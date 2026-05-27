import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from src.domain.ports.invoice_repository import InvoiceRepositoryProtocol
from src.domain.value_objects.iban import IBAN

logger = logging.getLogger("services.sepa_payment")


# ─── Modelos de Resultado ───


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


# ─── Excepciones ───


class SepaPaymentServiceError(Exception):
    """Base exception for SEPA payment service errors."""
    pass


class MissingIbanError(SepaPaymentServiceError):
    """Raised when SEPA generation requires an IBAN that is missing or invalid."""
    pass


# ─── Servicio de Pagos SEPA ───


class SepaPaymentService:
    """
    Orquesta la generación de pagos SEPA (pain.001).
    Responsabilidades únicas:
    - Cargar datos de factura
    - Validar IBAN
    - Generar XML SEPA
    """

    def __init__(
        self,
        invoice_repository: InvoiceRepositoryProtocol,
    ):
        self.invoice_repository = invoice_repository

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

        from src.services.ap.sepa_generator import (
            SepaGenerationError,
            SepaGenerator,
        )

        invoice = await self.invoice_repository.get_by_id(
            invoice_id=invoice_id,
        )

        if not invoice:
            raise SepaPaymentServiceError(
                f"Invoice {invoice_id} not found"
            )

        canonical = invoice.canonical_data

        if not isinstance(canonical, dict):
            raise SepaPaymentServiceError(
                "Invoice canonical_data is not a valid object"
            )

        amount_raw = canonical.get("total_amount")

        if amount_raw is None:
            raise SepaPaymentServiceError(
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

        try:
            creditor_iban_vo = IBAN(creditor_iban)

        except ValueError as e:
            raise MissingIbanError(
                f"Invalid creditor IBAN: {e}"
            ) from e

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
                creditor_iban=str(creditor_iban_vo),
                creditor_bic=creditor_bic,
                amount=amount,
                currency=currency,
            )

        except SepaGenerationError as e:
            raise SepaPaymentServiceError(
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
            creditor_iban=str(creditor_iban_vo),
            generated_at=datetime.now(
                timezone.utc
            ).isoformat(),
        )
