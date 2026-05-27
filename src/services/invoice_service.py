import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool
from src.core.settings import invoice_settings
from src.repositories.invoice_repository import (
    DuplicateInvoiceError as RepoDuplicateInvoiceError,
    insert_invoice,
)
from src.services.ap.peppol_parser import ParsedInvoice, PeppolParser

logger = logging.getLogger("services.invoice")
CanonicalInvoiceData = dict[str, Any]


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


# ─── Servicio Principal ───


class InvoiceService:
    """
    Orquesta todo el flujo de ingestión de facturas y generación SEPA.
    Contiene TODAS las reglas de negocio: formatos, tamaños, parsing.
    """

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
        if extension not in invoice_settings.allowed_extensions:
            logger.warning(
                "Rejected file: unsupported format %s",
                extension,
            )

            raise UnsupportedFormatError(
                extension,
                list(invoice_settings.allowed_extensions),
            )

    async def _read_and_validate_size(
        self,
        file: UploadFile,
    ) -> bytes:
        content = await file.read()

        if len(content) > invoice_settings.max_size_bytes:
            logger.warning(
                "Rejected file %s: file size exceeds %s bytes",
                file.filename,
                invoice_settings.max_size_bytes,
            )

            raise FileTooLargeError(
                len(content),
                invoice_settings.max_size_bytes,
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
    ) -> CanonicalInvoiceData:
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
        canonical_data: CanonicalInvoiceData,
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