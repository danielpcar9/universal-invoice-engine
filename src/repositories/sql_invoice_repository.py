from sqlalchemy import select

from src.db.models import Invoice
from src.repositories.invoice_repository import insert_invoice


class SqlInvoiceRepository:
    def __init__(self, session):
        self.session = session

    async def insert_invoice(
        self,
        *,
        raw_hash: str,
        filename: str,
        source_format: str,
        canonical_data,
    ):
        return await insert_invoice(
            self.session,
            raw_hash=raw_hash,
            filename=filename,
            source_format=source_format,
            canonical_data=canonical_data,
        )

    async def get_by_id(
        self,
        *,
        invoice_id: str,
    ):
        result = await self.session.execute(
            select(Invoice).where(Invoice.id == invoice_id)
        )
        return result.scalar_one_or_none()
