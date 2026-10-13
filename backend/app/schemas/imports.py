"""Billing import API schemas."""

from datetime import date, datetime
from typing import Literal

from app.schemas.common import APIModel


class ImportRowError(APIModel):
    line: int | None
    column: str | None
    message: str


class ImportSummary(APIModel):
    id: int
    filename: str
    source: Literal["upload", "sample", "connector"]
    connector_id: int | None
    status: Literal["processing", "completed", "failed"]
    detected_format: str | None
    file_size_bytes: int
    rows_total: int
    rows_inserted: int
    rows_duplicate: int
    rows_invalid: int
    rows_replaced: int
    error_summary: str | None
    currencies: list[str] | None
    date_start: date | None
    date_end: date | None
    created_at: datetime
    completed_at: datetime | None


class ImportDetail(ImportSummary):
    errors: list[ImportRowError] | None


class CanonicalField(APIModel):
    name: str
    required: bool
    description: str
    example: str
    accepted_headers: list[str]


class ImportSchemaResponse(APIModel):
    fields: list[CanonicalField]
    max_upload_bytes: int
    max_rows: int
