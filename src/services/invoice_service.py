import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from src.repositories.invoice_repository import (
    DuplicateInvoiceError as RepoDuplicateInvoiceError,
    insert_invoice,
)
from src.services.ap.peppol_parser import ParsedInvoice, PeppolParser

logger = logging.getLogger("services.invoice")


# ─── Excepciones de Dominio ───


class InvoiceServiceError(Exception):
    """Base exception for invoice service errors."""
    pass


class UnsupportedFormatError(InvoiceServiceError):
    def __init__(self, extension: str, allowed: list[str]):
        self.extension = extension
        self.allowed = allowed

        super().__init__(
            f"Unsupported format: {extension}. "
            f"Allowed formats: {', '.join(allowed)}"
        )


class FileTooLargeError(InvoiceServiceError):
    def __init__(self, actual_bytes: int, max_bytes: int):
        self.actual_bytes = actual_bytes
        self.max_bytes = max_bytes

        super().__init__(
            f"Maximum allowed size is {max_bytes / 1024 / 1024:.0f}MB. "
            f"Got {actual_bytes / 1024 / 1024:.2f}MB"
        )


class MissingFilenameError(InvoiceServiceError):
    pass


class InvalidInvoiceError(InvoiceServiceError):
    """Raised when the invoice content is structurally invalid."""
    pass


class DuplicateInvoiceError(InvoiceServiceError):
    """Raised when trying to ingest an already existing invoice."""

    def __init__(
        self,
        raw_hash: str,
        existing_invoice_id: str | None = None,
    ):
        self.raw_hash = raw_hash
        self.existing_invoice_id = existing_invoice_id

        super().__init__(
            f"Invoice with hash {raw_hash} already exists"
        )


class MissingIbanError(InvoiceServiceError):
    """Raised when SEPA generation requires an IBAN that is missing or invalid."""
    pass


# ─── Modelos de Resultado ───


@dataclass
class InvoiceIngestResult:
    """Resultado de la ingestión de una factura."""

    invoice_id: str
    filename: str
    size_bytes: int
    content_hash: str
    status: str
    received_at: datetime
    parsed_invoice: ParsedInvoice | None = None


@dataclass
class SepaGenerateResult:
    """Resultado de la generación de un archivo SEPA."""

    payment_id: str
    invoice_id: str
    xml_payload: str
    amount: str
    currency: str
    creditor_iban: str
    generated_at: str


# ─── Servicio Principal ───


class InvoiceService:
    """
    Orquesta todo el flujo de ingestión de facturas y generación SEPA.
    Contiene TODAS las reglas de negocio: formatos, tamaños, parsing.
    """

    ALLOWED_EXTENSIONS = {
        ".xml",
        ".pdf",
        ".csv",
        ".xlsx",
    }

    MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10MB

    def __init__(self, session):
        self.session = session

    async def ingest(self, file: UploadFile) -> InvoiceIngestResult:
        """Punto de entrada único para ingestión de facturas."""

        filename = self._validate_filename(file.filename)
        extension = self._extract_extension(filename)

        self._ensure_supported_format(extension)

        content = await self._read_and_validate_size(file)
        content_hash = self._compute_hash(content)

        parsed_invoice = await self._parse_if_applicable(
            content,
            extension,
            filename,
        )

        canonical_data = self._build_canonical_data(
            parsed_invoice,
            filename,
            extension,
        )

        stored_invoice = await self._save_with_idempotency(
            content_hash,
            filename,
            extension,
            canonical_data,
        )

        return InvoiceIngestResult(
            invoice_id=str(stored_invoice.id),
            filename=filename,
            size_bytes=len(content),
            content_hash=content_hash,
            status="received",
            received_at=datetime.now(timezone.utc),
            parsed_invoice=parsed_invoice,
        )

    async def generate_sepa(
        self,
        *,
        invoice_id: str,
        debtor_name: str,
        debtor_iban: str,
        debtor_bic: str | None = None,
        requested_execution_date: str | None = None,
    ) -> SepaGenerateResult:
        """Genera un archivo SEPA pain.001 a partir de una factura ingestada."""

        from sqlalchemy import select

        from src.db.models import Invoice as InvoiceModel
        from src.services.ap.sepa_generator import (
            SepaGenerationError,
            SepaGenerator,
        )
        from src.services.ap.validation.rules.iban_validator import (
            validate_iban,
        )

        result = await self.session.execute(
            select(InvoiceModel).where(
                InvoiceModel.id == invoice_id
            )
        )

        invoice = result.scalar_one_or_none()

        if not invoice:
            raise InvoiceServiceError(
                f"Invoice {invoice_id} not found"
            )

        canonical = invoice.canonical_data

        if not isinstance(canonical, dict):
            raise InvoiceServiceError(
                "Invoice canonical_data is not a valid object"
            )

        amount_raw = canonical.get("total_amount")

        if amount_raw is None:
            raise InvoiceServiceError(
                "Invoice missing total_amount in canonical_data"
            )

        amount = Decimal(str(amount_raw))

        creditor_name = canonical.get("supplier_name")
        creditor_iban = canonical.get("creditor_iban")
        creditor_bic = canonical.get("creditor_bic")

        currency = canonical.get("currency", "EUR")

        if not creditor_iban:
            raise MissingIbanError(
                "Invoice missing creditor_iban; "
                "cannot generate SEPA without payee account"
            )

        iban_result = validate_iban(creditor_iban)

        if not iban_result.is_valid:
            raise MissingIbanError(
                f"Invalid creditor IBAN: {iban_result.error}"
            )

        execution_date = (
            date.fromisoformat(requested_execution_date)
            if requested_execution_date
            else date.today()
        )

        payment_id = (
            f"PAY-"
            f"{hashlib.sha256(invoice_id.encode()).hexdigest()[:12].upper()}"
        )

        try:
            xml_bytes = SepaGenerator.generate(
                message_id=payment_id,
                creation_date_time=datetime.now(
                    timezone.utc
                ).isoformat(timespec="seconds"),
                initiating_party_name=debtor_name,
                payment_info_id=f"{payment_id}-001",
                requested_execution_date=execution_date,
                debtor_name=debtor_name,
                debtor_iban=debtor_iban,
                debtor_bic=debtor_bic,
                creditor_name=creditor_name or "Unknown Supplier",
                creditor_iban=(
                    iban_result.normalized_iban
                    or creditor_iban
                ),
                creditor_bic=creditor_bic,
                amount=amount,
                currency=currency,
            )

        except SepaGenerationError as e:
            raise InvoiceServiceError(
                f"SEPA generation failed: {e}"
            ) from e

        logger.info(
            "Generated SEPA payment %s for invoice %s",
            payment_id,
            invoice_id,
        )

        return SepaGenerateResult(
            payment_id=payment_id,
            invoice_id=invoice_id,
            xml_payload=xml_bytes.decode("utf-8"),
            amount=f"{amount:.2f}",
            currency=currency,
            creditor_iban=(
                iban_result.normalized_iban
                or creditor_iban
            ),
            generated_at=datetime.now(
                timezone.utc
            ).isoformat(),
        )

    # ─── Métodos Privados ───

    def _validate_filename(
        self,
        filename: str | None,
    ) -> str:
        if not filename:
            logger.warning(
                "Rejected file: no filename provided"
            )

            raise MissingFilenameError(
                "Filename is required"
            )

        return filename

    def _extract_extension(self, filename: str) -> str:
        return Path(filename).suffix.lower()

    def _ensure_supported_format(
        self,
        extension: str,
    ) -> None:
        if extension not in self.ALLOWED_EXTENSIONS:
            logger.warning(
                "Rejected file: unsupported format %s",
                extension,
            )

            raise UnsupportedFormatError(
                extension,
                list(self.ALLOWED_EXTENSIONS),
            )

    async def _read_and_validate_size(
        self,
        file: UploadFile,
    ) -> bytes:
        content = await file.read()

        if len(content) > self.MAX_SIZE_BYTES:
            logger.warning(
                "Rejected file %s: file size exceeds %s bytes",
                file.filename,
                self.MAX_SIZE_BYTES,
            )

            raise FileTooLargeError(
                len(content),
                self.MAX_SIZE_BYTES,
            )

        return content

    def _compute_hash(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    async def _parse_if_applicable(
        self,
        content: bytes,
        extension: str,
        filename: str,
    ) -> ParsedInvoice | None:
        if extension != ".xml":
            return None

        try:
            return await run_in_threadpool(
                PeppolParser.parse,
                content,
            )

        except ValueError as e:
            logger.warning(
                "XML parsing failed for %s: %s",
                filename,
                str(e),
            )

            raise InvalidInvoiceError(
                f"XML invoice parsing failed: {str(e)}"
            ) from e

    def _build_canonical_data(
        self,
        parsed_invoice: ParsedInvoice | None,
        filename: str,
        extension: str,
    ) -> dict:
        if parsed_invoice:
            return parsed_invoice.model_dump(mode="json")

        return {
            "filename": filename,
            "source_format": extension.lstrip("."),
        }

    async def _save_with_idempotency(
        self,
        content_hash: str,
        filename: str,
        extension: str,
        canonical_data: dict,
    ):
        try:
            return await insert_invoice(
                self.session,
                raw_hash=content_hash,
                filename=filename,
                source_format=extension.lstrip("."),
                canonical_data=canonical_data,
            )

        except RepoDuplicateInvoiceError as e:
            logger.info(
                "Duplicate invoice detected: hash=%s",
                e.raw_hash,
            )

            raise DuplicateInvoiceError(
                e.raw_hash,
                str(e.existing_invoice_id),
            ) from e