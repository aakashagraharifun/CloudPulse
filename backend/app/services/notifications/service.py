"""Notification delivery over webhooks and e-mail.

Guarantees:
* Every attempt is recorded in `notification_deliveries` with its outcome.
* (channel, event_key) is unique, so the same event is never sent twice to a
  channel - callers choose event keys that encode the alert policy.
* Delivery errors are caught and recorded; they never propagate to billing
  ingestion, anomaly detection or budget evaluation.
"""

import logging
import smtplib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import NotificationChannel, NotificationDelivery
from app.models.anomaly import SEVERITY_ORDER, Severity

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
RETRY_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class Notification:
    event_type: str  # budget_threshold | incident_opened | test
    event_key: str
    subject: str
    body: str
    data: dict[str, Any]

    def payload(self) -> dict[str, Any]:
        # "text" at the top level renders directly in Slack/Teams-style incoming webhooks.
        return {
            "source": "cloudpulse",
            "event": self.event_type,
            "subject": self.subject,
            "text": f"{self.subject}\n{self.body}",
            "data": self.data,
        }


def parse_recipients(target: str) -> list[str]:
    return [part.strip() for part in target.split(",") if part.strip()]


def send_webhook(url: str, payload: dict[str, Any], settings: Settings) -> None:
    response = httpx.post(
        url,
        json=payload,
        timeout=settings.notification_timeout_seconds,
        follow_redirects=False,
        headers={"User-Agent": "CloudPulse-Notifier/0.1"},
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Webhook returned HTTP {response.status_code}")


def send_email(recipients: list[str], subject: str, body: str, settings: Settings) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(
        settings.smtp_host, settings.smtp_port, timeout=settings.notification_timeout_seconds
    ) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_username and settings.smtp_password:
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        smtp.send_message(message)


def _attempt(delivery: NotificationDelivery, channel: NotificationChannel | None) -> None:
    settings = get_settings()
    delivery.attempts += 1
    delivery.last_attempt_at = datetime.now(UTC)
    try:
        if channel is None:
            raise RuntimeError("The channel no longer exists.")
        if channel.type == "webhook":
            send_webhook(channel.target, delivery.payload, settings)
        else:
            send_email(parse_recipients(channel.target), delivery.subject, delivery.body, settings)
    except Exception as exc:  # recorded, never raised
        delivery.status = "failed"
        delivery.last_error = f"{type(exc).__name__}: {exc}"[:2000]
        logger.warning(
            "Notification delivery failed",
            extra={"context": {"delivery_id": delivery.id, "error": delivery.last_error}},
        )
    else:
        delivery.status = "sent"
        delivery.sent_at = datetime.now(UTC)
        delivery.last_error = None


def deliver(
    db: Session, notification: Notification, channels: Iterable[NotificationChannel]
) -> list[NotificationDelivery]:
    """Create one delivery per channel (skipping already-delivered events) and send it."""
    deliveries: list[NotificationDelivery] = []
    for channel in channels:
        try:
            inserted_id = db.scalar(
                insert(NotificationDelivery)
                .values(
                    channel_id=channel.id,
                    channel_name=channel.name,
                    channel_type=channel.type,
                    event_type=notification.event_type,
                    event_key=notification.event_key,
                    subject=notification.subject,
                    body=notification.body,
                    payload=notification.payload(),
                    status="pending",
                    attempts=0,
                )
                .on_conflict_do_nothing(
                    index_elements=[NotificationDelivery.channel_id, NotificationDelivery.event_key]
                )
                .returning(NotificationDelivery.id)
            )
            db.commit()
            if inserted_id is None:
                continue  # already delivered (or attempted) for this event
            delivery = db.get(NotificationDelivery, inserted_id)
            assert delivery is not None
            _attempt(delivery, channel)
            db.commit()
            deliveries.append(delivery)
        except Exception:
            db.rollback()
            logger.exception("Could not record a notification for channel %s", channel.id)
    return deliveries


def channels_for_incident(db: Session, severity: str) -> list[NotificationChannel]:
    rank = SEVERITY_ORDER[Severity(severity)]
    channels = db.scalars(
        select(NotificationChannel).where(
            NotificationChannel.enabled.is_(True), NotificationChannel.notify_incidents.is_(True)
        )
    ).all()
    return [c for c in channels if SEVERITY_ORDER[Severity(c.min_severity)] <= rank]


def channels_for_budgets(db: Session) -> list[NotificationChannel]:
    return list(
        db.scalars(
            select(NotificationChannel).where(
                NotificationChannel.enabled.is_(True),
                NotificationChannel.notify_budget_alerts.is_(True),
            )
        ).all()
    )


def retry_failed(db: Session) -> int:
    """Retry recent failed deliveries that have attempts left. Returns the number retried."""
    cutoff = datetime.now(UTC) - RETRY_WINDOW
    failed = db.scalars(
        select(NotificationDelivery).where(
            NotificationDelivery.status == "failed",
            NotificationDelivery.attempts < MAX_ATTEMPTS,
            NotificationDelivery.created_at >= cutoff,
        )
    ).all()
    retried = 0
    for delivery in failed:
        channel = db.get(NotificationChannel, delivery.channel_id) if delivery.channel_id else None
        if channel is not None and not channel.enabled:
            continue
        _attempt(delivery, channel)
        db.commit()
        retried += 1
    return retried
