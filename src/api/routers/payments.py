import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.auth import verify_api_key
from src.db.models import Invoice
from src.db.session import get_db_session
from src.services.ap.sepa_generator import SepaGenerator, SepaGenerationError

logger = logging.getLogger("api.payments")

router = APIRouter(
    prefix="/ap/payments",
    tags=["accounts-payable-payments"],
    dependencies=[Depends(verify_api_key)],
)


class SepaGenerateRequest(BaseModel):
    invoice_id: uuid.UUID
    debtor_name: str = Field(min_length=1)
    debtor_iban: str = Field(min_length=15)
    debtor_bic: str | None = None
    requested_execution_date: date | None = None


class SepaGenerateResponse(BaseModel):
    payment_id: str
    invoice_id: str
    xml_payload: str
    amount: str
    currency: str
    creditor_iban: str
    generated_at: str


@router.post(
    "/sepa/generate",
    status_code=status.HTTP_201_CREATED,
    summary="Generate a SEPA pain.001 payment file from an ingested invoice",
)
async def generate_sepa(
    body: SepaGenerateRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SepaGenerateResponse:
    # 1. Fetch invoice by ID
    result = await session.execute(
        select(Invoice).where(Invoice.id == body.invoice_id)
    )
    invoice = result.scalar_one_or_none()

    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice {body.invoice_id} not found",
        )

    canonical = invoice.canonical_data
    if not isinstance(canonical, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invoice canonical_data is not a valid object",
        )

    # 2. Extract payment-critical fields
    amount_raw = canonical.get("total_amount")
    if amount_raw is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invoice missing total_amount in canonical_data",
        )
    amount = Decimal(str(amount_raw))

    creditor_name = canonical.get("supplier_name")
    creditor_iban = canonical.get("creditor_iban")
    creditor_bic = canonical.get("creditor_bic")
    currency = canonical.get("currency", "EUR")

    if not creditor_iban:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invoice missing creditor_iban; cannot generate SEPA without payee account",
        )

    execution_date = body.requested_execution_date or date.today()
    payment_id = f"PAY-{uuid.uuid4().hex[:12].upper()}"

    try:
        xml_bytes = SepaGenerator.generate(
            message_id=payment_id,
            creation_date_time=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            initiating_party_name=body.debtor_name,
            payment_info_id=f"{payment_id}-001",
            requested_execution_date=execution_date,
            debtor_name=body.debtor_name,
            debtor_iban=body.debtor_iban,
            debtor_bic=body.debtor_bic,
            creditor_name=creditor_name or "Unknown Supplier",
            creditor_iban=creditor_iban,
            creditor_bic=creditor_bic,
            amount=amount,
            currency=currency,
        )
    except SepaGenerationError as e:
        logger.error(f"SEPA generation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"SEPA generation failed: {e}",
        )

    logger.info(f"Generated SEPA payment {payment_id} for invoice {body.invoice_id}")

    return SepaGenerateResponse(
        payment_id=payment_id,
        invoice_id=str(body.invoice_id),
        xml_payload=xml_bytes.decode("utf-8"),
        amount=f"{amount:.2f}",
        currency=currency,
        creditor_iban=creditor_iban,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )