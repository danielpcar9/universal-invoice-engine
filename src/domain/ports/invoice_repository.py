from typing import Any, Protocol

from src.domain.types import CanonicalInvoiceData


class InvoiceRepositoryProtocol(Protocol):
    async def insert_invoice(
        self,
        *,
        raw_hash: str,
        filename: str,
        source_format: str,
        canonical_data: CanonicalInvoiceData,
    ):
        ...

    async def get_by_id(
        self,
        *,
        invoice_id: str,
    ) -> Any:
        ...
