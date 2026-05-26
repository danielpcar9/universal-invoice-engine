import hashlib
import logging
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

from fastapi import UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from src.repositories.invoice_repository import (
    DuplicateInvoiceError,
    insert_invoice,
)
from src.services.ap.peppol_parser import ParsedInvoice, PeppolParser
from src.services.ap.validation.rules.iban_validator import (
    validate_iban,
)

logger = logging.getLogger("services.invoice")

ALLOWED_EXTENSIONS = {".xml", ".pdf", ".csv", ".xlsx"}
MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10MB


class InvoiceIngestResult(BaseModel):
    invoice_id: str
    filename: str
    size_bytes: int
    content_hash: str
    status: str
    received_at: datetime
    parsed_invoice: Optional[ParsedInvoice] = None


class SepaGenerateResult(BaseModel):
    payment_id: str
    invoice_id: str
    xml_payload: str
    amount: str
    currency: str
    creditor_iban: str
    generated_at: str


class InvoiceServiceError(Exception):
    pass


class UnsupportedFormatError(InvoiceServiceError):
    pass


class FileTooLargeError(InvoiceServiceError):
    pass


class InvalidInvoiceError(InvoiceServiceError):
    pass


class MissingIbanError(InvoiceServiceError):
    pass


class InvoiceService:
    """
    Orchestrates invoice ingestion, validation, and SEPA generation.
    This is the single entry point for AP invoice business logic.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def ingest(
        self,
        file: UploadFile,
    ) -> InvoiceIngestResult:
        """
        Ingest an invoice file: validate, parse, deduplicate, persist.
        """
        filename = file.filename
        if not filename:
            raise InvoiceServiceError("Filename is required")

        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise UnsupportedFormatError(
                f"Unsupported format: {ext}. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
            )

        content = await file.read()
        content_hash = hashlib.sha256(content).hexdigest()

        if len(content) > MAX_SIZE_BYTES:
            raise FileTooLargeError(
                f"Maximum allowed size is 10MB. Got {len(content) / 1024 / 1024:.2f}MB"
            )

        parsed_invoice = None
        if ext == ".xml":
            try:
                parsed_invoice = await run_in_threadpool(PeppolParser.parse, content)
            except ValueError as e:
                raise InvalidInvoiceError(f"XML invoice parsing failed: {e}")

        canonical_data = (
            parsed_invoice.model_dump(mode="json")
            if parsed_invoice
            else {"filename": filename, "source_format": ext.lstrip(".")}
        )

        try:
            stored_invoice = await insert_invoice(
                self.session,
                raw_hash=content_hash,
                filename=filename,
                source_format=ext.lstrip("."),
                canonical_data=canonical_data,
            )
        except DuplicateInvoiceError as e:
            raise DuplicateInvoiceError(e.raw_hash, e.existing_invoice_id) from e

        invoice_id = str(stored_invoice.id)
        logger.info(f"Successfully ingested invoice {filename} with ID: {invoice_id}")

        return InvoiceIngestResult(
            invoice_id=invoice_id,
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
        debtor_bic: Optional[str] = None,
        requested_execution_date: Optional[str] = None,
    ) -> SepaGenerateResult:
        """
        Generate a SEPA pain.001 payment file from an ingested invoice.
        """
        from sqlalchemy import select
        from src.db.models import Invoice as InvoiceModel
        from src.services.ap.sepa_generator import SepaGenerator, SepaGenerationError
        from datetime import date

        result = await self.session.execute(
            select(InvoiceModel).where(InvoiceModel.id == invoice_id)
        )
        invoice = result.scalar_one_or_none()

        if not invoice:
            raise InvoiceServiceError(f"Invoice {invoice_id} not found")

        canonical = invoice.canonical_data
        if not isinstance(canonical, dict):
            raise InvoiceServiceError("Invoice canonical_data is not a valid object")

        amount_raw = canonical.get("total_amount")
        if amount_raw is None:
            raise InvoiceServiceError("Invoice missing total_amount in canonical_data")

        amount = Decimal(str(amount_raw))
        creditor_name = canonical.get("supplier_name")
        creditor_iban = canonical.get("creditor_iban")
        creditor_bic = canonical.get("creditor_bic")
        currency = canonical.get("currency", "EUR")

        if not creditor_iban:
            raise MissingIbanError(
                "Invoice missing creditor_iban; cannot generate SEPA without payee account"
            )

        # Validate IBAN format before generating SEPA
        iban_result = validate_iban(creditor_iban)
        if not iban_result.is_valid:
            raise MissingIbanError(f"Invalid creditor IBAN: {iban_result.error}")

        execution_date = (
            date.fromisoformat(requested_execution_date)
            if requested_execution_date
            else date.today()
        )
        payment_id = f"PAY-{hashlib.sha256(invoice_id.encode()).hexdigest()[:12].upper()}"

        try:
            xml_bytes = SepaGenerator.generate(
                message_id=payment_id,
                creation_date_time=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                initiating_party_name=debtor_name,
                payment_info_id=f"{payment_id}-001",
                requested_execution_date=execution_date,
                debtor_name=debtor_name,
                debtor_iban=debtor_iban,
                debtor_bic=debtor_bic,
                creditor_name=creditor_name or "Unknown Supplier",
                creditor_iban=iban_result.normalized_iban or creditor_iban,
                creditor_bic=creditor_bic,
                amount=amount,
                currency=currency,
            )
        except SepaGenerationError as e:
            raise InvoiceServiceError(f"SEPA generation failed: {e}")

        logger.info(f"Generated SEPA payment {payment_id} for invoice {invoice_id}")

        return SepaGenerateResult(
            payment_id=payment_id,
            invoice_id=invoice_id,
            xml_payload=xml_bytes.decode("utf-8"),
            amount=f"{amount:.2f}",
            currency=currency,
            creditor_iban=iban_result.normalized_iban or creditor_iban,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )