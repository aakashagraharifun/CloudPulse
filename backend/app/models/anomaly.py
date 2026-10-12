"""Anomaly detection settings, runs, detections and incidents."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.billing import MONEY

PERCENT = Numeric(12, 2)


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


SEVERITY_ORDER = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}


class IncidentStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class DetectionSettings(Base):
    """Single-row table (id = 1) holding the configurable detection thresholds."""

    __tablename__ = "detection_settings"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    pct_threshold: Mapped[Decimal] = mapped_column(PERCENT, nullable=False, default=Decimal(25))
    abs_threshold: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(25))
    z_threshold: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=Decimal(3))
    new_spend_threshold: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(50))
    min_history_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    baseline_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=28)
    evaluation_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    severity_medium_pct: Mapped[Decimal] = mapped_column(
        PERCENT, nullable=False, default=Decimal(50)
    )
    severity_high_pct: Mapped[Decimal] = mapped_column(
        PERCENT, nullable=False, default=Decimal(100)
    )
    severity_critical_pct: Mapped[Decimal] = mapped_column(
        PERCENT, nullable=False, default=Decimal(300)
    )
    severity_medium_abs: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal(100)
    )
    severity_high_abs: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(500))
    severity_critical_abs: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal(2000)
    )
    # Which scopes to evaluate: "total" and/or billing dimensions such as "service".
    scopes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=lambda: ["total", "service"]
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DetectionRun(Base):
    __tablename__ = "detection_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="status_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settings_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    currencies: Mapped[list[str] | None] = mapped_column(JSONB(none_as_null=True))
    evaluation_start: Mapped[date | None] = mapped_column(Date)
    evaluation_end: Mapped[date | None] = mapped_column(Date)
    series_evaluated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    points_evaluated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    points_insufficient_history: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    anomalies_detected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    incidents_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Human-readable limitations, e.g. series skipped for insufficient history.
    notes: Mapped[list[str] | None] = mapped_column(JSONB(none_as_null=True))
    error: Mapped[str | None] = mapped_column(Text)


class Incident(TimestampMixin, Base):
    """One cost event for one scope; consecutive anomalous days are grouped together."""

    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'acknowledged', 'resolved')", name="status_valid"),
        CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="severity_valid"),
        Index("ix_incidents_scope", "currency", "scope_type", "scope_value", "status"),
        Index("ix_incidents_status_start", "status", "start_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=IncidentStatus.OPEN)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # spike | new_spend
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_value: Mapped[str] = mapped_column(String(512), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    observed_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    expected_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    deviation_abs: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    peak_deviation_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    detection_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(String(80))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(80))
    resolution_note: Mapped[str | None] = mapped_column(Text)

    detections: Mapped[list["AnomalyDetection"]] = relationship(
        back_populates="incident", order_by="AnomalyDetection.anomaly_date"
    )
    events: Mapped[list["IncidentEvent"]] = relationship(
        back_populates="incident",
        order_by="IncidentEvent.id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AnomalyDetection(Base):
    """A single anomalous (scope, day) with the full evidence behind the decision."""

    __tablename__ = "anomaly_detections"
    __table_args__ = (
        UniqueConstraint(
            "currency", "scope_type", "scope_value", "anomaly_date", name="uq_detection_scope_day"
        ),
        CheckConstraint("kind IN ('spike', 'new_spend')", name="kind_valid"),
        CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="severity_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("detection_runs.id", ondelete="SET NULL"), index=True
    )
    incident_id: Mapped[int | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="SET NULL"), index=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_value: Mapped[str] = mapped_column(String(512), nullable=False)
    anomaly_date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)

    observed_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    expected_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    deviation_abs: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    deviation_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    z_score: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    baseline_method: Mapped[str] = mapped_column(String(32), nullable=False)
    baseline_points: Mapped[int] = mapped_column(Integer, nullable=False)
    # Thresholds in force when the decision was made, and the baseline data used.
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    first_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    incident: Mapped[Incident | None] = relationship(back_populates="detections")


class IncidentEvent(Base):
    """Audit trail and notes for an incident (created, status changes, notes, ...)."""

    __tablename__ = "incident_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    incident: Mapped[Incident] = relationship(back_populates="events")
