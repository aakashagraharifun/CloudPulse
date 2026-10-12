"""Cost aggregation, missing-data handling, currencies and forecasting."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.services.analytics import service as analytics
from app.services.analytics.service import CostFilters, Dimension, Granularity
from tests.factories import add_cost, add_daily_series, make_import

NO_FILTERS = CostFilters()


def test_summary_compares_with_previous_period_and_reports_missing_days(db: Session) -> None:
    imp = make_import(db)
    add_daily_series(db, imp, date(2026, 9, 1), ["10", "10", "10", "10"])  # previous period
    add_daily_series(db, imp, date(2026, 9, 5), ["15", None, "15", "15.5"])  # current
    db.commit()

    summary = analytics.get_summary(db, "USD", date(2026, 9, 5), date(2026, 9, 8), NO_FILTERS)
    assert summary.current.total_cost == Decimal("45.5")
    assert summary.current.days_with_data == 3
    assert summary.missing_days == [date(2026, 9, 6)]
    assert summary.previous.total_cost == Decimal("40")
    assert summary.change_abs == Decimal("5.5")
    assert summary.change_pct == 13.75
    # Average over days that have data, not over calendar days.
    assert summary.daily_average == Decimal("45.5") / 3


def test_summary_change_is_null_without_previous_data(db: Session) -> None:
    imp = make_import(db)
    add_cost(db, imp, date(2026, 9, 5), "5")
    db.commit()
    summary = analytics.get_summary(db, "USD", date(2026, 9, 5), date(2026, 9, 5), NO_FILTERS)
    assert summary.change_abs is None and summary.change_pct is None


def test_currencies_are_never_mixed(db: Session) -> None:
    imp = make_import(db)
    add_cost(db, imp, date(2026, 9, 1), "100", currency="USD")
    add_cost(db, imp, date(2026, 9, 1), "70", currency="EUR")
    db.commit()
    assert analytics.total_cost(db, "USD", date(2026, 9, 1), date(2026, 9, 1), NO_FILTERS) == 100
    assert analytics.total_cost(db, "EUR", date(2026, 9, 1), date(2026, 9, 1), NO_FILTERS) == 70
    with pytest.raises(AppError) as exc:
        analytics.resolve_currency(db, None)
    assert exc.value.code == "currency_required"
    assert analytics.resolve_currency(db, "eur") == "EUR"


def test_daily_series_distinguishes_missing_data_from_zero(db: Session) -> None:
    imp = make_import(db)
    add_cost(db, imp, date(2026, 9, 1), "5", service="EC2")
    add_cost(db, imp, date(2026, 9, 2), "7", service="S3")  # covered, but no EC2 cost
    db.commit()  # 2026-09-03 has no data at all

    points = analytics.get_timeseries(
        db, "USD", date(2026, 9, 1), date(2026, 9, 3), Granularity.DAY, CostFilters(service="EC2")
    )
    assert [p.cost for p in points] == [Decimal("5"), Decimal("0"), None]
    assert [p.is_partial for p in points] == [False, False, True]


def test_weekly_and_monthly_buckets_flag_partial_periods(db: Session) -> None:
    imp = make_import(db)
    # Wed 2026-09-30 .. Sun 2026-10-04, then Mon 2026-10-05
    add_daily_series(db, imp, date(2026, 9, 30), ["1", "2", "3", "4", "5", "6"])
    db.commit()

    weeks = analytics.get_timeseries(
        db, "USD", date(2026, 9, 30), date(2026, 10, 5), Granularity.WEEK, NO_FILTERS
    )
    assert [(w.period_start, w.cost, w.is_partial) for w in weeks] == [
        (date(2026, 9, 28), Decimal("15"), True),  # range starts mid-week
        (date(2026, 10, 5), Decimal("6"), True),
    ]
    months = analytics.get_timeseries(
        db, "USD", date(2026, 9, 30), date(2026, 10, 5), Granularity.MONTH, NO_FILTERS
    )
    assert [(m.period_start, m.cost, m.days_with_data) for m in months] == [
        (date(2026, 9, 1), Decimal("1"), 1),
        (date(2026, 10, 1), Decimal("20"), 5),
    ]


def test_breakdown_ranks_groups_unassigned_and_rolls_up_other(db: Session) -> None:
    imp = make_import(db)
    for service, current, previous in [("EC2", "50", "40"), ("S3", "30", "0"), ("RDS", "20", "25")]:
        add_cost(db, imp, date(2026, 9, 2), current, service=service, project="web")
        if previous != "0":
            add_cost(db, imp, date(2026, 9, 1), previous, service=service)
    add_cost(db, imp, date(2026, 9, 2), "5", service="Lambda")
    db.commit()

    result = analytics.get_breakdown(
        db, "USD", Dimension.SERVICE, date(2026, 9, 2), date(2026, 9, 2), NO_FILTERS, limit=3
    )
    assert [i.label for i in result.items] == ["EC2", "S3", "RDS"]
    assert result.total_cost == Decimal("105")
    assert (result.other_cost, result.other_count) == (Decimal("5"), 1)
    ec2, s3, rds = result.items
    assert (ec2.change_abs, ec2.change_pct) == (Decimal("10"), 25.0)
    assert s3.change_pct is None  # no previous spend: percentage undefined
    assert rds.change_abs == Decimal("-5")

    projects = analytics.get_breakdown(
        db, "USD", Dimension.PROJECT, date(2026, 9, 2), date(2026, 9, 2), NO_FILTERS, limit=10
    )
    assert {i.label: i.cost for i in projects.items} == {
        "web": Decimal("100"),
        analytics.UNASSIGNED: Decimal("5"),
    }
    unassigned_only = analytics.total_cost(
        db, "USD", date(2026, 9, 2), date(2026, 9, 2), CostFilters(project=analytics.UNASSIGNED)
    )
    assert unassigned_only == Decimal("5")


def test_forecast_projects_trailing_average(db: Session) -> None:
    imp = make_import(db)
    add_daily_series(db, imp, date(2026, 9, 1), ["10"] * 10)  # Sep 1..10
    db.commit()
    forecast = analytics.get_forecast(db, "USD", NO_FILTERS)
    assert forecast.status == "ok"
    assert forecast.as_of == date(2026, 9, 10)
    assert forecast.actual_to_date == Decimal("100")
    assert forecast.days_remaining == 20
    assert forecast.trailing_days_used == 7
    assert forecast.forecast_total == Decimal("300")


def test_forecast_median_ignores_a_one_off_spike(db: Session) -> None:
    imp = make_import(db)
    add_daily_series(db, imp, date(2026, 9, 1), ["10"] * 8 + ["500", "10"])  # spike on Sep 9
    db.commit()
    forecast = analytics.get_forecast(db, "USD", NO_FILTERS)
    assert forecast.trailing_daily_median == Decimal("10")
    assert forecast.forecast_total == Decimal("590") + 20 * Decimal("10")


def test_forecast_needs_enough_recent_data(db: Session) -> None:
    imp = make_import(db)
    add_daily_series(db, imp, date(2026, 9, 9), ["10", "10"])
    db.commit()
    forecast = analytics.get_forecast(db, "USD", NO_FILTERS)
    assert forecast.status == "insufficient_data"
    assert forecast.forecast_total is None


def test_forecast_reports_missing_days_and_complete_month(db: Session) -> None:
    imp = make_import(db)
    add_daily_series(db, imp, date(2026, 9, 25), ["10", None, "10", "10", "10", "10"])  # to 30th
    db.commit()
    forecast = analytics.get_forecast(db, "USD", NO_FILTERS)
    assert forecast.status == "complete"
    assert forecast.forecast_total == forecast.actual_to_date == Decimal("50")
    assert forecast.missing_days_to_date == 25  # Sep 1-24 and Sep 26


def test_cost_endpoints_return_decimal_strings(client: TestClient, db: Session) -> None:
    imp = make_import(db, source="sample")
    add_daily_series(db, imp, date(2026, 9, 1), ["10.125", "0.00005"])
    db.commit()

    status_body = client.get("/api/v1/costs/data-status").json()
    assert status_body["has_sample_data"] is True
    assert status_body["default_currency"] == "USD"

    body = client.get("/api/v1/costs/summary?start=2026-09-01&end=2026-09-02").json()
    assert body["current"]["total_cost"] == "10.1250"
    series = client.get("/api/v1/costs/timeseries?start=2026-09-01&end=2026-09-02").json()
    assert [p["cost"] for p in series["points"]] == ["10.1250", "0.0000"]
    assert client.get("/api/v1/costs/breakdown?dimension=service").status_code == 200
    assert client.get("/api/v1/costs/forecast").json()["status"] == "insufficient_data"


def test_cost_endpoints_without_data_and_bad_input(client: TestClient) -> None:
    response = client.get("/api/v1/costs/summary")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "no_data"
    assert client.get("/api/v1/costs/summary?currency=US").status_code == 422
    assert client.get("/api/v1/costs/breakdown?dimension=colour").status_code == 422
    bad_range = client.get("/api/v1/costs/summary?currency=USD&start=2026-09-05&end=2026-09-01")
    assert bad_range.json()["error"]["code"] == "invalid_date_range"


def test_allocation_rule_api_reattributes_records(client: TestClient, db: Session) -> None:
    imp = make_import(db)
    add_cost(db, imp, date(2026, 9, 1), "3", service="CloudWatch")
    db.commit()
    created = client.post(
        "/api/v1/allocation-rules",
        json={
            "name": "Monitoring is platform",
            "match_field": "service",
            "match_operator": "equals",
            "match_value": "cloudwatch",
            "project": "platform",
        },
    )
    assert created.status_code == 201, created.json()
    assert created.json()["records_updated"] == 1
    rule_id = created.json()["rule"]["id"]
    breakdown = client.get(
        "/api/v1/costs/breakdown?dimension=project&start=2026-09-01&end=2026-09-01"
    ).json()
    assert breakdown["items"][0]["label"] == "platform"

    invalid = client.post(
        "/api/v1/allocation-rules",
        json={
            "name": "x",
            "match_field": "service",
            "match_operator": "equals",
            "match_value": "y",
        },
    )
    assert invalid.status_code == 422
    deleted = client.delete(f"/api/v1/allocation-rules/{rule_id}")
    assert deleted.json() == {"rule": None, "records_updated": 1}


def test_category_and_model_dimensions(client: TestClient, db: Session) -> None:
    imp = make_import(db)
    day = date(2026, 9, 2)
    add_cost(db, imp, day, "60", provider="aws", service="EC2")
    add_cost(db, imp, day, "10", provider="azure", service="Virtual Machines")
    add_cost(db, imp, day, "20", provider="openai", service="OpenAI API", model="gpt-4o")
    add_cost(db, imp, day, "8", provider="anthropic", service="Claude", model="claude-sonnet-4-5")
    add_cost(db, imp, day, "2", provider="acme-cdn", service="CDN")
    db.commit()

    categories = analytics.get_breakdown(
        db, "USD", Dimension.CATEGORY, day, day, NO_FILTERS, limit=10
    )
    assert [(i.key, i.label, i.cost) for i in categories.items] == [
        ("cloud", "Cloud infrastructure", Decimal("70")),
        ("ai", "AI & LLM APIs", Decimal("28")),
        ("other", "Other", Decimal("2")),
    ]
    models = analytics.get_breakdown(
        db, "USD", Dimension.MODEL, day, day, CostFilters(category="ai"), limit=10
    )
    assert {i.key: i.cost for i in models.items} == {
        "gpt-4o": Decimal("20"),
        "claude-sonnet-4-5": Decimal("8"),
    }

    params = {"start": "2026-09-02", "end": "2026-09-02"}
    ai_only = client.get("/api/v1/costs/summary", params={**params, "category": "ai"}).json()
    assert ai_only["current"]["total_cost"] == "28.0000"
    one_model = client.get(
        "/api/v1/costs/breakdown",
        params={**params, "dimension": "provider", "model": "gpt-4o"},
    ).json()
    assert [i["key"] for i in one_model["items"]] == ["openai"]
    bad = client.get("/api/v1/costs/summary", params={**params, "category": "llm"})
    assert bad.status_code == 422
