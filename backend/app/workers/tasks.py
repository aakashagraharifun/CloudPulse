"""Celery tasks. Each task opens its own database session and always closes it."""

import logging

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.services.anomaly_detection.service import run_detection
from app.services.auth.service import purge_expired_sessions
from app.services.budgeting.service import evaluate_budgets
from app.services.connectors.service import due_connectors, sync_connector
from app.services.notifications.service import retry_failed
from app.services.pipeline import notify_new_incidents, run_post_import_evaluation
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="cloudpulse.run_anomaly_detection")
def run_anomaly_detection_task() -> dict:
    with get_sessionmaker()() as db:
        outcome = run_detection(db, trigger="scheduled")
        notify_new_incidents(db, outcome.new_incident_ids)
        return {"run_id": outcome.run.id, "status": outcome.run.status}


@celery_app.task(name="cloudpulse.evaluate_budgets")
def evaluate_budgets_task() -> dict:
    with get_sessionmaker()() as db:
        return {"notifications_sent": evaluate_budgets(db)}


@celery_app.task(name="cloudpulse.retry_failed_notifications")
def retry_failed_notifications_task() -> dict:
    with get_sessionmaker()() as db:
        return {"retried": retry_failed(db)}


@celery_app.task(name="cloudpulse.purge_expired_sessions")
def purge_expired_sessions_task() -> dict:
    with get_sessionmaker()() as db:
        return {"deleted": purge_expired_sessions(db)}


@celery_app.task(name="cloudpulse.sync_due_connectors")
def sync_due_connectors_task() -> dict:
    """Sync every enabled connector whose interval has elapsed, one after another."""
    settings = get_settings()
    results: dict[str, str] = {}
    changed = False
    with get_sessionmaker()() as db:
        for connector_id in due_connectors(db):
            try:
                outcome = sync_connector(db, settings, connector_id)
            except Exception:  # e.g. a sync already running; try again next round
                db.rollback()
                logger.exception(
                    "Scheduled connector sync skipped",
                    extra={"context": {"connector_id": connector_id}},
                )
                results[str(connector_id)] = "skipped"
                continue
            results[str(connector_id)] = outcome.status
            changed = changed or (outcome.changed and outcome.status == "succeeded")
        if changed:
            run_post_import_evaluation(db)
    return results
