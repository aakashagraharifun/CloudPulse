"""Evidence-based investigation of an incident.

Everything here is computed from stored billing records with fixed rules; no
language model is involved and no cause is asserted that the data does not
show. Where the data cannot support a conclusion, a limitation is reported.

Method
------
* Incident period: the incident's anomalous days (start..end).
* Baseline period: the `baseline_window_days` days immediately before it.
* For every member of a dimension (e.g. each resource) the change is
  `cost in incident period - (baseline average per day x incident days)`,
  i.e. how much more it cost than it usually does over the same number of days.
* Only days that have billing data count towards averages.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BillingRecord
from app.models.anomaly import AnomalyDetection, Incident
from app.services.analytics.service import (
    UNASSIGNED,
    CostFilters,
    coverage_days,
    daily_costs,
    days_between,
    latest_data_date,
)
from app.services.anomaly_detection.service import (
    DIMENSION_LABELS,
    TOTAL_SCOPE,
    get_settings_row,
    scope_filters,
    scope_label,
)

ZERO = Decimal("0")
TOP_N = 5
DOMINANT_SHARE = 50.0
# Contributors below this share of the increase are listed in the tables but not
# narrated individually, so explanations stay focused on what matters.
MIN_SHARE_TO_NARRATE = 10.0
CHART_PADDING_AFTER = 7
DATA_TRANSFER_HINTS = ("datatransfer", "data-transfer", "bytes", "natgateway", "egress")

DIMENSIONS_FOR_SCOPE = {
    TOTAL_SCOPE: ("service", "resource_id", "region", "usage_type", "project", "account_id"),
    "service": ("resource_id", "region", "usage_type", "project"),
}
DEFAULT_DIMENSIONS = ("service", "resource_id", "region", "usage_type")


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)


def _quantity(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value:,.2f}"


def _money(value: Decimal, currency: str) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN):,} {currency}"


@dataclass
class UsageComparison:
    unit: str | None
    baseline_daily_quantity: Decimal | None
    current_daily_quantity: Decimal | None
    quantity_ratio: float | None
    cost_ratio: float | None
    driver: str  # usage | rate | mixed | mixed_units | new | unknown


@dataclass
class Contributor:
    key: str | None
    label: str
    current_cost: Decimal
    baseline_cost: Decimal
    baseline_daily_avg: Decimal
    current_daily_avg: Decimal
    change: Decimal
    share_of_increase_pct: float | None
    is_new: bool
    usage: UsageComparison | None = None


@dataclass
class DimensionAnalysis:
    dimension: str
    label: str
    contributors: list[Contributor]
    other_change: Decimal
    members_total: int


@dataclass
class Suggestion:
    title: str
    detail: str
    evidence: str


@dataclass
class ChartPoint:
    day: date
    cost: Decimal | None
    expected: Decimal | None
    is_anomaly: bool


@dataclass
class RelatedIncident:
    id: int
    title: str
    status: str
    severity: str
    start_date: date
    end_date: date


@dataclass
class Investigation:
    incident_id: int
    currency: str
    scope_label: str
    current_start: date
    current_end: date
    current_days_with_data: int
    baseline_start: date
    baseline_end: date
    baseline_days_with_data: int
    current_total: Decimal
    baseline_daily_avg: Decimal | None
    expected_total_from_baseline: Decimal | None
    total_change: Decimal | None
    observed_cost: Decimal
    expected_cost: Decimal
    deviation_abs: Decimal
    peak_deviation_pct: Decimal | None
    confidence: str  # high | medium | low
    confidence_statement: str
    summary: list[str]
    explanations: list[str]
    suggestions: list[Suggestion]
    limitations: list[str]
    dimensions: list[DimensionAnalysis] = field(default_factory=list)
    chart: list[ChartPoint] = field(default_factory=list)
    related_incidents: list[RelatedIncident] = field(default_factory=list)


# --- queries -------------------------------------------------------------------


def _grouped(
    db: Session,
    currency: str,
    dimension: str,
    start: date,
    end: date,
    filters: CostFilters,
) -> dict[str | None, Decimal]:
    column = getattr(BillingRecord, dimension)
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


@dataclass(frozen=True)
class _UsageTotals:
    status: str  # ok | no_rows | missing | mixed_units
    unit: str | None = None
    quantity: Decimal = ZERO


def _usage(
    db: Session,
    currency: str,
    dimension: str,
    key: str | None,
    start: date,
    end: date,
    filters: CostFilters,
) -> _UsageTotals:
    """Total usage quantity for one contributor, if it is comparable (one unit, all rows)."""
    column = getattr(BillingRecord, dimension)
    statement = select(
        func.count(),
        func.count(BillingRecord.usage_quantity),
        func.count(func.distinct(BillingRecord.usage_unit)),
        func.max(BillingRecord.usage_unit),
        func.sum(BillingRecord.usage_quantity),
    ).where(
        BillingRecord.currency == currency,
        BillingRecord.usage_date >= start,
        BillingRecord.usage_date <= end,
        column.is_(None) if key is None else column == key,
    )
    rows, with_quantity, units, unit, quantity = db.execute(filters.apply(statement)).one()
    if rows == 0:
        return _UsageTotals("no_rows")
    if with_quantity != rows:
        return _UsageTotals("missing")
    if units > 1:
        return _UsageTotals("mixed_units")
    return _UsageTotals("ok", unit, quantity or ZERO)


def _ratio(current: Decimal, baseline: Decimal) -> float | None:
    if baseline <= 0:
        return None
    return round(float(current / baseline), 2)


def _classify(is_new: bool, quantity_ratio: float | None, cost_ratio: float | None) -> str:
    if is_new:
        return "new"
    if quantity_ratio is None or cost_ratio is None:
        return "unknown"
    if quantity_ratio >= 1.1 and abs(cost_ratio / quantity_ratio - 1) <= 0.15:
        return "usage"
    if 0.9 <= quantity_ratio <= 1.1 and cost_ratio >= 1.1:
        return "rate"
    return "mixed"


# --- main entry ----------------------------------------------------------------


def investigate(db: Session, incident: Incident) -> Investigation:
    settings_row = get_settings_row(db)
    currency = incident.currency
    filters = scope_filters(incident.scope_type, incident.scope_value)
    label = scope_label(incident.scope_type, incident.scope_value)

    current_start, current_end = incident.start_date, incident.end_date
    baseline_end = current_start - timedelta(days=1)
    baseline_start = current_start - timedelta(days=settings_row.baseline_window_days)
    current_days = len(coverage_days(db, currency, current_start, current_end))
    baseline_days = len(coverage_days(db, currency, baseline_start, baseline_end))

    current_total = sum(
        daily_costs(db, currency, current_start, current_end, filters).values(), ZERO
    )
    baseline_total = sum(
        daily_costs(db, currency, baseline_start, baseline_end, filters).values(), ZERO
    )
    baseline_avg = baseline_total / baseline_days if baseline_days else None
    expected_from_baseline = baseline_avg * current_days if baseline_avg is not None else None
    total_change = (
        current_total - expected_from_baseline if expected_from_baseline is not None else None
    )

    limitations: list[str] = []
    if baseline_days == 0:
        limitations.append(
            "There is no billing data in the baseline period, so contributors cannot be "
            "compared with normal spend."
        )
    elif baseline_days < settings_row.baseline_window_days:
        limitations.append(
            f"Only {baseline_days} of {settings_row.baseline_window_days} baseline days have "
            "billing data; baseline averages use those days only."
        )

    dimensions: list[DimensionAnalysis] = []
    if baseline_days and current_days and total_change is not None:
        for dimension in DIMENSIONS_FOR_SCOPE.get(incident.scope_type, DEFAULT_DIMENSIONS):
            dimensions.append(
                _analyse_dimension(
                    db,
                    currency,
                    dimension,
                    filters,
                    (current_start, current_end, current_days),
                    (baseline_start, baseline_end, baseline_days),
                    total_change,
                )
            )

    explanations, suggestions, confidence, statement = _narrate(
        incident, label, dimensions, total_change, limitations
    )
    summary = [
        f"{label} cost {_money(incident.observed_cost, currency)} between "
        f"{current_start.isoformat()} and {current_end.isoformat()}, against an expected "
        f"baseline of {_money(incident.expected_cost, currency)}.",
        f"That is {_money(incident.deviation_abs, currency)} above the baseline"
        + (
            f" (peak day +{incident.peak_deviation_pct}%)."
            if incident.peak_deviation_pct is not None
            else " (new spend; there was no cost in the baseline, so a percentage is undefined)."
        ),
    ]

    return Investigation(
        incident_id=incident.id,
        currency=currency,
        scope_label=label,
        current_start=current_start,
        current_end=current_end,
        current_days_with_data=current_days,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        baseline_days_with_data=baseline_days,
        current_total=current_total,
        baseline_daily_avg=baseline_avg,
        expected_total_from_baseline=expected_from_baseline,
        total_change=total_change,
        observed_cost=incident.observed_cost,
        expected_cost=incident.expected_cost,
        deviation_abs=incident.deviation_abs,
        peak_deviation_pct=incident.peak_deviation_pct,
        confidence=confidence,
        confidence_statement=statement,
        summary=summary,
        explanations=explanations,
        suggestions=suggestions,
        limitations=limitations,
        dimensions=dimensions,
        chart=_chart(db, incident, filters, baseline_start),
        related_incidents=_related(db, incident),
    )


def _analyse_dimension(
    db: Session,
    currency: str,
    dimension: str,
    filters: CostFilters,
    current: tuple[date, date, int],
    baseline: tuple[date, date, int],
    total_change: Decimal,
) -> DimensionAnalysis:
    cur_start, cur_end, cur_days = current
    base_start, base_end, base_days = baseline
    cur = _grouped(db, currency, dimension, cur_start, cur_end, filters)
    base = _grouped(db, currency, dimension, base_start, base_end, filters)

    contributors: list[Contributor] = []
    for key in set(cur) | set(base):
        current_cost = cur.get(key, ZERO)
        baseline_cost = base.get(key, ZERO)
        base_avg = baseline_cost / base_days
        cur_avg = current_cost / cur_days
        change = current_cost - base_avg * cur_days
        contributors.append(
            Contributor(
                key=key,
                label=key if key is not None else UNASSIGNED,
                current_cost=_q(current_cost),
                baseline_cost=_q(baseline_cost),
                baseline_daily_avg=_q(base_avg),
                current_daily_avg=_q(cur_avg),
                change=_q(change),
                share_of_increase_pct=(
                    round(float(change / total_change * 100), 1) if total_change > 0 else None
                ),
                is_new=baseline_cost <= 0 and current_cost > 0,
            )
        )
    contributors.sort(key=lambda c: (-c.change, c.label))
    top = [c for c in contributors if c.change > 0][:TOP_N]

    if dimension in ("resource_id", "usage_type"):
        for contributor in top:
            contributor.usage = _compare_usage(
                db, currency, dimension, contributor, filters, current, baseline
            )

    shown = {id(c) for c in top}
    return DimensionAnalysis(
        dimension=dimension,
        label=DIMENSION_LABELS.get(dimension, dimension),
        contributors=top,
        other_change=_q(sum((c.change for c in contributors if id(c) not in shown), ZERO)),
        members_total=len(contributors),
    )


def _material(contributor: Contributor) -> bool:
    share = contributor.share_of_increase_pct
    return share is not None and share >= MIN_SHARE_TO_NARRATE


def _compare_usage(
    db: Session,
    currency: str,
    dimension: str,
    contributor: Contributor,
    filters: CostFilters,
    current: tuple[date, date, int],
    baseline: tuple[date, date, int],
) -> UsageComparison:
    cur_start, cur_end, cur_days = current
    base_start, base_end, base_days = baseline
    cur = _usage(db, currency, dimension, contributor.key, cur_start, cur_end, filters)
    base = _usage(db, currency, dimension, contributor.key, base_start, base_end, filters)
    cost_ratio = _ratio(contributor.current_daily_avg, contributor.baseline_daily_avg)

    def result(driver: str, unit=None, base_q=None, cur_q=None, ratio=None) -> UsageComparison:
        return UsageComparison(
            unit=unit,
            baseline_daily_quantity=_q(base_q) if base_q is not None else None,
            current_daily_quantity=_q(cur_q) if cur_q is not None else None,
            quantity_ratio=ratio,
            cost_ratio=cost_ratio,
            driver=driver,
        )

    if contributor.is_new:
        unit = cur.unit if cur.status == "ok" else None
        cur_q = cur.quantity / cur_days if cur.status == "ok" else None
        return result("new", unit, None, cur_q)
    if "mixed_units" in (cur.status, base.status) or (
        cur.status == base.status == "ok" and cur.unit != base.unit
    ):
        return result("mixed_units")
    if cur.status != "ok" or base.status != "ok":
        return result("unknown")
    cur_q = cur.quantity / cur_days
    base_q = base.quantity / base_days
    ratio = _ratio(cur_q, base_q)
    return result(_classify(False, ratio, cost_ratio), cur.unit, base_q, cur_q, ratio)


def _narrate(
    incident: Incident,
    label: str,
    dimensions: list[DimensionAnalysis],
    total_change: Decimal | None,
    limitations: list[str],
) -> tuple[list[str], list[Suggestion], str, str]:
    currency = incident.currency
    explanations: list[str] = []
    suggestions: list[Suggestion] = []
    by_dimension = {d.dimension: d for d in dimensions}
    dates = (
        incident.start_date.isoformat()
        if incident.start_date == incident.end_date
        else f"{incident.start_date.isoformat()} to {incident.end_date.isoformat()}"
    )

    if not dimensions or total_change is None or total_change <= 0:
        limitations.append(
            "Compared with the average baseline day, the incident period does not show a net "
            "increase that can be attributed to individual contributors."
        )
        statement = "The cause cannot be determined confidently from the available billing data."
        suggestions.append(
            Suggestion(
                "Review changes around the incident dates",
                f"Compare deployments, configuration changes and traffic for {dates} with the "
                "cost data above.",
                "No individual contributor stands out in the billing data.",
            )
        )
        return explanations, suggestions, "low", statement

    primary = dimensions[0]
    top = primary.contributors[0] if primary.contributors else None
    dominant = (
        top is not None
        and top.share_of_increase_pct is not None
        and top.share_of_increase_pct >= DOMINANT_SHARE
    )
    if top is not None and top.is_new:
        explanations.append(
            f"{primary.label} '{top.label}' had no cost in the baseline period and contributed "
            f"{_money(top.change, currency)} of the {_money(total_change, currency)} increase "
            f"({top.share_of_increase_pct}%), averaging {_money(top.current_daily_avg, currency)} "
            "per day during the incident."
        )
    elif top is not None:
        explanations.append(
            f"{primary.label} '{top.label}' contributed {_money(top.change, currency)} of the "
            f"{_money(total_change, currency)} increase ({top.share_of_increase_pct}%), rising "
            f"from {_money(top.baseline_daily_avg, currency)} to "
            f"{_money(top.current_daily_avg, currency)} per day."
        )

    resources = by_dimension.get("resource_id")
    for contributor in resources.contributors[:3] if resources else []:
        if not _material(contributor):
            continue
        if contributor.key is None:
            explanations.append(
                f"Line items without a resource ID contributed "
                f"{_money(contributor.change, currency)}."
            )
            continue
        if contributor.is_new:
            if contributor is not top:  # the top contributor was already described above
                explanations.append(
                    f"Resource '{contributor.label}' had no cost in the baseline period and cost "
                    f"{_money(contributor.current_cost, currency)} during the incident."
                )
            suggestions.append(
                Suggestion(
                    f"Confirm resource {contributor.label} is expected",
                    "Check who created it, whether it is still needed, and that it is tagged "
                    "with an owner and project.",
                    f"It first incurred cost during the incident ({dates}) with no baseline spend.",
                )
            )
        _describe_usage(contributor, "Resource", currency, explanations, suggestions)

    usage_types = by_dimension.get("usage_type")
    for contributor in usage_types.contributors[:2] if usage_types else []:
        if (
            contributor.key
            and _material(contributor)
            and any(h in contributor.key.lower() for h in DATA_TRANSFER_HINTS)
        ):
            suggestions.append(
                Suggestion(
                    f"Review data transfer for {contributor.label}",
                    "Look at traffic paths: cross-AZ or cross-region transfer, NAT gateway "
                    "processing that could use VPC endpoints, and unexpected egress.",
                    f"Usage type '{contributor.label}' increased by "
                    f"{_money(contributor.change, currency)}; its name indicates data transfer.",
                )
            )
        _describe_usage(contributor, "Usage type", currency, explanations, suggestions)

    regions = by_dimension.get("region")
    for contributor in regions.contributors if regions else []:
        if contributor.is_new and contributor.key is not None and _material(contributor):
            suggestions.append(
                Suggestion(
                    f"Check activity in region {contributor.label}",
                    "Verify deployments, test environments or resources launched in this region.",
                    f"Region {contributor.label} had no spend in the baseline period and cost "
                    f"{_money(contributor.current_cost, currency)} during the incident.",
                )
            )

    projects = by_dimension.get("project")
    if projects:
        unassigned = next((c for c in projects.contributors if c.key is None), None)
        if unassigned and (unassigned.share_of_increase_pct or 0) >= 25:
            suggestions.append(
                Suggestion(
                    "Tag the unallocated resources",
                    "Add project tags or an allocation rule so the owner of this spend is known.",
                    f"{unassigned.share_of_increase_pct}% of the increase has no project.",
                )
            )
        elif projects.contributors and projects.contributors[0].key is not None:
            owner = projects.contributors[0]
            explanations.append(
                f"Project '{owner.label}' accounts for {owner.share_of_increase_pct}% of the "
                "increase."
            )

    if dominant and top is not None:
        confidence = "high" if top.share_of_increase_pct >= 80 else "medium"
        statement = (
            f"The increase is concentrated in {primary.label.lower()} '{top.label}' "
            f"({top.share_of_increase_pct}% of the change). Billing data shows where the money "
            "went, not why; confirm the reason with the owning team."
        )
    else:
        confidence = "low"
        statement = (
            "No single contributor explains most of the increase. The billing data alone does "
            "not identify a single cause; review the contributors listed above."
        )

    if not suggestions:
        suggestions.append(
            Suggestion(
                "Review changes around the incident dates",
                f"Compare deployments, configuration and traffic for {dates} with the top "
                "contributors.",
                "The contributors above show where the cost increased.",
            )
        )
    unique = list({s.title: s for s in suggestions}.values())
    return explanations, unique, confidence, statement


def _describe_usage(
    contributor: Contributor,
    kind: str,
    currency: str,
    explanations: list[str],
    suggestions: list[Suggestion],
) -> None:
    usage = contributor.usage
    if usage is None or contributor.is_new or not _material(contributor):
        return
    unit = f" {usage.unit}" if usage.unit else ""
    if usage.driver == "usage":
        explanations.append(
            f"{kind} '{contributor.label}': usage rose from "
            f"{_quantity(usage.baseline_daily_quantity)}{unit}/day to "
            f"{_quantity(usage.current_daily_quantity)}{unit}/day ({usage.quantity_ratio}x) "
            f"while cost rose {usage.cost_ratio}x, so the increase is usage-driven."
        )
        suggestions.append(
            Suggestion(
                f"Find what drove usage of {contributor.label}",
                "Check traffic, batch jobs, autoscaling events and retries during the incident.",
                f"Usage grew {usage.quantity_ratio}x with an unchanged unit cost.",
            )
        )
    elif usage.driver == "rate":
        explanations.append(
            f"{kind} '{contributor.label}': usage stayed about the same "
            f"({usage.quantity_ratio}x) but cost rose {usage.cost_ratio}x, which is consistent "
            "with a price or rate change."
        )
        suggestions.append(
            Suggestion(
                f"Check pricing for {contributor.label}",
                "Look for expired reservations or savings plans, pricing tier changes, or a "
                "different instance/storage class.",
                f"Cost per unit increased about {usage.cost_ratio}x at constant usage.",
            )
        )
    elif usage.driver == "unknown":
        explanations.append(
            f"{kind} '{contributor.label}': usage quantities are not available, so it cannot be "
            "determined whether the increase is usage- or price-driven."
        )


def _chart(
    db: Session, incident: Incident, filters: CostFilters, baseline_start: date
) -> list[ChartPoint]:
    currency = incident.currency
    as_of = latest_data_date(db, currency) or incident.end_date
    end = min(as_of, incident.end_date + timedelta(days=CHART_PADDING_AFTER))
    costs = daily_costs(db, currency, baseline_start, end, filters)
    covered = coverage_days(db, currency, baseline_start, end)
    detections = {
        d.anomaly_date: d
        for d in db.scalars(
            select(AnomalyDetection).where(AnomalyDetection.incident_id == incident.id)
        ).all()
    }
    return [
        ChartPoint(
            day=day,
            cost=costs.get(day, ZERO) if day in covered else None,
            expected=detections[day].expected_cost if day in detections else None,
            is_anomaly=day in detections,
        )
        for day in days_between(baseline_start, end)
    ]


def _related(db: Session, incident: Incident) -> list[RelatedIncident]:
    rows = db.scalars(
        select(Incident)
        .where(
            Incident.id != incident.id,
            Incident.currency == incident.currency,
            Incident.start_date <= incident.end_date,
            Incident.end_date >= incident.start_date,
        )
        .order_by(Incident.id)
        .limit(10)
    ).all()
    return [
        RelatedIncident(r.id, r.title, r.status, r.severity, r.start_date, r.end_date) for r in rows
    ]
