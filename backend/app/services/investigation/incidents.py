"""Incident workflow: listing, acknowledgement, notes, resolution and reopening."""

from datetime import UTC, datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.models.anomaly import Incident, IncidentEvent, IncidentStatus

STATUS_RANK = case(
    (Incident.status == IncidentStatus.OPEN, 0),
    (Incident.status == IncidentStatus.ACKNOWLEDGED, 1),
    else_=2,
)
SEVERITY_RANK = case(
    (Incident.severity == "critical", 0),
    (Incident.severity == "high", 1),
    (Incident.severity == "medium", 2),
    else_=3,
)


def get_incident(db: Session, incident_id: int) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise NotFoundError("Incident", incident_id)
    return incident


def list_incidents(
    db: Session,
    *,
    status: str | None,
    severity: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Incident], int]:
    """Unresolved first, then most severe, then most recent."""
    conditions = []
    if status is not None:
        conditions.append(Incident.status == status)
    if severity is not None:
        conditions.append(Incident.severity == severity)
    total = db.scalar(select(func.count()).select_from(Incident).where(*conditions)) or 0
    items = db.scalars(
        select(Incident)
        .where(*conditions)
        .order_by(STATUS_RANK, Incident.end_date.desc(), SEVERITY_RANK, Incident.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(items), total


def incident_counts(db: Session) -> dict[str, int]:
    rows = db.execute(select(Incident.status, func.count()).group_by(Incident.status)).all()
    counts = {status.value: 0 for status in IncidentStatus}
    counts.update(dict(rows))
    return counts


def _event(
    db: Session, incident: Incident, event_type: str, actor: str, message: str
) -> IncidentEvent:
    event = IncidentEvent(
        incident_id=incident.id, event_type=event_type, actor=actor, message=message
    )
    db.add(event)
    return event


def acknowledge(db: Session, incident: Incident, actor: str, note: str | None) -> Incident:
    if incident.status != IncidentStatus.OPEN:
        raise AppError(
            f"Only open incidents can be acknowledged (this one is {incident.status}).",
            code="invalid_transition",
            status_code=409,
        )
    incident.status = IncidentStatus.ACKNOWLEDGED
    incident.acknowledged_at = datetime.now(UTC)
    incident.acknowledged_by = actor
    _event(db, incident, "acknowledged", actor, note or "Incident acknowledged.")
    db.commit()
    return incident


def resolve(db: Session, incident: Incident, actor: str, resolution_note: str) -> Incident:
    if incident.status == IncidentStatus.RESOLVED:
        raise AppError(
            "The incident is already resolved.", code="invalid_transition", status_code=409
        )
    incident.status = IncidentStatus.RESOLVED
    incident.resolved_at = datetime.now(UTC)
    incident.resolved_by = actor
    incident.resolution_note = resolution_note
    _event(db, incident, "resolved", actor, resolution_note)
    db.commit()
    return incident


def reopen(db: Session, incident: Incident, actor: str, reason: str | None) -> Incident:
    if incident.status != IncidentStatus.RESOLVED:
        raise AppError(
            "Only resolved incidents can be reopened.", code="invalid_transition", status_code=409
        )
    incident.status = IncidentStatus.OPEN
    incident.resolved_at = None
    incident.resolved_by = None
    incident.resolution_note = None
    incident.acknowledged_at = None
    incident.acknowledged_by = None
    _event(db, incident, "reopened", actor, reason or "Incident reopened.")
    db.commit()
    return incident


def add_note(db: Session, incident: Incident, author: str, body: str) -> IncidentEvent:
    event = _event(db, incident, "note", author, body)
    # Touch the incident so "updated_at" reflects the latest activity.
    incident.updated_at = datetime.now(UTC)
    db.commit()
    return event
