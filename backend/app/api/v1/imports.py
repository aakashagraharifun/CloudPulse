"""Billing import endpoints."""

import csv
import io
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_member
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db
from app.models import BillingImport, ImportSource, ImportStatus, User
from app.schemas.common import Page
from app.schemas.imports import CanonicalField, ImportDetail, ImportSchemaResponse, ImportSummary
from app.services.audit import record_audit
from app.services.ingestion import service
from app.services.ingestion.sample_data import default_end_date, generate_sample_csv
from app.services.normalization.schema import CANONICAL_FIELDS
from app.services.pipeline import run_post_import_evaluation

router = APIRouter(prefix="/imports", tags=["imports"])
# The CSV template contains no billing data, so it is available without signing in
# (it is downloaded with a plain link).
public_router = APIRouter(prefix="/imports", tags=["imports"])

# Multipart framing adds a little overhead on top of the file itself.
_MULTIPART_OVERHEAD_BYTES = 64 * 1024
_IMPORT_FAILED_RESPONSES = {
    409: {"description": "The identical file was already imported."},
    413: {"description": "The file exceeds the upload size limit."},
    415: {"description": "The file is not a .csv file."},
    422: {"description": "The file failed validation; `error.details` holds the import."},
}


def _finish(
    db: Session, billing_import: BillingImport, user: User, request: Request, action: str
) -> ImportDetail:
    detail = ImportDetail.model_validate(billing_import)
    record_audit(
        db,
        action,
        actor=user,
        request=request,
        target_type="import",
        target_id=billing_import.id,
        details={
            "filename": billing_import.filename,
            "status": billing_import.status,
            "rows_inserted": billing_import.rows_inserted,
            "rows_duplicate": billing_import.rows_duplicate,
            "rows_invalid": billing_import.rows_invalid,
        },
    )
    db.commit()
    if billing_import.status == ImportStatus.FAILED:
        raise AppError(
            billing_import.error_summary or "The file failed validation.",
            code="import_validation_failed",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details=detail.model_dump(mode="json"),
        )
    if billing_import.rows_inserted > 0:
        run_post_import_evaluation(db)
    return detail


@router.get("/schema", response_model=ImportSchemaResponse, summary="Canonical CSV schema")
def import_schema(settings: Settings = Depends(get_settings)) -> ImportSchemaResponse:
    return ImportSchemaResponse(
        fields=[
            CanonicalField(
                name=spec.name,
                required=spec.required,
                description=spec.description,
                example=spec.example,
                accepted_headers=list(spec.aliases),
            )
            for spec in CANONICAL_FIELDS
        ],
        max_upload_bytes=settings.max_upload_bytes,
        max_rows=settings.max_upload_rows,
    )


@public_router.get(
    "/template.csv",
    summary="Download a CSV template",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
def import_template() -> Response:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([spec.name for spec in CANONICAL_FIELDS])
    writer.writerow([spec.example for spec in CANONICAL_FIELDS])
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="cloudpulse-billing-template.csv"'},
    )


@router.post(
    "",
    response_model=ImportDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a billing CSV",
    responses=_IMPORT_FAILED_RESPONSES,
)
def upload_billing_file(
    request: Request,
    file: UploadFile = File(..., description="Billing CSV (UTF-8)"),
    is_sample: bool = Form(False, description="Mark the file as synthetic / sample data"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(require_member),
) -> ImportDetail:
    # Reject oversized requests early using the declared length, then re-check the
    # actual bytes read (the header can be absent or wrong).
    declared = request.headers.get("content-length", "")
    if declared.isdigit():
        service.validate_file_size(int(declared) - _MULTIPART_OVERHEAD_BYTES, settings)
    filename = service.sanitize_filename(file.filename)
    service.validate_file_type(filename)
    content = file.file.read(settings.max_upload_bytes + 1)
    service.validate_file_size(len(content), settings)
    billing_import = service.import_billing_file(
        db,
        filename=filename,
        content=content,
        settings=settings,
        source=ImportSource.SAMPLE if is_sample else ImportSource.UPLOAD,
    )
    return _finish(db, billing_import, user, request, "import.uploaded")


@router.post(
    "/sample",
    response_model=ImportDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Load the built-in synthetic dataset (90 days, with injected anomalies)",
    responses={
        409: {
            "description": "Sample data is already loaded and complete, or the loaded sample "
            "does not match the built-in one."
        }
    },
)
def load_sample_data(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(require_member),
) -> ImportDetail:
    """Load the synthetic dataset, or add what a newer version of it contains.

    When sample data from an earlier version is loaded (for example before AI and
    multi-cloud lines were added), only the missing records are imported, for the same
    dates. Existing records are never duplicated.
    """
    update = service.plan_sample_update(db, settings)
    if update is not None:
        billing_import = service.import_billing_file(
            db,
            filename=f"cloudpulse-sample-update-to-{update.end_date.isoformat()}.csv",
            content=update.content,
            settings=settings,
            source=ImportSource.SAMPLE,
            today=update.end_date + timedelta(days=1),
        )
        return _finish(db, billing_import, user, request, "import.sample_updated")
    end = default_end_date()
    content = generate_sample_csv(end).encode("utf-8")
    billing_import = service.import_billing_file(
        db,
        filename=f"cloudpulse-sample-billing-90d-to-{end.isoformat()}.csv",
        content=content,
        settings=settings,
        source=ImportSource.SAMPLE,
    )
    return _finish(db, billing_import, user, request, "import.sample_loaded")


@router.get("", response_model=Page[ImportSummary], summary="List imports (newest first)")
def list_imports(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> Page[ImportSummary]:
    items, total = service.list_imports(db, limit=limit, offset=offset)
    return Page[ImportSummary](
        items=[ImportSummary.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{import_id}", response_model=ImportDetail, summary="Import status and errors")
def get_import(import_id: int, db: Session = Depends(get_db)) -> ImportDetail:
    return ImportDetail.model_validate(service.get_import(db, import_id))


@router.delete(
    "/{import_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an import and all of its billing records",
)
def delete_import(
    import_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> Response:
    billing_import = service.get_import(db, import_id)
    details = {"filename": billing_import.filename, "rows_inserted": billing_import.rows_inserted}
    service.delete_import(db, import_id)
    record_audit(
        db,
        "import.deleted",
        actor=user,
        request=request,
        target_type="import",
        target_id=import_id,
        details=details,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
