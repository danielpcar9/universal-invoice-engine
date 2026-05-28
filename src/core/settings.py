import os
from dataclasses import dataclass


@dataclass(frozen=True)
class InvoiceSettings:
    allowed_extensions: set[str]
    max_size_bytes: int
    database_url: str


invoice_settings = InvoiceSettings(
    allowed_extensions={
        ".xml",
        ".pdf",
        ".csv",
        ".xlsx",
    },
    max_size_bytes=10 * 1024 * 1024,
    database_url=os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://uie_app:uie_password@localhost:5432/universal_invoice_engine",
    ),
)
