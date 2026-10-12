"""Run anomaly detection over stored billing data and maintain incidents.

Incident de-duplication:
* A detection is unique per (currency, scope, day). Re-running detection
  updates the existing detection instead of inserting a new one.
* A new anomalous day joins an unresolved incident of the same scope when it is
  adjacent to (or inside) that incident's date range; otherwise it opens a new
  incident. Days already attached to a resolved incident never reopen or
  duplicate it.
* A PostgreSQL advisory lock serialises concurrent runs, so two runs cannot
  both create an incident for the same event.
"""

import logging
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import BillingRecord
from app.models.anomaly import (
    SEVERITY_ORDER,
    AnomalyDetection,
    DetectionRun,
    DetectionSettings,
    Incident,
    IncidentEvent,
    IncidentStatus,
    Severity,
)
from app.services.analytics.service import UNASSIGNED, CostFilters, Dimension, coverage_days
from app.services.anomaly_detection.engine import (
    DOW_LOOKBACK_DAYS,
    ZERO,
    DetectionConfig,
    PointEvaluation,
    evaluate_point,
)

logger = logging.getLogger(__name__)

ADVISORY_LOCK_KEY = 7_420_001
TOTAL_SCOPE = "total"
ALLOWED_SCOPES = (TOTAL_SCOPE, *(d.value for d in Dimension))
MAX_RUN_NOTES = 50
SYSTEM_ACTOR = "CloudPulse"

DIMENSION_LABELS = {
    "provider": "Provider",
    "account_id": "Account",
    "service": "Service",
    "region": "Region",
    "resource_id": "Resource",
    "usage_type": "Usage type",
    "project": "Project",
    "environment": "Environment",
}


def scope_label(scope_type: str, scope_value: str) -> str:
    if scope_type == TOTAL_SCOPE:
        return "Total spend"
    return f"{DIMENSION_LABELS.get(scope_type, scope_type)}: {scope_value}"


def scope_filters(scope_type: str, scope_value: str) -> CostFilters:
    if scope_type == TOTAL_SCOPE:
        return CostFilters()
    return CostFilters(**{scope_type: scope_value})


def incident_title(kind: str, scope_type: str, scope_value: str) -> str:
    prefix = "New spend" if kind == "new_spend" else "Cost spike"
    return f"{prefix} — {scope_label(scope_type, scope_value)}"


# --- settings ----------------------------------------------------------------


def get_settings_row(db: Session) -> DetectionSettings:
    row = db.get(DetectionSettings, 1)
    if row is None:
        row = DetectionSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def to_config(row: DetectionSettings) -> DetectionConfig:
    return DetectionConfig(
        pct_threshold=row.pct_threshold,
        abs_threshold=row.abs_threshold,
        z_threshold=row.z_threshold,
        new_spend_threshold=row.new_spend_threshold,
        min_history_days=row.min_history_days,
        baseline_window_days=row.baseline_window_days,
        severity_medium_pct=row.severity_medium_pct,
        severity_high_pct=row.severity_high_pct,
        severity_critical_pct=row.severity_critical_pct,
        severity_medium_abs=row.severity_medium_abs,
        severity_high_abs=row.severity_high_abs,
        severity_critical_abs=row.severity_critical_abs,
    )


def _snapshot(row: DetectionSettings) -> dict:
    data = {k: str(v) for k, v in asdict(to_config(row)).items()}
    data["evaluation_window_days"] = str(row.evaluation_window_days)
    data["scopes"] = list(row.scopes)
    return data


# --- series loading ----------------------------------------------------------


def load_scope_series(
    db: Session, currency: str, scope_type: str, start: date, end: date
) -> dict[str, dict[date, Decimal]]:
    """Daily cost per scope value. The total scope has a single value ""."""
    where = (
        BillingRecord.currency == currency,
        BillingRecord.usage_date >= start,
        BillingRecord.usage_date <= end,
    )
    series: dict[str, dict[date, Decimal]] = {}
    if scope_type == TOTAL_SCOPE:
        rows = db.execute(
            select(BillingRecord.usage_date, func.sum(BillingRecord.cost))
            .where(*where)
            .group_by(BillingRecord.usage_date)
        ).all()
        series[""] = dict(rows)
        return series
    column = getattr(BillingRecord, scope_type)
    rows = db.execute(
        select(column, BillingRecord.usage_date, func.sum(BillingRecord.cost))
        .where(*where)
        .group_by(column, BillingRecord.usage_date)
    ).all()
    for value, day, cost in rows:
        series.setdefault(value if value is not None else UNASSIGNED, {})[day] = cost
    return series


# --- run -----------------------------------------------------------------------


@dataclass
class RunOutcome:
    run: DetectionRun
    new_incident_ids: list[int]


def run_detection(db: Session, trigger: str = "manual") -> RunOutcome:
    """Evaluate recent days for every currency and scope. Never raises."""
    settings_row = get_settings_row(db)
    config = to_config(settings_row)
    run = DetectionRun(trigger=trigger, status="running", settings_snapshot=_snapshot(settings_row))
    db.add(run)
    db.commit()
    run_id = run.id

    try:
        new_incident_ids = _execute(db, run, settings_row, config)
        run.status = "completed"
        run.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Anomaly detection run %s failed", run_id)
        run = db.get(DetectionRun, run_id) or run
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"[:2000]
        run.finished_at = datetime.now(UTC)
        db.commit()
        return RunOutcome(run, [])

    logger.info(
        "Anomaly detection completed",
        extra={
            "context": {
                "run_id": run.id,
                "anomalies": run.anomalies_detected,
                "incidents_created": run.incidents_created,
            }
        },
    )
    return RunOutcome(run, new_incident_ids)


def _execute(
    db: Session, run: DetectionRun, settings_row: DetectionSettings, config: DetectionConfig
) -> list[int]:
    # Serialise runs; released automatically when this transaction ends.
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADVISORY_LOCK_KEY})

    currencies = sorted(db.scalars(select(BillingRecord.currency).distinct()).all())
    run.currencies = currencies
    notes: list[str] = []
    new_incident_ids: list[int] = []
    now = datetime.now(UTC)
    scopes = [s for s in settings_row.scopes if s in ALLOWED_SCOPES]

    for currency in currencies:
        as_of = db.scalar(
            select(func.max(BillingRecord.usage_date)).where(BillingRecord.currency == currency)
        )
        if as_of is None:
            continue
        eval_days = [
            as_of - timedelta(days=offset)
            for offset in range(settings_row.evaluation_window_days - 1, -1, -1)
        ]
        history_start = eval_days[0] - timedelta(
            days=max(config.baseline_window_days, DOW_LOOKBACK_DAYS)
        )
        run.evaluation_start = min(filter(None, [run.evaluation_start, eval_days[0]]))
        run.evaluation_end = max(filter(None, [run.evaluation_end, as_of]))
        covered = coverage_days(db, currency, history_start, as_of)

        for scope_type in scopes:
            all_series = load_scope_series(db, currency, scope_type, history_start, as_of)
            for scope_value, series in sorted(all_series.items()):
                if not any(series.get(day, ZERO) > 0 for day in eval_days):
                    continue  # nothing that could be an increase
                run.series_evaluated += 1
                insufficient = 0
                for day in eval_days:
                    evaluation = evaluate_point(series, covered, day, config)
                    if evaluation.status == "no_data":
                        continue
                    if evaluation.status == "insufficient_history":
                        insufficient += 1
                        continue
                    run.points_evaluated += 1
                    if evaluation.status == "anomaly":
                        run.anomalies_detected += 1
                        incident_id = _record_anomaly(
                            db, run, currency, scope_type, scope_value, evaluation, config, now
                        )
                        if incident_id is not None:
                            new_incident_ids.append(incident_id)
                if insufficient:
                    run.points_insufficient_history += insufficient
                    if len(notes) < MAX_RUN_NOTES:
                        notes.append(
                            f"{scope_label(scope_type, scope_value)} ({currency}): {insufficient} "
                            "day(s) not evaluated because there is not enough history for a "
                            "reliable baseline."
                        )

    run.incidents_created = len(new_incident_ids)
    run.notes = notes or None
    return new_incident_ids


def _record_anomaly(
    db: Session,
    run: DetectionRun,
    currency: str,
    scope_type: str,
    scope_value: str,
    evaluation: PointEvaluation,
    config: DetectionConfig,
    now: datetime,
) -> int | None:
    """Upsert the detection and attach it to an incident. Returns a NEW incident's id."""
    assert evaluation.expected is not None and evaluation.deviation_abs is not None
    assert evaluation.kind is not None and evaluation.severity is not None
    assert evaluation.method is not None

    detection = db.scalar(
        select(AnomalyDetection).where(
            AnomalyDetection.currency == currency,
            AnomalyDetection.scope_type == scope_type,
            AnomalyDetection.scope_value == scope_value,
            AnomalyDetection.anomaly_date == evaluation.day,
        )
    )
    if detection is None:
        detection = AnomalyDetection(
            currency=currency,
            scope_type=scope_type,
            scope_value=scope_value,
            anomaly_date=evaluation.day,
        )
        db.add(detection)

    detection.run_id = run.id
    detection.kind = evaluation.kind
    detection.severity = evaluation.severity
    detection.observed_cost = evaluation.observed
    detection.expected_cost = evaluation.expected
    detection.deviation_abs = evaluation.deviation_abs
    detection.deviation_pct = evaluation.deviation_pct
    detection.z_score = evaluation.z_score
    detection.baseline_method = evaluation.method
    detection.baseline_points = len(evaluation.baseline)
    detection.thresholds = config.thresholds()
    detection.evidence = evaluation.evidence()
    detection.last_evaluated_at = now
    db.flush()

    if detection.incident_id is not None:
        incident = db.get(Incident, detection.incident_id)
        if incident is not None:
            refresh_incident(db, incident)
        return None

    incident = db.scalar(
        select(Incident)
        .where(
            Incident.currency == currency,
            Incident.scope_type == scope_type,
            Incident.scope_value == scope_value,
            Incident.status != IncidentStatus.RESOLVED,
            Incident.start_date <= evaluation.day + timedelta(days=1),
            Incident.end_date >= evaluation.day - timedelta(days=1),
        )
        .order_by(Incident.end_date.desc())
        .limit(1)
    )
    created = incident is None
    if incident is None:
        incident = Incident(
            title=incident_title(evaluation.kind, scope_type, scope_value),
            status=IncidentStatus.OPEN,
            severity=evaluation.severity,
            kind=evaluation.kind,
            currency=currency,
            scope_type=scope_type,
            scope_value=scope_value,
            start_date=evaluation.day,
            end_date=evaluation.day,
            observed_cost=evaluation.observed,
            expected_cost=evaluation.expected,
            deviation_abs=evaluation.deviation_abs,
            peak_deviation_pct=evaluation.deviation_pct,
            detection_count=0,
        )
        db.add(incident)
        db.flush()
    detection.incident_id = incident.id
    db.flush()
    refresh_incident(db, incident)
    db.add(
        IncidentEvent(
            incident_id=incident.id,
            event_type="created" if created else "detection_added",
            actor=SYSTEM_ACTOR,
            message=(
                f"Incident opened: {evaluation.reason}"
                if created
                else f"Anomalous day {evaluation.day.isoformat()} added: {evaluation.reason}"
            ),
            data={"detection_id": detection.id, "run_id": run.id},
        )
    )
    return incident.id if created else None


def refresh_incident(db: Session, incident: Incident) -> None:
    """Recompute an incident's aggregates from its detections."""
    detections = db.scalars(
        select(AnomalyDetection).where(AnomalyDetection.incident_id == incident.id)
    ).all()
    if not detections:
        return
    incident.start_date = min(d.anomaly_date for d in detections)
    incident.end_date = max(d.anomaly_date for d in detections)
    incident.observed_cost = sum((d.observed_cost for d in detections), ZERO)
    incident.expected_cost = sum((d.expected_cost for d in detections), ZERO)
    incident.deviation_abs = sum((d.deviation_abs for d in detections), ZERO)
    percentages = [d.deviation_pct for d in detections if d.deviation_pct is not None]
    incident.peak_deviation_pct = max(percentages) if percentages else None
    incident.detection_count = len(detections)
    incident.severity = max(
        (Severity(d.severity) for d in detections), key=lambda s: SEVERITY_ORDER[s]
    ).value
    first = min(detections, key=lambda d: d.anomaly_date)
    incident.kind = first.kind
    incident.title = incident_title(first.kind, incident.scope_type, incident.scope_value)
    db.flush()
