"""Live billing connectors: scheduled pulls from provider billing APIs."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ConnectorKind(StrEnum):
    AWS_CUR_S3 = "aws_cur_s3"
    AWS_COST_EXPLORER = "aws_cost_explorer"
    OPENAI_COSTS = "openai_costs"
    ANTHROPIC_COSTS = "anthropic_costs"


class SyncStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Connector(TimestampMixin, Base):
    """One configured connection to a provider's billing API.

    `config` holds non-secret settings (bucket, region, grouping). Credentials are
    stored only as a Fernet token in `credentials_encrypted`; `credentials_hint`
    is a masked form (e.g. "sk-ant-…9Xyz") for display.
    """

    __tablename__ = "connectors"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('aws_cur_s3', 'aws_cost_explorer', 'openai_costs', 'anthropic_costs')",
            name="kind_valid",
        ),
        CheckConstraint(
            "last_sync_status IS NULL OR last_sync_status IN ('running', 'succeeded', 'failed')",
            name="last_sync_status_valid",
        ),
        CheckConstraint("sync_interval_hours BETWEEN 0 AND 168", name="interval_range"),
        CheckConstraint("lookback_days BETWEEN 1 AND 365", name="lookback_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    credentials_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    credentials_hint: Mapped[str] = mapped_column(String(64), nullable=False)
    # 0 = manual syncs only.
    sync_interval_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)

    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Who the provider says the credentials belong to (org name, AWS ARN, ...).
    verified_identity: Mapped[str | None] = mapped_column(String(255))

    last_sync_status: Mapped[str | None] = mapped_column(String(16))
    last_sync_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_message: Mapped[str | None] = mapped_column(Text)
    # use_alter: billing_imports also references connectors (a cycle), so this
    # constraint is created after both tables and ignored when sorting tables.
    last_import_id: Mapped[int | None] = mapped_column(
        ForeignKey("billing_imports.id", ondelete="SET NULL", use_alter=True)
    )
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
