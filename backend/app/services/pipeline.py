"""Work that runs after billing data changes: anomaly detection and budget checks.

Failures here are logged and swallowed: they must never undo or fail a
billing import that has already been committed.
"""

import logging

from sqlalchemy.orm import Session

from app.models import Incident
from app.services.anomaly_detection.service import run_detection, scope_label
from app.services.budgeting.service import evaluate_budgets
from app.services.notifications.service import Notification, channels_for_incident, deliver

logger = logging.getLogger(__name__)


def run_post_import_evaluation(db: Session) -> None:
    try:
        outcome = run_detection(db, trigger="post_import")
        notify_new_incidents(db, outcome.new_incident_ids)
    except Exception:
        db.rollback()
        logger.exception("Post-import anomaly detection failed")
    try:
        evaluate_budgets(db)
    except Exception:
        db.rollback()
        logger.exception("Post-import budget evaluation failed")


def incident_notification(incident: Incident) -> Notification:
    pct = (
        f"+{incident.peak_deviation_pct}% on the peak day"
        if incident.peak_deviation_pct is not None
        else "new spend with no baseline"
    )
    subject = f"[CloudPulse] {incident.severity.upper()}: {incident.title}"
    body = (
        f"Scope: {scope_label(incident.scope_type, incident.scope_value)}\n"
        f"Dates: {incident.start_date.isoformat()} to {incident.end_date.isoformat()}\n"
        f"Observed: {incident.observed_cost:.2f} {incident.currency}\n"
        f"Expected: {incident.expected_cost:.2f} {incident.currency}\n"
        f"Increase: {incident.deviation_abs:.2f} {incident.currency} ({pct})\n"
        f"Investigate: /dashboard/incidents/{incident.id}\n"
    )
    return Notification(
        event_type="incident_opened",
        event_key=f"incident:{incident.id}:opened",
        subject=subject,
        body=body,
        data={
            "incident_id": incident.id,
            "severity": incident.severity,
            "scope_type": incident.scope_type,
            "scope_value": incident.scope_value,
            "currency": incident.currency,
            "start_date": incident.start_date.isoformat(),
            "end_date": incident.end_date.isoformat(),
            "observed_cost": str(incident.observed_cost),
            "expected_cost": str(incident.expected_cost),
        },
    )


def notify_new_incidents(db: Session, incident_ids: list[int]) -> None:
    for incident_id in incident_ids:
        try:
            incident = db.get(Incident, incident_id)
            if incident is None:
                continue
            channels = channels_for_incident(db, incident.severity)
            if channels:
                deliver(db, incident_notification(incident), channels)
        except Exception:
            db.rollback()
            logger.exception("Could not notify about incident %s", incident_id)
