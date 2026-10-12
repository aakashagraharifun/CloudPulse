"""Budgets, threshold alerts and notification delivery (PostgreSQL + local HTTP server)."""

import json
import threading
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Budget, BudgetAlert, NotificationChannel, NotificationDelivery
from app.services.budgeting.service import budget_status, evaluate_budgets, period_bounds
from app.services.notifications import service as notifications
from app.services.pipeline import run_post_import_evaluation
from tests.factories import add_daily_series, make_import


class _Receiver(BaseHTTPRequestHandler):
    received: list[dict] = []
    status_code = 200

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", 0))
        type(self).received.append(json.loads(self.rfile.read(length)))
        self.send_response(type(self).status_code)
        self.end_headers()

    def log_message(self, *args) -> None:  # keep test output quiet
        pass


@pytest.fixture()
def webhook() -> Iterator[type[_Receiver]]:
    _Receiver.received = []
    _Receiver.status_code = 200
    server = HTTPServer(("127.0.0.1", 0), _Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _Receiver.url = f"http://127.0.0.1:{server.server_port}/hook"  # type: ignore[attr-defined]
    yield _Receiver
    server.shutdown()


def _channel(db: Session, url: str, **kwargs) -> NotificationChannel:
    channel = NotificationChannel(name="hook", type="webhook", target=url, **kwargs)
    db.add(channel)
    db.commit()
    return channel


def _september_spend(db: Session, values: list[str]) -> None:
    imp = make_import(db)
    add_daily_series(db, imp, date(2026, 9, 1), values)
    db.commit()


@pytest.mark.parametrize(
    ("period", "day", "expected"),
    [
        ("monthly", date(2026, 2, 14), (date(2026, 2, 1), date(2026, 2, 28))),
        ("monthly", date(2028, 2, 14), (date(2028, 2, 1), date(2028, 2, 29))),
        ("quarterly", date(2026, 11, 3), (date(2026, 10, 1), date(2026, 12, 31))),
        ("yearly", date(2026, 6, 30), (date(2026, 1, 1), date(2026, 12, 31))),
    ],
)
def test_period_bounds(period: str, day: date, expected: tuple[date, date]) -> None:
    assert period_bounds(period, day) == expected


def test_budget_status_utilization_and_projection(db: Session) -> None:
    _september_spend(db, ["10"] * 10)  # Sep 1-10: 100 spent
    budget = Budget(name="Total", amount=Decimal(250), currency="USD", thresholds=[50, 80, 100])
    db.add(budget)
    db.commit()
    status = budget_status(db, budget)
    assert status.as_of == date(2026, 9, 10)
    assert status.actual == Decimal(100)
    assert status.utilization_pct == Decimal("40.00")
    assert status.projected_total == Decimal(300)  # 100 + 20 days x median 10
    assert status.state == "warning"  # projected to exceed
    assert status.thresholds_crossed == []


def test_scoped_budget_only_counts_matching_costs(db: Session) -> None:
    imp = make_import(db)
    add_daily_series(db, imp, date(2026, 9, 1), ["10"] * 5, service="EC2")
    add_daily_series(db, imp, date(2026, 9, 1), ["90"] * 5, service="S3")
    budget = Budget(
        name="EC2", amount=Decimal(100), currency="USD", scope_type="service", scope_value="EC2"
    )
    db.add(budget)
    db.commit()
    assert budget_status(db, budget).actual == Decimal(50)


def test_threshold_alerts_once_per_period_and_single_notification(
    db: Session, webhook: type[_Receiver]
) -> None:
    _channel(db, webhook.url)
    _september_spend(db, ["30"] * 10)  # 300 of 250 -> 120%
    db.add(Budget(name="Total", amount=Decimal(250), currency="USD", thresholds=[50, 80, 100]))
    db.commit()

    assert evaluate_budgets(db) == 1
    alerts = db.scalars(select(BudgetAlert).order_by(BudgetAlert.threshold_pct)).all()
    assert [a.threshold_pct for a in alerts] == [50, 80, 100]
    assert len(webhook.received) == 1  # one message names the highest threshold
    payload = webhook.received[0]
    assert payload["event"] == "budget_threshold"
    assert payload["data"]["threshold_pct"] == 100
    assert "120.00%" in payload["subject"]

    assert evaluate_budgets(db) == 0  # same thresholds, same period: no repeat
    assert len(webhook.received) == 1
    assert db.scalar(select(func.count()).select_from(NotificationDelivery)) == 1


def test_renotify_policy_repeats_after_interval(db: Session, webhook: type[_Receiver]) -> None:
    _channel(db, webhook.url)
    _september_spend(db, ["30"] * 10)
    db.add(
        Budget(
            name="Total", amount=Decimal(250), currency="USD", thresholds=[100], renotify_hours=6
        )
    )
    db.commit()
    now = datetime(2026, 10, 1, 12, tzinfo=UTC)
    assert evaluate_budgets(db, now=now) == 1
    assert evaluate_budgets(db, now=now + timedelta(hours=5)) == 0
    assert evaluate_budgets(db, now=now + timedelta(hours=6)) == 1
    assert len(webhook.received) == 2


def test_failed_delivery_is_recorded_and_does_not_raise(
    db: Session, webhook: type[_Receiver]
) -> None:
    webhook.status_code = 500
    _channel(db, webhook.url)
    _september_spend(db, ["30"] * 10)
    db.add(Budget(name="Total", amount=Decimal(250), currency="USD", thresholds=[100]))
    db.commit()

    evaluate_budgets(db)
    delivery = db.scalars(select(NotificationDelivery)).one()
    assert delivery.status == "failed"
    assert delivery.attempts == 1
    assert "HTTP 500" in (delivery.last_error or "")

    webhook.status_code = 200
    assert notifications.retry_failed(db) == 1
    db.refresh(delivery)
    assert (delivery.status, delivery.attempts) == ("sent", 2)


def test_unreachable_channel_does_not_break_the_pipeline(db: Session) -> None:
    _channel(db, "http://127.0.0.1:9/unreachable", min_severity="low")
    imp = make_import(db)
    add_daily_series(db, imp, date(2026, 8, 1), ["100"] * 40 + ["900"])
    db.add(Budget(name="Total", amount=Decimal(100), currency="USD", thresholds=[100]))
    db.commit()

    run_post_import_evaluation(db)  # must not raise

    deliveries = db.scalars(select(NotificationDelivery)).all()
    assert {d.event_type for d in deliveries} == {"incident_opened", "budget_threshold"}
    assert all(d.status == "failed" for d in deliveries)


def test_incident_notifications_respect_min_severity(db: Session, webhook: type[_Receiver]) -> None:
    _channel(db, webhook.url, min_severity="critical", notify_budget_alerts=False)
    imp = make_import(db)
    add_daily_series(db, imp, date(2026, 8, 1), ["100"] * 40 + ["400"])  # medium/high, not critical
    db.commit()
    run_post_import_evaluation(db)
    assert webhook.received == []


def test_budget_and_channel_api(client: TestClient, db: Session, webhook: type[_Receiver]) -> None:
    _september_spend(db, ["10"] * 10)
    created = client.post(
        "/api/v1/budgets",
        json={"name": " Monthly ", "amount": "120.50", "currency": "usd", "thresholds": [80, 50]},
    )
    assert created.status_code == 201, created.json()
    body = created.json()
    assert body["budget"]["name"] == "Monthly"
    assert body["budget"]["currency"] == "USD"
    assert body["budget"]["thresholds"] == [50, 80]
    assert body["actual"] == "100.0000"
    assert body["utilization_pct"] == "82.99"
    assert body["thresholds_crossed"] == [50, 80]

    bad = client.post(
        "/api/v1/budgets",
        json={"name": "x", "amount": 10, "currency": "USD", "scope_type": "service"},
    )
    assert bad.status_code == 422  # scope_value required for a scoped budget

    channel = client.post(
        "/api/v1/notifications/channels",
        json={"name": "Hook", "type": "webhook", "target": webhook.url + "?token=secret123"},
    ).json()
    assert "secret" not in channel["target_display"]
    test = client.post(f"/api/v1/notifications/channels/{channel['id']}/test").json()
    assert test["status"] == "sent"
    assert webhook.received[-1]["event"] == "test"

    assert client.post("/api/v1/budgets/evaluate").json() == {"notifications_sent": 1}
    alerts = client.get("/api/v1/budgets/alerts").json()
    assert {a["threshold_pct"] for a in alerts["items"]} == {50, 80}
    deliveries = client.get("/api/v1/notifications/deliveries").json()
    assert deliveries["total"] == 2

    invalid = client.post(
        "/api/v1/notifications/channels",
        json={"name": "Mail", "type": "email", "target": "not-an-address"},
    )
    assert invalid.status_code == 422
    assert client.delete(f"/api/v1/budgets/{body['budget']['id']}").status_code == 204
