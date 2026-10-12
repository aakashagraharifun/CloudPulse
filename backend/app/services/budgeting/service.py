"""Budget utilization, projection and threshold alerts.

* The budget period is the calendar month / quarter / year that contains the
  latest day with billing data in the budget's currency ("as of").
* Utilization = actual spend in the period up to "as of" / budget amount.
* Projection uses the same trailing-median method as the cost forecast.
* Alert policy: each threshold alerts once per budget period (enforced by a
  unique constraint). With `renotify_hours` set, a still-exceeded threshold is
  re-sent after that many hours. When several thresholds are crossed at once,
  a single notification names the highest one.
"""

import calendar
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Budget, BudgetAlert
from app.services.analytics.service import (
    latest_data_date,
    total_cost,
    trailing_daily_median,
)
from app.services.anomaly_detection.service import scope_filters, scope_label
from app.services.notifications.service import Notification, channels_for_budgets, deliver

logger = logging.getLogger(__name__)
ZERO = Decimal("0")


def period_bounds(period: str, day: date) -> tuple[date, date]:
    if period == "monthly":
        return day.replace(day=1), day.replace(day=calendar.monthrange(day.year, day.month)[1])
    if period == "quarterly":
        first_month = 3 * ((day.month - 1) // 3) + 1
        last_month = first_month + 2
        return (
            date(day.year, first_month, 1),
            date(day.year, last_month, calendar.monthrange(day.year, last_month)[1]),
        )
    if period == "yearly":
        return date(day.year, 1, 1), date(day.year, 12, 31)
    raise ValueError(f"Unknown budget period {period!r}")


def _pct(part: Decimal, whole: Decimal) -> Decimal:
    return (part / whole * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


@dataclass
class BudgetStatus:
    budget: Budget
    as_of: date | None
    period_start: date | None
    period_end: date | None
    actual: Decimal
    utilization_pct: Decimal | None
    projected_total: Decimal | None
    projected_utilization_pct: Decimal | None
    days_remaining: int | None
    state: str  # no_data | ok | warning | over_budget
    message: str
    thresholds_crossed: list[int] = field(default_factory=list)


def budget_status(db: Session, budget: Budget) -> BudgetStatus:
    as_of = latest_data_date(db, budget.currency)
    if as_of is None:
        return BudgetStatus(
            budget, None, None, None, ZERO, None, None, None, None, "no_data",
            f"No billing data in {budget.currency} yet.",
        )  # fmt: skip

    period_start, period_end = period_bounds(budget.period, as_of)
    filters = scope_filters(budget.scope_type, budget.scope_value)
    actual = total_cost(db, budget.currency, period_start, as_of, filters)
    utilization = _pct(actual, budget.amount)
    days_remaining = (period_end - as_of).days
    if days_remaining == 0:
        projected: Decimal | None = actual  # the period is complete
    else:
        median, _ = trailing_daily_median(db, budget.currency, filters, as_of)
        projected = actual + median * days_remaining if median is not None else None
    crossed = sorted(t for t in budget.thresholds if utilization >= t)

    if actual >= budget.amount:
        state, message = "over_budget", "Actual spend has exceeded the budget."
    elif projected is not None and projected > budget.amount:
        state, message = "warning", "Spend is projected to exceed the budget by period end."
    elif crossed:
        state, message = "warning", f"Spend has passed the {crossed[-1]}% threshold."
    else:
        state, message = "ok", "Spend is within budget."
    if projected is None:
        message += " Not enough recent data for a projection."

    return BudgetStatus(
        budget=budget,
        as_of=as_of,
        period_start=period_start,
        period_end=period_end,
        actual=actual,
        utilization_pct=utilization,
        projected_total=projected,
        projected_utilization_pct=_pct(projected, budget.amount) if projected is not None else None,
        days_remaining=days_remaining,
        state=state,
        message=message,
        thresholds_crossed=crossed,
    )


def _notification(status: BudgetStatus, threshold: int, crossed_now: list[int], key: str):
    budget = status.budget
    assert status.period_start is not None and status.as_of is not None
    scope = scope_label(budget.scope_type, budget.scope_value)
    subject = (
        f"[CloudPulse] Budget '{budget.name}' reached {status.utilization_pct}% "
        f"(threshold {threshold}%)"
    )
    body = (
        f"Budget: {budget.name} ({scope})\n"
        f"Period: {status.period_start.isoformat()} to {status.period_end}\n"
        f"Actual spend to {status.as_of.isoformat()}: {status.actual:.2f} {budget.currency}\n"
        f"Budget amount: {budget.amount:.2f} {budget.currency}\n"
        f"Utilization: {status.utilization_pct}%\n"
        f"Thresholds crossed in this evaluation: {', '.join(f'{t}%' for t in crossed_now)}\n"
        + (
            f"Projected period total: {status.projected_total:.2f} {budget.currency}\n"
            if status.projected_total is not None
            else ""
        )
    )
    return Notification(
        event_type="budget_threshold",
        event_key=key,
        subject=subject,
        body=body,
        data={
            "budget_id": budget.id,
            "budget_name": budget.name,
            "currency": budget.currency,
            "period_start": status.period_start.isoformat(),
            "threshold_pct": threshold,
            "utilization_pct": str(status.utilization_pct),
            "actual": str(status.actual),
            "amount": str(budget.amount),
            "as_of": status.as_of.isoformat(),
        },
    )


def evaluate_budgets(db: Session, now: datetime | None = None) -> int:
    """Record new threshold crossings and notify. Returns the number of notifications queued."""
    now = now or datetime.now(UTC)
    sent = 0
    budgets = db.scalars(select(Budget).where(Budget.enabled.is_(True)).order_by(Budget.id)).all()
    for budget in budgets:
        try:
            sent += _evaluate_budget(db, budget, now)
        except Exception:
            db.rollback()
            logger.exception("Budget %s evaluation failed", budget.id)
    return sent


def _evaluate_budget(db: Session, budget: Budget, now: datetime) -> int:
    status = budget_status(db, budget)
    if not status.thresholds_crossed or status.period_start is None:
        return 0
    assert status.period_end is not None and status.as_of is not None
    assert status.utilization_pct is not None

    existing = {
        alert.threshold_pct: alert
        for alert in db.scalars(
            select(BudgetAlert).where(
                BudgetAlert.budget_id == budget.id,
                BudgetAlert.period_start == status.period_start,
            )
        ).all()
    }
    new_alerts: list[BudgetAlert] = []
    for threshold in status.thresholds_crossed:
        if threshold not in existing:
            alert = BudgetAlert(
                budget_id=budget.id,
                period_start=status.period_start,
                period_end=status.period_end,
                threshold_pct=threshold,
                actual_amount=status.actual,
                budget_amount=budget.amount,
                utilization_pct=status.utilization_pct,
                data_as_of=status.as_of,
            )
            db.add(alert)
            new_alerts.append(alert)
    db.commit()

    period_key = f"budget:{budget.id}:{status.period_start.isoformat()}"
    if new_alerts:
        highest = max(new_alerts, key=lambda a: a.threshold_pct)
        notification = _notification(
            status,
            highest.threshold_pct,
            [a.threshold_pct for a in new_alerts],
            f"{period_key}:{highest.threshold_pct}",
        )
        deliver(db, notification, channels_for_budgets(db))
        for alert in new_alerts:
            alert.last_notified_at = now
            alert.notification_count += 1
        db.commit()
        return 1

    if budget.renotify_hours:
        highest = existing[max(status.thresholds_crossed)]
        due = highest.last_notified_at is None or now - highest.last_notified_at >= timedelta(
            hours=budget.renotify_hours
        )
        if due:
            notification = _notification(
                status,
                highest.threshold_pct,
                [highest.threshold_pct],
                f"{period_key}:{highest.threshold_pct}:repeat:{highest.notification_count}",
            )
            deliver(db, notification, channels_for_budgets(db))
            highest.last_notified_at = now
            highest.notification_count += 1
            db.commit()
            return 1
    return 0
