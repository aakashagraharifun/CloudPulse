"""Incidents: list, detail, workflow actions and investigation evidence."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.anomalies import (
    AcknowledgeInput,
    IncidentCounts,
    IncidentDetail,
    IncidentEventRead,
    IncidentSummary,
    InvestigationRead,
    NoteInput,
    ReopenInput,
    ResolveInput,
    SeverityLiteral,
    StatusLiteral,
)
from app.schemas.common import Page
from app.services.investigation import incidents as workflow
from app.services.investigation.service import investigate

router = APIRouter(prefix="/incidents", tags=["incidents"])

_TRANSITION_ERRORS = {409: {"description": "The action is not valid in the current status."}}


@router.get("", response_model=Page[IncidentSummary], summary="List incidents")
def list_incidents(
    status_filter: StatusLiteral | None = Query(None, alias="status"),
    severity: SeverityLiteral | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> Page[IncidentSummary]:
    items, total = workflow.list_incidents(
        db, status=status_filter, severity=severity, limit=limit, offset=offset
    )
    return Page[IncidentSummary](
        items=[IncidentSummary.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/counts", response_model=IncidentCounts, summary="Incident counts by status")
def counts(db: Session = Depends(get_db)) -> IncidentCounts:
    return IncidentCounts.model_validate(workflow.incident_counts(db))


@router.get("/{incident_id}", response_model=IncidentDetail, summary="Incident with evidence")
def get_incident(incident_id: int, db: Session = Depends(get_db)) -> IncidentDetail:
    return IncidentDetail.model_validate(workflow.get_incident(db, incident_id))


@router.get(
    "/{incident_id}/investigation",
    response_model=InvestigationRead,
    summary="Contributors, explanations and suggestions computed from billing data",
)
def get_investigation(incident_id: int, db: Session = Depends(get_db)) -> InvestigationRead:
    incident = workflow.get_incident(db, incident_id)
    return InvestigationRead.model_validate(investigate(db, incident))


@router.post(
    "/{incident_id}/acknowledge",
    response_model=IncidentDetail,
    responses=_TRANSITION_ERRORS,
)
def acknowledge(
    incident_id: int, payload: AcknowledgeInput, db: Session = Depends(get_db)
) -> IncidentDetail:
    incident = workflow.get_incident(db, incident_id)
    workflow.acknowledge(db, incident, payload.actor, payload.note)
    db.refresh(incident)
    return IncidentDetail.model_validate(incident)


@router.post("/{incident_id}/resolve", response_model=IncidentDetail, responses=_TRANSITION_ERRORS)
def resolve(
    incident_id: int, payload: ResolveInput, db: Session = Depends(get_db)
) -> IncidentDetail:
    incident = workflow.get_incident(db, incident_id)
    workflow.resolve(db, incident, payload.actor, payload.resolution_note)
    db.refresh(incident)
    return IncidentDetail.model_validate(incident)


@router.post("/{incident_id}/reopen", response_model=IncidentDetail, responses=_TRANSITION_ERRORS)
def reopen(incident_id: int, payload: ReopenInput, db: Session = Depends(get_db)) -> IncidentDetail:
    incident = workflow.get_incident(db, incident_id)
    workflow.reopen(db, incident, payload.actor, payload.reason)
    db.refresh(incident)
    return IncidentDetail.model_validate(incident)


@router.post(
    "/{incident_id}/notes",
    response_model=IncidentEventRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a note to the incident timeline",
)
def add_note(
    incident_id: int, payload: NoteInput, db: Session = Depends(get_db)
) -> IncidentEventRead:
    incident = workflow.get_incident(db, incident_id)
    return IncidentEventRead.model_validate(
        workflow.add_note(db, incident, payload.actor, payload.body)
    )
