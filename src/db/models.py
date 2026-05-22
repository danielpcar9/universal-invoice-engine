import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    raw_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_format: Mapped[str] = mapped_column(String(50), nullable=False)
    canonical_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="received")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
