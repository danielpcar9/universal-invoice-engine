from dataclasses import dataclass


@dataclass(frozen=True)
class InvoiceSettings:
    allowed_extensions: set[str]
    max_size_bytes: int


invoice_settings = InvoiceSettings(
    allowed_extensions={
        ".xml",
        ".pdf",
        ".csv",
        ".xlsx",
    },
    max_size_bytes=10 * 1024 * 1024,
)