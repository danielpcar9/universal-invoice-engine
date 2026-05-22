import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Invoice


class DuplicateInvoiceError(Exception):
    def __init__(self, raw_hash: str, existing_invoice_id: uuid.UUID | None) -> None:
        self.raw_hash = raw_hash
        self.existing_invoice_id = existing_invoice_id
        super().__init__(f"Invoice with raw_hash={raw_hash} already exists")


async def get_invoice_by_raw_hash(
    session: AsyncSession,
    raw_hash: str,
) -> Invoice | None:
    result = await session.execute(select(Invoice).where(Invoice.raw_hash == raw_hash))
    return result.scalar_one_or_none()


async def insert_invoice(
    session: AsyncSession,
    *,
    raw_hash: str,
    filename: str,
    source_format: str,
    canonical_data: dict[str, Any],
    status: str = "received",
) -> Invoice:
    invoice = Invoice(
        raw_hash=raw_hash,
        filename=filename,
        source_format=source_format,
        canonical_data=canonical_data,
        status=status,
    )
    session.add(invoice)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        existing_invoice = await get_invoice_by_raw_hash(session, raw_hash)
        existing_invoice_id = existing_invoice.id if existing_invoice else None
        raise DuplicateInvoiceError(raw_hash, existing_invoice_id) from exc

    await session.refresh(invoice)
    return invoice
