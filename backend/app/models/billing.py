"""Billing imports and normalized billing records."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

# Money is stored as NUMERIC (exact decimal), never as binary floating point.
MONEY = Numeric(18, 8)
QUANTITY = Numeric(24, 8)


class ImportStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ImportSource(StrEnum):
    UPLOAD = "upload"
    SAMPLE = "sample"
    CONNECTOR = "connector"


class BillingImport(TimestampMixin, Base):
    """One uploaded billing file and the outcome of ingesting it."""

    __tablename__ = "billing_imports"
    __table_args__ = (
        CheckConstraint("status IN ('processing', 'completed', 'failed')", name="status_valid"),
        CheckConstraint("source IN ('upload', 'sample', 'connector')", name="source_valid"),
        # The same file content can only be imported successfully once. Connector syncs
        # are exempt: a provider may restate data back to an earlier state, and their
        # records are reconciled per sync window instead (see ingestion service).
        Index(
            "uq_billing_imports_completed_sha256",
            "file_sha256",
            unique=True,
            postgresql_where=text("status = 'completed' AND source <> 'connector'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default=ImportSource.UPLOAD)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    detected_format: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ImportStatus.PROCESSING)

    rows_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_duplicate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_invalid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Connector syncs: stale records of earlier syncs removed from the sync window.
    rows_replaced: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    connector_id: Mapped[int | None] = mapped_column(
        ForeignKey("connectors.id", ondelete="SET NULL"), index=True
    )

    # Up to MAX_REPORTED_ERRORS entries of {"line", "column", "message"}.
    errors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB(none_as_null=True))
    error_summary: Mapped[str | None] = mapped_column(Text)

    currencies: Mapped[list[str] | None] = mapped_column(JSONB(none_as_null=True))
    date_start: Mapped[date | None] = mapped_column(Date)
    date_end: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    records: Mapped[list["BillingRecord"]] = relationship(
        back_populates="billing_import", passive_deletes=True
    )


class BillingRecord(Base):
    """A single normalized daily cost line item (canonical billing model)."""

    __tablename__ = "billing_records"
    __table_args__ = (
        Index("ix_billing_records_currency_date", "currency", "usage_date"),
        Index("ix_billing_records_date_service", "usage_date", "service"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    import_id: Mapped[int] = mapped_column(
        ForeignKey("billing_imports.id", ondelete="CASCADE"), nullable=False, index=True
    )

    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    account_id: Mapped[str | None] = mapped_column(String(128))
    service: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(512))
    region: Mapped[str | None] = mapped_column(String(64))
    usage_type: Mapped[str | None] = mapped_column(String(255))
    # AI/LLM model (e.g. "gpt-4o"), when the line item is model usage.
    model: Mapped[str | None] = mapped_column(String(128), index=True)
    usage_quantity: Mapped[Decimal | None] = mapped_column(QUANTITY)
    usage_unit: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    # Tags exactly as they appeared in the source file.
    project_tag: Mapped[str | None] = mapped_column(String(128))
    environment_tag: Mapped[str | None] = mapped_column(String(128))
    # Effective attribution: the source tag, else the first matching allocation rule.
    project: Mapped[str | None] = mapped_column(String(128), index=True)
    environment: Mapped[str | None] = mapped_column(String(128))

    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    extra_attributes: Mapped[dict[str, str] | None] = mapped_column(JSONB(none_as_null=True))
    # SHA-256 of the canonical values (plus occurrence index); prevents duplicate records.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    billing_import: Mapped[BillingImport] = relationship(back_populates="records")
