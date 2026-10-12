"""Celery tasks. Each task opens its own database session and always closes it."""

from app.db.session import get_sessionmaker
from app.services.anomaly_detection.service import run_detection
from app.services.auth.service import purge_expired_sessions
from app.services.budgeting.service import evaluate_budgets
from app.services.notifications.service import retry_failed
from app.services.pipeline import notify_new_incidents
from app.workers.celery_app import celery_app


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
