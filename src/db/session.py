import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from src.core.settings import invoice_settings

DATABASE_URL = invoice_settings.database_url

_engine_kwargs: dict = {"pool_pre_ping": True}
if os.getenv("TESTING") == "1":
    _engine_kwargs["poolclass"] = NullPool

engine = create_async_engine(
    DATABASE_URL,
    **_engine_kwargs,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


async def create_database_schema() -> None:
    from src.db.models import Base

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
