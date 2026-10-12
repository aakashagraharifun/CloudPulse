"""Cost analytics over normalized billing records.

Rules that keep the numbers honest:
* Every query is scoped to exactly one currency; amounts in different
  currencies are never added together (no conversion rates are available).
* "Coverage" is the set of days on which *any* record exists for the currency.
  A day without coverage is missing data (reported as null), not zero spend.
  A covered day with no records matching a filter is a genuine zero.
* "As of" is the latest usage date with data for the currency, so analysis of
  historical or sample data behaves the same as analysis of live data.
"""

import calendar
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from fastapi import status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import BillingImport, BillingRecord, ImportSource, ImportStatus

UNASSIGNED = "(unassigned)"
ZERO = Decimal("0")


class Dimension(StrEnum):
    PROVIDER = "provider"
    ACCOUNT_ID = "account_id"
    SERVICE = "service"
    REGION = "region"
    RESOURCE_ID = "resource_id"
    USAGE_TYPE = "usage_type"
    PROJECT = "project"
    ENVIRONMENT = "environment"


class Granularity(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


@dataclass(frozen=True)
class CostFilters:
    """Optional exact-match filters. The value "(unassigned)" matches missing values."""

    provider: str | None = None
    account_id: str | None = None
    service: str | None = None
    region: str | None = None
    resource_id: str | None = None
    usage_type: str | None = None
    project: str | None = None
    environment: str | None = None

    def apply(self, statement: Select) -> Select:
        for item in fields(self):
            value = getattr(self, item.name)
            if value is None:
                continue
            column = getattr(BillingRecord, item.name)
            statement = statement.where(
                column.is_(None) if value == UNASSIGNED else column == value
            )
        return statement

    def is_empty(self) -> bool:
        return all(getattr(self, item.name) is None for item in fields(self))


def pct_change(current: Decimal, previous: Decimal) -> float | None:
    """Percentage change; None when the previous value is zero or negative."""
    if previous <= 0:
        return None
    return round(float((current - previous) / previous * 100), 2)


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


# --- data status / currency resolution -------------------------------------


@dataclass
class DataStatus:
    has_data: bool
    currencies: list[str]
    default_currency: str | None
    data_start: date | None
    data_end: date | None
    has_sample_data: bool
    record_count: int


def get_data_status(db: Session) -> DataStatus:
    rows = db.execute(
        select(
            BillingRecord.currency,
            func.count(),
            func.min(BillingRecord.usage_date),
            func.max(BillingRecord.usage_date),
        ).group_by(BillingRecord.currency)
    ).all()
    has_sample = (
        db.scalar(
            select(func.count())
            .select_from(BillingImport)
            .where(
                BillingImport.source == ImportSource.SAMPLE,
                BillingImport.status == ImportStatus.COMPLETED,
            )
        )
        or 0
    ) > 0
    if not rows:
        return DataStatus(False, [], None, None, None, has_sample, 0)
    default = max(rows, key=lambda row: (row[1], row[0]))[0]
    return DataStatus(
        has_data=True,
        currencies=sorted(row[0] for row in rows),
        default_currency=default,
        data_start=min(row[2] for row in rows),
        data_end=max(row[3] for row in rows),
        has_sample_data=has_sample,
        record_count=sum(row[1] for row in rows),
    )


def resolve_currency(db: Session, currency: str | None) -> str | None:
    """Return the currency to analyse, or None when there is no data at all."""
    available = sorted(db.scalars(select(BillingRecord.currency).distinct()).all())
    if currency is not None:
        return currency.upper()
    if not available:
        return None
    if len(available) > 1:
        raise AppError(
            "Billing data contains several currencies ("
            + ", ".join(available)
            + "). Choose one with the `currency` parameter; amounts in different "
            "currencies are never combined.",
            code="currency_required",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"currencies": available},
        )
    return available[0]


def latest_data_date(db: Session, currency: str) -> date | None:
    return db.scalar(
        select(func.max(BillingRecord.usage_date)).where(BillingRecord.currency == currency)
    )


def coverage_days(db: Session, currency: str, start: date, end: date) -> set[date]:
    return set(
        db.scalars(
            select(BillingRecord.usage_date)
            .distinct()
            .where(
                BillingRecord.currency == currency,
                BillingRecord.usage_date >= start,
                BillingRecord.usage_date <= end,
            )
        ).all()
    )


def daily_costs(
    db: Session, currency: str, start: date, end: date, filters: CostFilters
) -> dict[date, Decimal]:
    statement = (
        select(BillingRecord.usage_date, func.sum(BillingRecord.cost))
        .where(
            BillingRecord.currency == currency,
            BillingRecord.usage_date >= start,
            BillingRecord.usage_date <= end,
        )
        .group_by(BillingRecord.usage_date)
    )
    return dict(db.execute(filters.apply(statement)).all())


def total_cost(db: Session, currency: str, start: date, end: date, filters: CostFilters) -> Decimal:
    statement = select(func.coalesce(func.sum(BillingRecord.cost), ZERO)).where(
        BillingRecord.currency == currency,
        BillingRecord.usage_date >= start,
        BillingRecord.usage_date <= end,
    )
    return db.scalar(filters.apply(statement)) or ZERO


def default_range(db: Session, currency: str, days: int = 30) -> tuple[date, date] | None:
    end = latest_data_date(db, currency)
    if end is None:
        return None
    return end - timedelta(days=days - 1), end


def validate_range(start: date, end: date, max_days: int = 3660) -> None:
    if start > end:
        raise AppError("`start` must be on or before `end`.", code="invalid_date_range")
    if (end - start).days + 1 > max_days:
        raise AppError(f"The date range may not exceed {max_days} days.", code="invalid_date_range")


# --- summary -----------------------------------------------------------------


@dataclass
class PeriodTotal:
    start: date
    end: date
    total_cost: Decimal
    days_in_period: int
    days_with_data: int


@dataclass
class CostSummary:
    currency: str
    as_of: date | None
    current: PeriodTotal
    previous: PeriodTotal
    change_abs: Decimal | None
    change_pct: float | None
    daily_average: Decimal | None
    missing_days: list[date]


def _period_total(
    db: Session, currency: str, start: date, end: date, filters: CostFilters
) -> tuple[PeriodTotal, set[date]]:
    covered = coverage_days(db, currency, start, end)
    return (
        PeriodTotal(
            start=start,
            end=end,
            total_cost=total_cost(db, currency, start, end, filters),
            days_in_period=(end - start).days + 1,
            days_with_data=len(covered),
        ),
        covered,
    )


def get_summary(
    db: Session, currency: str, start: date, end: date, filters: CostFilters
) -> CostSummary:
    validate_range(start, end)
    length = (end - start).days + 1
    current, covered = _period_total(db, currency, start, end, filters)
    previous, _ = _period_total(
        db, currency, start - timedelta(days=length), start - timedelta(days=1), filters
    )
    comparable = current.days_with_data > 0 and previous.days_with_data > 0
    return CostSummary(
        currency=currency,
        as_of=latest_data_date(db, currency),
        current=current,
        previous=previous,
        change_abs=current.total_cost - previous.total_cost if comparable else None,
        change_pct=pct_change(current.total_cost, previous.total_cost) if comparable else None,
        daily_average=(
            current.total_cost / current.days_with_data if current.days_with_data else None
        ),
        missing_days=[day for day in days_between(start, end) if day not in covered],
    )


# --- time series -------------------------------------------------------------


@dataclass
class SeriesPoint:
    period_start: date
    period_end: date
    cost: Decimal | None  # None: no billing data at all for any day in the period
    days_in_period: int
    days_with_data: int
    is_partial: bool


def _period_bounds(day: date, granularity: Granularity) -> tuple[date, date]:
    if granularity == Granularity.DAY:
        return day, day
    if granularity == Granularity.WEEK:  # ISO weeks, Monday to Sunday
        monday = day - timedelta(days=day.weekday())
        return monday, monday + timedelta(days=6)
    last = calendar.monthrange(day.year, day.month)[1]
    return day.replace(day=1), day.replace(day=last)


def get_timeseries(
    db: Session,
    currency: str,
    start: date,
    end: date,
    granularity: Granularity,
    filters: CostFilters,
) -> list[SeriesPoint]:
    validate_range(start, end)
    costs = daily_costs(db, currency, start, end, filters)
    covered = coverage_days(db, currency, start, end)

    buckets: dict[tuple[date, date], list[date]] = {}
    for day in days_between(start, end):
        buckets.setdefault(_period_bounds(day, granularity), []).append(day)

    points = []
    for (period_start, period_end), days in buckets.items():
        with_data = [day for day in days if day in covered]
        cost = sum((costs.get(day, ZERO) for day in with_data), ZERO) if with_data else None
        full_length = (period_end - period_start).days + 1
        points.append(
            SeriesPoint(
                period_start=period_start,
                period_end=period_end,
                cost=cost,
                days_in_period=full_length,
                days_with_data=len(with_data),
                # Partial: clipped by the requested range, or some days lack data.
                is_partial=len(days) < full_length or len(with_data) < len(days),
            )
        )
    return points


# --- breakdown ---------------------------------------------------------------


@dataclass
class BreakdownItem:
    key: str | None
    label: str
    cost: Decimal
    share_pct: float | None
    previous_cost: Decimal
    change_abs: Decimal
    change_pct: float | None


@dataclass
class Breakdown:
    currency: str
    dimension: Dimension
    start: date
    end: date
    previous_start: date
    previous_end: date
    total_cost: Decimal
    items: list[BreakdownItem]
    other_cost: Decimal
    other_count: int


def costs_by_dimension(
    db: Session,
    currency: str,
    dimension: Dimension,
    start: date,
    end: date,
    filters: CostFilters,
) -> dict[str | None, Decimal]:
    column = getattr(BillingRecord, dimension.value)
    statement = (
        select(column, func.sum(BillingRecord.cost))
        .where(
            BillingRecord.currency == currency,
            BillingRecord.usage_date >= start,
            BillingRecord.usage_date <= end,
        )
        .group_by(column)
    )
    return dict(db.execute(filters.apply(statement)).all())


def get_breakdown(
    db: Session,
    currency: str,
    dimension: Dimension,
    start: date,
    end: date,
    filters: CostFilters,
    limit: int,
) -> Breakdown:
    validate_range(start, end)
    length = (end - start).days + 1
    previous_start, previous_end = start - timedelta(days=length), start - timedelta(days=1)
    current = costs_by_dimension(db, currency, dimension, start, end, filters)
    previous = costs_by_dimension(db, currency, dimension, previous_start, previous_end, filters)
    total = sum(current.values(), ZERO)

    ranked = sorted(current.items(), key=lambda kv: (-kv[1], kv[0] or ""))
    items = [
        BreakdownItem(
            key=key,
            label=key if key is not None else UNASSIGNED,
            cost=cost,
            share_pct=round(float(cost / total * 100), 2) if total > 0 else None,
            previous_cost=previous.get(key, ZERO),
            change_abs=cost - previous.get(key, ZERO),
            change_pct=pct_change(cost, previous.get(key, ZERO)),
        )
        for key, cost in ranked[:limit]
    ]
    rest = ranked[limit:]
    return Breakdown(
        currency=currency,
        dimension=dimension,
        start=start,
        end=end,
        previous_start=previous_start,
        previous_end=previous_end,
        total_cost=total,
        items=items,
        other_cost=sum((cost for _, cost in rest), ZERO),
        other_count=len(rest),
    )


# --- forecast ----------------------------------------------------------------

FORECAST_TRAILING_DAYS = 7
FORECAST_MIN_DAYS = 3
FORECAST_ASSUMPTIONS = (
    "Remaining days are projected at the median daily cost of the most recent "
    f"{FORECAST_TRAILING_DAYS} days that have billing data (looking back up to 14 days). "
    "The median keeps a one-off spike from inflating the whole month.",
    f"At least {FORECAST_MIN_DAYS} days with data in that window are required.",
    "Days without billing data are not treated as zero spend and are excluded from the median.",
    "The projection is linear: it does not model seasonality, commitments, "
    "credits or planned changes. A sustained recent increase does raise it.",
)


@dataclass
class Forecast:
    currency: str
    month_start: date
    month_end: date
    as_of: date | None
    actual_to_date: Decimal
    days_elapsed: int
    days_remaining: int
    days_in_month: int
    missing_days_to_date: int
    trailing_daily_median: Decimal | None
    trailing_days_used: int
    forecast_total: Decimal | None
    previous_month_total: Decimal | None
    previous_month_complete: bool
    status: str  # "ok" | "insufficient_data" | "complete" | "no_data"
    message: str
    assumptions: Sequence[str] = FORECAST_ASSUMPTIONS


def trailing_daily_median(
    db: Session, currency: str, filters: CostFilters, as_of: date
) -> tuple[Decimal | None, int]:
    """Median daily cost of the latest covered days (see FORECAST_ASSUMPTIONS).

    Returns (None, days_found) when fewer than FORECAST_MIN_DAYS days are available.
    """
    lookback_start = as_of - timedelta(days=13)
    covered_recent = sorted(coverage_days(db, currency, lookback_start, as_of), reverse=True)
    window = covered_recent[:FORECAST_TRAILING_DAYS]
    if len(window) < FORECAST_MIN_DAYS:
        return None, len(window)
    daily = daily_costs(db, currency, lookback_start, as_of, filters)
    return statistics.median(daily.get(day, ZERO) for day in window), len(window)


def get_forecast(
    db: Session, currency: str, filters: CostFilters, as_of: date | None = None
) -> Forecast:
    as_of = as_of or latest_data_date(db, currency)
    if as_of is None:
        today = datetime.now(UTC).date()
        month_start, month_end = _period_bounds(today, Granularity.MONTH)
        return Forecast(
            currency, month_start, month_end, None, ZERO, 0, 0, month_end.day, 0, None, 0,
            None, None, False, "no_data", "No billing data in this currency yet.",
        )  # fmt: skip

    month_start, month_end = _period_bounds(as_of, Granularity.MONTH)
    actual = total_cost(db, currency, month_start, as_of, filters)
    covered_mtd = coverage_days(db, currency, month_start, as_of)
    days_elapsed = (as_of - month_start).days + 1
    days_remaining = (month_end - as_of).days

    median, days_used = trailing_daily_median(db, currency, filters, as_of)

    prev_end = month_start - timedelta(days=1)
    prev_start = prev_end.replace(day=1)
    prev_covered = coverage_days(db, currency, prev_start, prev_end)
    previous_total = (
        total_cost(db, currency, prev_start, prev_end, filters) if prev_covered else None
    )

    if days_remaining == 0:
        status_, message, forecast_total = (
            "complete",
            "The month is complete; the forecast equals actual spend.",
            actual,
        )
    elif median is None:
        status_, message, forecast_total = (
            "insufficient_data",
            f"Only {days_used} day(s) with billing data in the last 14 days; "
            f"at least {FORECAST_MIN_DAYS} are needed for a forecast.",
            None,
        )
    else:
        status_ = "ok"
        forecast_total = actual + median * days_remaining
        message = (
            f"Actual spend to {as_of.isoformat()} plus {days_remaining} remaining day(s) at the "
            f"trailing {days_used}-day median."
        )

    return Forecast(
        currency=currency,
        month_start=month_start,
        month_end=month_end,
        as_of=as_of,
        actual_to_date=actual,
        days_elapsed=days_elapsed,
        days_remaining=days_remaining,
        days_in_month=month_end.day,
        missing_days_to_date=days_elapsed - len(covered_mtd),
        trailing_daily_median=median,
        trailing_days_used=days_used,
        forecast_total=forecast_total,
        previous_month_total=previous_total,
        previous_month_complete=len(prev_covered) == prev_end.day,
        status=status_,
        message=message,
    )
