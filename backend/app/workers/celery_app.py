"""Celery application: background and scheduled jobs (Redis broker).

Start a worker and the scheduler (from the backend directory):
    celery -A app.workers.celery_app worker --loglevel=INFO --pool=solo   # Windows
    celery -A app.workers.celery_app beat --loglevel=INFO
On Linux/Docker the default prefork pool is used instead of --pool=solo.
"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level, settings.log_json)

celery_app = Celery(
    "cloudpulse",
    broker=settings.redis_url,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_ignore_result=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "detect-anomalies": {
            "task": "cloudpulse.run_anomaly_detection",
            "schedule": crontab(minute=15, hour="*/6"),
        },
        "evaluate-budgets": {
            "task": "cloudpulse.evaluate_budgets",
            "schedule": crontab(minute=5),
        },
        "retry-failed-notifications": {
            "task": "cloudpulse.retry_failed_notifications",
            "schedule": crontab(minute="*/10"),
        },
    },
)
