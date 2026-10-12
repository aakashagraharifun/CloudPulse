"""Anomaly detection, incident and investigation API schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.common import APIModel, Money

SeverityLiteral = Literal["low", "medium", "high", "critical"]
StatusLiteral = Literal["open", "acknowledged", "resolved"]
ScopeLiteral = Literal[
    "total",
    "provider",
    "account_id",
    "service",
    "region",
    "resource_id",
    "usage_type",
    "project",
    "environment",
]


class DetectionSettingsBase(APIModel):
    pct_threshold: Decimal = Field(ge=0, le=100_000, description="Minimum % increase")
    abs_threshold: Decimal = Field(ge=0, le=1_000_000_000, description="Minimum increase")
    z_threshold: Decimal = Field(ge=0, le=100, description="Minimum robust z-score; 0 disables")
    new_spend_threshold: Decimal = Field(ge=0, le=1_000_000_000)
    min_history_days: int = Field(ge=3, le=365)
    baseline_window_days: int = Field(ge=7, le=365)
    evaluation_window_days: int = Field(ge=1, le=90)
    severity_medium_pct: Decimal = Field(ge=0, le=100_000)
    severity_high_pct: Decimal = Field(ge=0, le=100_000)
    severity_critical_pct: Decimal = Field(ge=0, le=100_000)
    severity_medium_abs: Decimal = Field(ge=0, le=1_000_000_000)
    severity_high_abs: Decimal = Field(ge=0, le=1_000_000_000)
    severity_critical_abs: Decimal = Field(ge=0, le=1_000_000_000)
    scopes: list[ScopeLiteral] = Field(min_length=1)


class DetectionSettingsUpdate(DetectionSettingsBase):
    @field_validator("scopes")
    @classmethod
    def _unique_scopes(cls, scopes: list[str]) -> list[str]:
        return list(dict.fromkeys(scopes))

    @model_validator(mode="after")
    def _consistent(self) -> "DetectionSettingsUpdate":
        if self.min_history_days > self.baseline_window_days:
            raise ValueError("min_history_days cannot exceed baseline_window_days.")
        if not (self.severity_medium_pct <= self.severity_high_pct <= self.severity_critical_pct):
            raise ValueError("Severity percentages must increase from medium to critical.")
        if not (self.severity_medium_abs <= self.severity_high_abs <= self.severity_critical_abs):
            raise ValueError("Severity amounts must increase from medium to critical.")
        return self


class DetectionSettingsRead(DetectionSettingsBase):
    updated_at: datetime


class DetectionRunRead(APIModel):
    id: int
    trigger: str
    status: Literal["running", "completed", "failed"]
    started_at: datetime
    finished_at: datetime | None
    currencies: list[str] | None
    evaluation_start: date | None
    evaluation_end: date | None
    series_evaluated: int
    points_evaluated: int
    points_insufficient_history: int
    anomalies_detected: int
    incidents_created: int
    notes: list[str] | None
    error: str | None
    settings_snapshot: dict[str, Any]


class DetectionRead(APIModel):
    id: int
    anomaly_date: date
    kind: Literal["spike", "new_spend"]
    severity: SeverityLiteral
    observed_cost: Money
    expected_cost: Money
    deviation_abs: Money
    deviation_pct: Decimal | None
    z_score: Decimal | None
    baseline_method: str
    baseline_points: int
    thresholds: dict[str, Any]
    evidence: dict[str, Any]
    first_detected_at: datetime
    last_evaluated_at: datetime


class IncidentSummary(APIModel):
    id: int
    title: str
    status: StatusLiteral
    severity: SeverityLiteral
    kind: Literal["spike", "new_spend"]
    currency: str
    scope_type: str
    scope_value: str
    start_date: date
    end_date: date
    observed_cost: Money
    expected_cost: Money
    deviation_abs: Money
    peak_deviation_pct: Decimal | None
    detection_count: int
    created_at: datetime
    updated_at: datetime


class IncidentEventRead(APIModel):
    id: int
    event_type: str
    actor: str
    message: str
    created_at: datetime


class IncidentDetail(IncidentSummary):
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    resolved_at: datetime | None
    resolved_by: str | None
    resolution_note: str | None
    detections: list[DetectionRead]
    events: list[IncidentEventRead]


class IncidentCounts(APIModel):
    open: int
    acknowledged: int
    resolved: int


def _strip(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    return value


# The acting user is always the signed-in user; it is never taken from the body.


class AcknowledgeInput(APIModel):
    note: str | None = Field(None, max_length=5000)


class ResolveInput(APIModel):
    resolution_note: str = Field(min_length=1, max_length=5000)

    @field_validator("resolution_note")
    @classmethod
    def _note(cls, value: str) -> str:
        return _strip(value)


class ReopenInput(APIModel):
    reason: str | None = Field(None, max_length=5000)


class NoteInput(APIModel):
    body: str = Field(min_length=1, max_length=5000)

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        return _strip(value)


# --- investigation -------------------------------------------------------------


class UsageComparisonRead(APIModel):
    unit: str | None
    baseline_daily_quantity: Decimal | None
    current_daily_quantity: Decimal | None
    quantity_ratio: float | None
    cost_ratio: float | None
    driver: Literal["usage", "rate", "mixed", "mixed_units", "new", "unknown"]


class ContributorRead(APIModel):
    key: str | None
    label: str
    current_cost: Money
    baseline_cost: Money
    baseline_daily_avg: Money
    current_daily_avg: Money
    change: Money
    share_of_increase_pct: float | None
    is_new: bool
    usage: UsageComparisonRead | None


class DimensionAnalysisRead(APIModel):
    dimension: str
    label: str
    contributors: list[ContributorRead]
    other_change: Money
    members_total: int


class SuggestionRead(APIModel):
    title: str
    detail: str
    evidence: str


class ChartPointRead(APIModel):
    day: date
    cost: Money | None
    expected: Money | None
    is_anomaly: bool


class RelatedIncidentRead(APIModel):
    id: int
    title: str
    status: StatusLiteral
    severity: SeverityLiteral
    start_date: date
    end_date: date


class InvestigationRead(APIModel):
    incident_id: int
    currency: str
    scope_label: str
    current_start: date
    current_end: date
    current_days_with_data: int
    baseline_start: date
    baseline_end: date
    baseline_days_with_data: int
    current_total: Money
    baseline_daily_avg: Money | None
    expected_total_from_baseline: Money | None
    total_change: Money | None
    observed_cost: Money
    expected_cost: Money
    deviation_abs: Money
    peak_deviation_pct: Decimal | None
    confidence: Literal["high", "medium", "low"]
    confidence_statement: str
    summary: list[str]
    explanations: list[str]
    suggestions: list[SuggestionRead]
    limitations: list[str]
    dimensions: list[DimensionAnalysisRead]
    chart: list[ChartPointRead]
    related_incidents: list[RelatedIncidentRead]
