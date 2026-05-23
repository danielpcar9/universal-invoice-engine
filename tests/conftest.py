import asyncio
import os

os.environ["TESTING"] = "1"

import pytest
from sqlalchemy import delete

from src.db.models import Invoice
from src.db.session import AsyncSessionLocal, create_database_schema, engine


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
def ensure_database_schema(event_loop) -> None:
    event_loop.run_until_complete(create_database_schema())
    event_loop.run_until_complete(engine.dispose())


@pytest.fixture(autouse=True)
def clean_invoices_table(event_loop) -> None:
    event_loop.run_until_complete(engine.dispose())

    async def _clean() -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(Invoice))
            await session.commit()

    event_loop.run_until_complete(_clean())
    event_loop.run_until_complete(engine.dispose())
