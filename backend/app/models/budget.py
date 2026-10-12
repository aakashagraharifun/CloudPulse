"""Budgets, threshold crossings, notification channels and delivery attempts."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.anomaly import PERCENT
from app.models.billing import MONEY


class Budget(TimestampMixin, Base):
    __tablename__ = "budgets"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("period IN ('monthly', 'quarterly', 'yearly')", name="period_valid"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
        CheckConstraint("renotify_hours IS NULL OR renotify_hours > 0", name="renotify_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False, default="monthly")
    # "total" for all spend, otherwise a billing dimension plus the value to match.
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, default="total")
    scope_value: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # Alert when actual spend reaches these percentages of the budget.
    thresholds: Mapped[list[int]] = mapped_column(
        JSONB, nullable=False, default=lambda: [50, 80, 100]
    )
    # None: alert once per threshold per period. Otherwise repeat while still above.
    renotify_hours: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    alerts: Mapped[list["BudgetAlert"]] = relationship(
        back_populates="budget", cascade="all, delete-orphan", passive_deletes=True
    )


class BudgetAlert(Base):
    """A threshold crossing; unique per budget, period and threshold."""

    __tablename__ = "budget_alerts"
    __table_args__ = (UniqueConstraint("budget_id", "period_start", "threshold_pct"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    budget_id: Mapped[int] = mapped_column(
        ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    threshold_pct: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    budget_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    utilization_pct: Mapped[Decimal] = mapped_column(PERCENT, nullable=False)
    data_as_of: Mapped[date] = mapped_column(Date, nullable=False)
    crossed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notification_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    budget: Mapped[Budget] = relationship(back_populates="alerts")


class NotificationChannel(TimestampMixin, Base):
    __tablename__ = "notification_channels"
    __table_args__ = (
        CheckConstraint("type IN ('webhook', 'email')", name="type_valid"),
        CheckConstraint(
            "min_severity IN ('low', 'medium', 'high', 'critical')", name="min_severity_valid"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    # Webhook URL, or comma-separated e-mail recipients.
    target: Mapped[str] = mapped_column(String(2048), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_budget_alerts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_incidents: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    min_severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")


class NotificationDelivery(Base):
    """Every attempt to notify a channel, including failures."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        # The same event is never delivered twice to the same channel.
        UniqueConstraint("channel_id", "event_key"),
        CheckConstraint("status IN ('pending', 'sent', 'failed')", name="status_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("notification_channels.id", ondelete="SET NULL"), index=True
    )
    channel_name: Mapped[str] = mapped_column(String(120), nullable=False)
    channel_type: Mapped[str] = mapped_column(String(16), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_key: Mapped[str] = mapped_column(String(200), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
