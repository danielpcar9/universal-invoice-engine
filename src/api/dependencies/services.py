from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db_session
from src.services.invoice_service import InvoiceService


async def get_invoice_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> InvoiceService:
    return InvoiceService(session)