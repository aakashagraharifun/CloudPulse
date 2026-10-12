"""Audit log helper. Callers add the event to the same transaction as the change."""

from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.request_context import current_request_id
from app.models import AuditEvent, User


def client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host[:64]


def record_audit(
    db: Session,
    action: str,
    *,
    actor: User | None,
    request: Request | None = None,
    target_type: str | None = None,
    target_id: object | None = None,
    details: dict[str, Any] | None = None,
    actor_email: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=actor.id if actor else None,
        actor_email=actor.email if actor else actor_email,
        action=action,
        target_type=target_type,
        target_id=None if target_id is None else str(target_id)[:64],
        details=details,
        ip_address=client_ip(request),
        request_id=current_request_id(),
    )
    db.add(event)
    return event
