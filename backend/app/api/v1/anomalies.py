"""Anomaly detection settings and runs."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_member
from app.db.session import get_db
from app.models import User
from app.models.anomaly import DetectionRun
from app.schemas.anomalies import DetectionRunRead, DetectionSettingsRead, DetectionSettingsUpdate
from app.schemas.common import Page
from app.services.anomaly_detection import service as detection
from app.services.audit import record_audit
from app.services.pipeline import notify_new_incidents

router = APIRouter(prefix="/anomalies", tags=["anomaly detection"])


@router.get("/settings", response_model=DetectionSettingsRead, summary="Detection thresholds")
def get_settings(db: Session = Depends(get_db)) -> DetectionSettingsRead:
    return DetectionSettingsRead.model_validate(detection.get_settings_row(db))


@router.put(
    "/settings",
    response_model=DetectionSettingsRead,
    summary="Update detection thresholds (applies to future runs)",
)
def update_settings(
    payload: DetectionSettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> DetectionSettingsRead:
    row = detection.get_settings_row(db)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    record_audit(
        db,
        "detection.settings_updated",
        actor=user,
        request=request,
        target_type="detection_settings",
        target_id=1,
        details=payload.model_dump(mode="json"),
    )
    db.commit()
    db.refresh(row)
    return DetectionSettingsRead.model_validate(row)


@router.post(
    "/runs",
    response_model=DetectionRunRead,
    summary="Run detection now over the most recent days of data",
)
def run_now(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_member)
) -> DetectionRunRead:
    outcome = detection.run_detection(db, trigger="manual")
    record_audit(
        db,
        "detection.run",
        actor=user,
        request=request,
        target_type="detection_run",
        target_id=outcome.run.id,
        details={"status": outcome.run.status, "incidents_created": outcome.run.incidents_created},
    )
    db.commit()
    notify_new_incidents(db, outcome.new_incident_ids)
    return DetectionRunRead.model_validate(outcome.run)


@router.get("/runs", response_model=Page[DetectionRunRead], summary="Detection run history")
def list_runs(
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> Page[DetectionRunRead]:
    total = db.scalar(select(func.count()).select_from(DetectionRun)) or 0
    runs = db.scalars(
        select(DetectionRun).order_by(DetectionRun.id.desc()).limit(limit).offset(offset)
    ).all()
    return Page[DetectionRunRead](
        items=[DetectionRunRead.model_validate(r) for r in runs],
        total=total,
        limit=limit,
        offset=offset,
    )
