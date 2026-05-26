import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from src.api.dependencies.auth import verify_api_key
from src.api.dependencies.services import get_invoice_service
from src.services.invoice_service import InvoiceService, SepaGenerateResult

logger = logging.getLogger("api.payments")

router = APIRouter(
    prefix="/ap/payments",
    tags=["accounts-payable-payments"],
    dependencies=[Depends(verify_api_key)],
)


class SepaGenerateRequest(BaseModel):
    invoice_id: str = Field(min_length=36)
    debtor_name: str = Field(min_length=1)
    debtor_iban: str = Field(min_length=15)
    debtor_bic: str | None = None
    requested_execution_date: str | None = None


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
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> SepaGenerateResponse:
    result: SepaGenerateResult = await service.generate_sepa(
        invoice_id=body.invoice_id,
        debtor_name=body.debtor_name,
        debtor_iban=body.debtor_iban,
        debtor_bic=body.debtor_bic,
        requested_execution_date=body.requested_execution_date,
    )

    return SepaGenerateResponse(
        payment_id=result.payment_id,
        invoice_id=result.invoice_id,
        xml_payload=result.xml_payload,
        amount=result.amount,
        currency=result.currency,
        creditor_iban=result.creditor_iban,
        generated_at=result.generated_at,
    )