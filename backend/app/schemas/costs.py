"""Cost analytics API schemas."""

from datetime import date
from typing import Literal

from app.schemas.common import APIModel, Money


class DataStatusResponse(APIModel):
    has_data: bool
    currencies: list[str]
    default_currency: str | None
    data_start: date | None
    data_end: date | None
    has_sample_data: bool
    record_count: int


class PeriodTotalResponse(APIModel):
    start: date
    end: date
    total_cost: Money
    days_in_period: int
    days_with_data: int


class CostSummaryResponse(APIModel):
    currency: str
    as_of: date | None
    current: PeriodTotalResponse
    previous: PeriodTotalResponse
    change_abs: Money | None
    change_pct: float | None
    daily_average: Money | None
    missing_days: list[date]


class SeriesPointResponse(APIModel):
    period_start: date
    period_end: date
    cost: Money | None
    days_in_period: int
    days_with_data: int
    is_partial: bool


class TimeseriesResponse(APIModel):
    currency: str
    granularity: Literal["day", "week", "month"]
    start: date
    end: date
    points: list[SeriesPointResponse]


class BreakdownItemResponse(APIModel):
    key: str | None
    label: str
    cost: Money
    share_pct: float | None
    previous_cost: Money
    change_abs: Money
    change_pct: float | None


class BreakdownResponse(APIModel):
    currency: str
    dimension: str
    start: date
    end: date
    previous_start: date
    previous_end: date
    total_cost: Money
    items: list[BreakdownItemResponse]
    other_cost: Money
    other_count: int


class ForecastResponse(APIModel):
    currency: str
    month_start: date
    month_end: date
    as_of: date | None
    actual_to_date: Money
    days_elapsed: int
    days_remaining: int
    days_in_month: int
    missing_days_to_date: int
    trailing_daily_median: Money | None
    trailing_days_used: int
    forecast_total: Money | None
    previous_month_total: Money | None
    previous_month_complete: bool
    status: Literal["ok", "insufficient_data", "complete", "no_data"]
    message: str
    assumptions: list[str]
