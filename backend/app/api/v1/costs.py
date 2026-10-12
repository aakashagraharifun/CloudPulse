"""Cost analytics endpoints."""

from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.session import get_db
from app.schemas.costs import (
    BreakdownResponse,
    CostSummaryResponse,
    DataStatusResponse,
    ForecastResponse,
    TimeseriesResponse,
)
from app.services.analytics import service as analytics
from app.services.analytics.service import CostFilters, Dimension, Granularity

router = APIRouter(prefix="/costs", tags=["costs"])

CURRENCY_QUERY = Query(
    None,
    pattern="^[A-Za-z]{3}$",
    description="ISO currency code. Required when the data contains several currencies.",
)


def cost_filters(
    provider: str | None = Query(None, max_length=32),
    account_id: str | None = Query(None, max_length=128),
    service: str | None = Query(None, max_length=255),
    region: str | None = Query(None, max_length=64),
    resource_id: str | None = Query(None, max_length=512),
    usage_type: str | None = Query(None, max_length=255),
    model: str | None = Query(None, max_length=128, description="AI/LLM model, e.g. gpt-4o."),
    project: str | None = Query(None, max_length=128),
    environment: str | None = Query(None, max_length=128),
    category: Literal["cloud", "ai", "saas", "other"] | None = Query(
        None, description="Provider category: cloud, ai (LLM APIs), saas or other."
    ),
) -> CostFilters:
    """Exact-match filters; pass "(unassigned)" to select records without a value."""
    return CostFilters(
        provider=provider,
        account_id=account_id,
        service=service,
        region=region,
        resource_id=resource_id,
        usage_type=usage_type,
        model=model,
        project=project,
        environment=environment,
        category=category,
    )


def _currency(db: Session, currency: str | None) -> str:
    resolved = analytics.resolve_currency(db, currency)
    if resolved is None:
        raise AppError(
            "No billing data has been imported yet.",
            code="no_data",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return resolved


def _range(
    db: Session, currency: str, start: date | None, end: date | None, default_days: int = 30
) -> tuple[date, date]:
    """Fill in a missing bound. Defaults end at the latest day with data."""
    if end is None:
        if start is not None:
            end = start + timedelta(days=default_days - 1)
        else:
            end = analytics.latest_data_date(db, currency) or datetime.now(UTC).date()
    if start is None:
        start = end - timedelta(days=default_days - 1)
    analytics.validate_range(start, end)
    return start, end


@router.get("/data-status", response_model=DataStatusResponse, summary="What data is loaded")
def data_status(db: Session = Depends(get_db)) -> DataStatusResponse:
    return DataStatusResponse.model_validate(analytics.get_data_status(db))


@router.get(
    "/summary",
    response_model=CostSummaryResponse,
    summary="Total cost for a period compared with the preceding period of equal length",
)
def summary(
    currency: str | None = CURRENCY_QUERY,
    start: date | None = Query(None, description="Inclusive. Default: 30 days before `end`."),
    end: date | None = Query(None, description="Inclusive. Default: latest day with data."),
    filters: CostFilters = Depends(cost_filters),
    db: Session = Depends(get_db),
) -> CostSummaryResponse:
    resolved = _currency(db, currency)
    start, end = _range(db, resolved, start, end)
    return CostSummaryResponse.model_validate(
        analytics.get_summary(db, resolved, start, end, filters)
    )


@router.get(
    "/timeseries",
    response_model=TimeseriesResponse,
    summary="Cost per day, ISO week or month. Periods without any data have cost = null.",
)
def timeseries(
    currency: str | None = CURRENCY_QUERY,
    granularity: Granularity = Granularity.DAY,
    start: date | None = None,
    end: date | None = None,
    filters: CostFilters = Depends(cost_filters),
    db: Session = Depends(get_db),
) -> TimeseriesResponse:
    resolved = _currency(db, currency)
    default_days = {Granularity.DAY: 30, Granularity.WEEK: 84, Granularity.MONTH: 365}
    start, end = _range(db, resolved, start, end, default_days[granularity])
    points = analytics.get_timeseries(db, resolved, start, end, granularity, filters)
    return TimeseriesResponse.model_validate(
        {
            "currency": resolved,
            "granularity": granularity.value,
            "start": start,
            "end": end,
            "points": points,
        }
    )


@router.get(
    "/breakdown",
    response_model=BreakdownResponse,
    summary="Cost grouped by a dimension, with change versus the previous period",
)
def breakdown(
    dimension: Dimension,
    currency: str | None = CURRENCY_QUERY,
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(10, ge=1, le=100),
    filters: CostFilters = Depends(cost_filters),
    db: Session = Depends(get_db),
) -> BreakdownResponse:
    resolved = _currency(db, currency)
    start, end = _range(db, resolved, start, end)
    return BreakdownResponse.model_validate(
        analytics.get_breakdown(db, resolved, dimension, start, end, filters, limit)
    )


@router.get(
    "/forecast",
    response_model=ForecastResponse,
    summary="Month-end forecast for the month containing the latest data",
)
def forecast(
    currency: str | None = CURRENCY_QUERY,
    filters: CostFilters = Depends(cost_filters),
    db: Session = Depends(get_db),
) -> ForecastResponse:
    resolved = _currency(db, currency)
    return ForecastResponse.model_validate(analytics.get_forecast(db, resolved, filters))
