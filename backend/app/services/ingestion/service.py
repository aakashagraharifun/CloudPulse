"""Billing import workflow: validate -> normalize -> persist, with status tracking.

Duplicate protection works at two levels:
* File level: a file whose SHA-256 matches an already *completed* import is
  rejected with 409 before anything is written.
* Record level: every record carries a content fingerprint with a unique
  constraint. Records already present (e.g. overlapping exports) are skipped
  and counted in `rows_duplicate`, never inserted twice.
"""

import hashlib
import logging
import re
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import PurePosixPath

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.models import BillingImport, BillingRecord, ImportSource, ImportStatus
from app.services.normalization.allocation import AllocationEngine
from app.services.normalization.normalizer import (
    FileValidationError,
    NormalizationResult,
    normalize_csv,
)

logger = logging.getLogger(__name__)

INSERT_CHUNK_SIZE = 2000
_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w.\- ()]+")


def sanitize_filename(name: str | None) -> str:
    """Keep only a display-safe base name. The name is never used as a file path."""
    base = PurePosixPath((name or "").replace("\\", "/")).name
    base = _UNSAFE_FILENAME_CHARS.sub("_", base).strip(" .")
    return (base or "upload.csv")[:255]


def validate_file_type(filename: str) -> None:
    if not filename.lower().endswith(".csv"):
        raise AppError(
            "Only .csv files are accepted.",
            code="unsupported_file_type",
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )


def validate_file_size(size: int, settings: Settings) -> None:
    if size > settings.max_upload_bytes:
        raise AppError(
            f"The file exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB upload limit.",
            code="file_too_large",
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        )


def _summarize_errors(result: NormalizationResult) -> str:
    rows = result.invalid_row_count
    noun = "row" if rows == 1 else "rows"
    summary = f"{rows} {noun} failed validation ({result.error_count} problems)."
    if result.error_count > len(result.errors):
        summary += f" Showing the first {len(result.errors)}."
    return summary + " No records were imported; fix the file and upload it again."


def import_billing_file(
    db: Session,
    *,
    filename: str,
    content: bytes,
    settings: Settings,
    source: ImportSource = ImportSource.UPLOAD,
    today: date | None = None,
) -> BillingImport:
    """Run the full import. Returns the import (completed or failed); raises on duplicates."""
    sha256 = hashlib.sha256(content).hexdigest()
    existing = db.scalar(
        select(BillingImport).where(
            BillingImport.file_sha256 == sha256,
            BillingImport.status == ImportStatus.COMPLETED,
        )
    )
    if existing is not None:
        raise ConflictError(
            f"This file was already imported as import #{existing.id} ({existing.filename}). "
            "No records were added.",
            details={"import_id": existing.id},
        )

    billing_import = BillingImport(
        filename=filename,
        source=source,
        file_sha256=sha256,
        file_size_bytes=len(content),
        status=ImportStatus.PROCESSING,
    )
    db.add(billing_import)
    db.commit()
    log_context = {"import_id": billing_import.id, "filename": filename}
    logger.info("Billing import started", extra={"context": log_context})

    try:
        result = normalize_csv(
            content,
            max_rows=settings.max_upload_rows,
            max_errors=settings.max_reported_errors,
            today=today,
        )
    except FileValidationError as exc:
        return _fail(
            db, billing_import, str(exc), [{"line": None, "column": None, "message": str(exc)}]
        )
    except Exception:
        logger.exception(
            "Unexpected error while normalizing import", extra={"context": log_context}
        )
        return _fail(
            db, billing_import, "An unexpected error occurred while reading the file.", None
        )

    billing_import.detected_format = result.detected_format
    billing_import.rows_total = result.rows_total
    if not result.is_valid:
        billing_import.rows_invalid = result.invalid_row_count
        return _fail(
            db,
            billing_import,
            _summarize_errors(result),
            [error.as_dict() for error in result.errors],
        )

    try:
        inserted = _insert_records(db, billing_import.id, result)
        billing_import.rows_inserted = inserted
        billing_import.rows_duplicate = len(result.records) - inserted
        billing_import.currencies = sorted({r.currency for r in result.records})
        billing_import.date_start = min(r.usage_date for r in result.records)
        billing_import.date_end = max(r.usage_date for r in result.records)
        billing_import.status = ImportStatus.COMPLETED
        billing_import.completed_at = datetime.now(UTC)
        db.commit()
    except IntegrityError:
        # A concurrent upload of the same file completed first.
        db.rollback()
        return _fail(db, billing_import, "This file was imported concurrently.", None)
    except Exception:
        db.rollback()
        logger.exception("Failed to persist billing records", extra={"context": log_context})
        return _fail(db, billing_import, "The records could not be saved.", None)

    logger.info(
        "Billing import completed",
        extra={
            "context": {
                **log_context,
                "rows_inserted": billing_import.rows_inserted,
                "rows_duplicate": billing_import.rows_duplicate,
            }
        },
    )
    return billing_import


def _insert_records(db: Session, import_id: int, result: NormalizationResult) -> int:
    allocation = AllocationEngine.load(db)
    inserted = 0
    for start in range(0, len(result.records), INSERT_CHUNK_SIZE):
        chunk = result.records[start : start + INSERT_CHUNK_SIZE]
        rows = []
        for record in chunk:
            values = asdict(record)
            values["import_id"] = import_id
            values["project"], values["environment"] = allocation.attribute(values)
            rows.append(values)
        statement = (
            insert(BillingRecord)
            .values(rows)
            .on_conflict_do_nothing(index_elements=[BillingRecord.fingerprint])
            .returning(BillingRecord.id)
        )
        inserted += len(db.execute(statement).all())
    return inserted


def _fail(
    db: Session, billing_import: BillingImport, summary: str, errors: list[dict] | None
) -> BillingImport:
    billing_import.status = ImportStatus.FAILED
    billing_import.error_summary = summary
    billing_import.errors = errors
    billing_import.completed_at = datetime.now(UTC)
    db.commit()
    logger.info(
        "Billing import failed",
        extra={"context": {"import_id": billing_import.id, "reason": summary}},
    )
    return billing_import


def get_import(db: Session, import_id: int) -> BillingImport:
    billing_import = db.get(BillingImport, import_id)
    if billing_import is None:
        raise NotFoundError("Import", import_id)
    return billing_import


def list_imports(db: Session, *, limit: int, offset: int) -> tuple[list[BillingImport], int]:
    total = db.scalar(select(func.count()).select_from(BillingImport)) or 0
    items = db.scalars(
        select(BillingImport).order_by(BillingImport.id.desc()).limit(limit).offset(offset)
    ).all()
    return list(items), total


def delete_import(db: Session, import_id: int) -> None:
    """Delete an import and (via ON DELETE CASCADE) all of its billing records."""
    billing_import = get_import(db, import_id)
    if billing_import.status == ImportStatus.PROCESSING:
        raise ConflictError("The import is still processing and cannot be deleted yet.")
    db.delete(billing_import)
    db.commit()
