import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://uie_app:uie_password@localhost:5432/universal_invoice_engine",
)

engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
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
