import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status
from pydantic import BaseModel

from src.api.dependencies.auth import verify_api_key
from src.api.dependencies.services import get_invoice_service
from src.services.ap.peppol_parser import ParsedInvoice
from src.services.invoice_service import InvoiceIngestResult, InvoiceService

logger = logging.getLogger("api.invoices")


class InvoiceIngestResponse(BaseModel):
    invoice_id: str
    filename: str
    size_bytes: int
    content_hash: str
    status: str
    received_at: datetime
    parsed_invoice: ParsedInvoice | None = None


router = APIRouter(
    prefix="/ap/invoices",
    tags=["accounts-payable"],
    dependencies=[Depends(verify_api_key)],
)


@router.post(
    "/ingest",
    status_code=status.HTTP_201_CREATED,
    summary="Ingest an Accounts Payable invoice",
)
async def ingest_invoice(
    file: Annotated[
        UploadFile,
        File(description="The invoice file to ingest (.xml, .pdf, .csv, .xlsx)"),
    ],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> InvoiceIngestResponse:
    """
    Ultra-thin router: only HTTP concerns.
    All business logic (validation, parsing, persistence) delegated to InvoiceService.
    Domain exceptions are translated to HTTP by global exception handlers in main.py.
    """
    result: InvoiceIngestResult = await service.ingest(file)

    return InvoiceIngestResponse(
        invoice_id=result.invoice_id,
        filename=result.filename,
        size_bytes=result.size_bytes,
        content_hash=result.content_hash,
        status=result.status,
        received_at=result.received_at,
        parsed_invoice=result.parsed_invoice,
    )