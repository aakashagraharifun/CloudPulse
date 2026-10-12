"""Parse and validate a billing CSV into canonical records.

Validation is all-or-nothing: if any row is invalid, the caller rejects the
whole file and reports every problem (capped at `max_errors` entries), so no
record is ever silently discarded.

Line numbers in error messages are physical line numbers in the file (the
header is line 1), so users can find the problem in a text editor or Excel.
"""

import csv
import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any

import pandas as pd

from app.services.normalization.schema import CANONICAL_FIELDS, FIELDS_BY_NAME, normalize_header

EIGHT_PLACES = Decimal("0.00000001")
MAX_ABS_COST = Decimal("1000000000")  # 1e9 per line item
MAX_ABS_QUANTITY = Decimal("1000000000000000")  # 1e15
MIN_USAGE_DATE = date(2000, 1, 1)
MAX_EXTRA_ATTRIBUTES = 50
MAX_EXTRA_VALUE_LENGTH = 256

_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_ISO_DATE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"([T ]\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?(Z|[+-]\d{2}(:?\d{2})?)?)?$"
)
_PROVIDER = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


class FileValidationError(Exception):
    """The file as a whole cannot be processed (encoding, structure, headers)."""


@dataclass(frozen=True)
class RowError:
    line: int | None
    column: str | None
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {"line": self.line, "column": self.column, "message": self.message}


@dataclass
class NormalizedRecord:
    usage_date: date
    provider: str
    account_id: str | None
    service: str
    resource_id: str | None
    region: str | None
    usage_type: str | None
    usage_quantity: Decimal | None
    usage_unit: str | None
    currency: str
    cost: Decimal
    project_tag: str | None
    environment_tag: str | None
    source_row_number: int
    extra_attributes: dict[str, str] | None
    fingerprint: str = ""


@dataclass
class NormalizationResult:
    detected_format: str | None = None
    rows_total: int = 0
    invalid_row_count: int = 0
    error_count: int = 0
    records: list[NormalizedRecord] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.error_count == 0


def _preview(value: str, limit: int = 60) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def decode_csv_bytes(content: bytes) -> str:
    if not content.strip():
        raise FileValidationError("The file is empty.")
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise FileValidationError(
            "The file is UTF-16 encoded. Re-save it as 'CSV UTF-8 (Comma delimited)'."
        )
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FileValidationError(
            f"The file is not valid UTF-8 (invalid byte at offset {exc.start}). "
            "Re-save it as 'CSV UTF-8 (Comma delimited)'."
        ) from exc
    if "\x00" in text:
        raise FileValidationError("The file contains NUL bytes; it does not look like a CSV file.")
    return text


def parse_usage_date(raw: str, today: date) -> date:
    if not _ISO_DATE.match(raw):
        raise ValueError(
            f"'{_preview(raw)}' is not an ISO 8601 date. Use YYYY-MM-DD (e.g. 2026-01-31) "
            "or a timestamp such as 2026-01-31T00:00:00Z."
        )
    try:
        if len(raw) == 10:
            value = date.fromisoformat(raw)
        else:
            parsed = datetime.fromisoformat(raw.replace(" ", "T", 1))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(UTC)
            value = parsed.date()
    except ValueError as exc:
        raise ValueError(f"'{_preview(raw)}' is not a valid calendar date.") from exc
    if value < MIN_USAGE_DATE:
        raise ValueError(f"{value.isoformat()} is before {MIN_USAGE_DATE.isoformat()}.")
    if value > today + timedelta(days=1):
        raise ValueError(f"{value.isoformat()} is in the future.")
    return value


def parse_decimal(raw: str, *, max_abs: Decimal, allow_negative: bool) -> Decimal:
    if "," in raw:
        raise ValueError(
            f"'{_preview(raw)}' contains a comma. Use '.' as the decimal separator "
            "and no thousands separators."
        )
    if not _NUMBER.match(raw):
        raise ValueError(f"'{_preview(raw)}' is not a number.")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:  # pragma: no cover - guarded by the regex
        raise ValueError(f"'{_preview(raw)}' is not a number.") from exc
    if abs(value) >= max_abs:
        raise ValueError(f"{_preview(raw)} is outside the supported range (±{max_abs}).")
    if value < 0 and not allow_negative:
        raise ValueError(f"{_preview(raw)} must not be negative.")
    quantized = value.quantize(EIGHT_PLACES, rounding=ROUND_HALF_EVEN)
    return quantized + Decimal(0)  # normalizes -0E-8 to 0E-8


def _optional_text(
    values: dict[str, Any], name: str, row_errors: list[tuple[str, str]]
) -> str | None:
    """Return a trimmed text value, None when empty; record a length violation."""
    value = values.get(name)
    if value is None or value == "":
        return None
    limit = FIELDS_BY_NAME[name].max_length
    if limit is not None and len(value) > limit:
        row_errors.append((name, f"Value is longer than {limit} characters."))
        return None
    return value


def _fingerprint(record: NormalizedRecord, occurrence: int) -> str:
    parts = [
        record.usage_date.isoformat(),
        record.provider,
        record.account_id or "",
        record.service,
        record.resource_id or "",
        record.region or "",
        record.usage_type or "",
        "" if record.usage_quantity is None else format(record.usage_quantity, "f"),
        record.usage_unit or "",
        record.currency,
        format(record.cost, "f"),
        record.project_tag or "",
        record.environment_tag or "",
        str(occurrence),
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _map_headers(header: list[str]) -> tuple[dict[str, int], dict[int, str], str]:
    """Return (canonical field -> column index, extra column index -> header, format)."""
    normalized = [normalize_header(h) for h in header]
    for index, name in enumerate(normalized):
        if not name:
            raise FileValidationError(f"Column {index + 1} has an empty header name.")
    duplicates = sorted(name for name, count in Counter(normalized).items() if count > 1)
    if duplicates:
        raise FileValidationError(
            "Duplicate column names (after normalizing case and punctuation): "
            + ", ".join(duplicates)
        )

    position = {name: index for index, name in enumerate(normalized)}
    mapping: dict[str, int] = {}
    for spec in CANONICAL_FIELDS:
        for alias in spec.aliases:
            if alias in position:
                mapping[spec.name] = position[alias]
                break

    is_cur = any(n.startswith(("lineitem_", "line_item_")) for n in normalized)
    detected_format = "aws_cur" if is_cur else "cloudpulse"

    missing = [
        spec
        for spec in CANONICAL_FIELDS
        if spec.required and spec.name not in mapping and not (spec.name == "provider" and is_cur)
    ]
    if missing:
        detail = "; ".join(f"{spec.name} (accepted: {', '.join(spec.aliases)})" for spec in missing)
        raise FileValidationError(f"Missing required column(s): {detail}.")

    used = set(mapping.values())
    extras = {index: header[index].strip() for index in range(len(header)) if index not in used}
    return mapping, extras, detected_format


def normalize_csv(
    content: bytes,
    *,
    max_rows: int,
    max_errors: int,
    today: date | None = None,
) -> NormalizationResult:
    """Validate and normalize a CSV file. Raises FileValidationError for file-level problems."""
    today = today or datetime.now(UTC).date()
    text = decode_csv_bytes(content)
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    result = NormalizationResult()

    def add_error(line: int | None, column: str | None, message: str) -> None:
        result.error_count += 1
        if len(result.errors) < max_errors:
            result.errors.append(RowError(line, column, message))

    try:
        header = next(reader)
    except StopIteration as exc:
        raise FileValidationError("The file has no header row.") from exc
    except csv.Error as exc:
        raise FileValidationError(f"Could not parse the header row: {exc}.") from exc

    mapping, extras, result.detected_format = _map_headers(header)

    lines: list[int] = []
    rows: list[list[str]] = []
    try:
        for row in reader:
            if not row or all(not cell.strip() for cell in row):
                continue  # blank lines are not records
            result.rows_total += 1
            if result.rows_total > max_rows:
                raise FileValidationError(
                    f"The file has more than {max_rows:,} data rows. Split it into smaller files."
                )
            if len(row) != len(header):
                add_error(
                    reader.line_num,
                    None,
                    f"Expected {len(header)} columns but found {len(row)}.",
                )
                result.invalid_row_count += 1
                continue
            lines.append(reader.line_num)
            rows.append(row)
    except csv.Error as exc:
        raise FileValidationError(f"CSV syntax error on line {reader.line_num}: {exc}.") from exc

    if result.rows_total == 0:
        raise FileValidationError("The file has a header row but no data rows.")

    # Pandas handles the column-wise cleanup (trimming, case normalization).
    frame = pd.DataFrame(
        {name: [row[index] for row in rows] for name, index in mapping.items()}, dtype=object
    )
    for name in mapping:
        frame[name] = frame[name].str.strip()
    if "provider" in frame:
        frame["provider"] = frame["provider"].str.lower()
    else:
        frame["provider"] = "aws"  # only reachable for AWS CUR files

    date_cache: dict[str, date | str] = {}
    occurrences: Counter[str] = Counter()
    records: list[NormalizedRecord] = []

    for position, values in enumerate(frame.to_dict("records")):
        line = lines[position]
        row_errors: list[tuple[str, str]] = []

        for name in ("usage_date", "provider", "service", "currency", "cost"):
            if not values.get(name):
                row_errors.append((name, "Value is required."))

        usage_date: date | None = None
        raw_date = values.get("usage_date") or ""
        if raw_date:
            cached = date_cache.get(raw_date)
            if cached is None:
                try:
                    cached = parse_usage_date(raw_date, today)
                except ValueError as exc:
                    cached = str(exc)
                date_cache[raw_date] = cached
            if isinstance(cached, date):
                usage_date = cached
            else:
                row_errors.append(("usage_date", cached))

        provider = values.get("provider") or ""
        if provider and not _PROVIDER.match(provider):
            row_errors.append(
                ("provider", f"'{_preview(provider)}' must be lower-case letters, digits, - or _.")
            )
        currency = (values.get("currency") or "").upper()
        if currency and not _CURRENCY.match(currency):
            row_errors.append(
                (
                    "currency",
                    f"'{_preview(values['currency'])}' is not a 3-letter ISO 4217 code (e.g. USD).",
                )
            )

        cost: Decimal | None = None
        if values.get("cost"):
            try:
                cost = parse_decimal(values["cost"], max_abs=MAX_ABS_COST, allow_negative=True)
            except ValueError as exc:
                row_errors.append(("cost", str(exc)))

        quantity: Decimal | None = None
        if values.get("usage_quantity"):
            try:
                quantity = parse_decimal(
                    values["usage_quantity"], max_abs=MAX_ABS_QUANTITY, allow_negative=False
                )
            except ValueError as exc:
                row_errors.append(("usage_quantity", str(exc)))

        service = _optional_text(values, "service", row_errors)
        account_id = _optional_text(values, "account_id", row_errors)
        resource_id = _optional_text(values, "resource_id", row_errors)
        region = _optional_text(values, "region", row_errors)
        usage_type = _optional_text(values, "usage_type", row_errors)
        usage_unit = _optional_text(values, "usage_unit", row_errors)
        project = _optional_text(values, "project", row_errors)
        environment = _optional_text(values, "environment", row_errors)

        if row_errors:
            result.invalid_row_count += 1
            for column, message in row_errors:
                add_error(line, column, message)
            continue

        assert usage_date is not None and cost is not None and service is not None
        source_row = rows[position]
        extra = {
            name: source_row[index].strip()[:MAX_EXTRA_VALUE_LENGTH]
            for index, name in extras.items()
            if source_row[index].strip()
        }
        record = NormalizedRecord(
            usage_date=usage_date,
            provider=provider,
            account_id=account_id,
            service=service,
            resource_id=resource_id,
            region=region,
            usage_type=usage_type,
            usage_quantity=quantity,
            usage_unit=usage_unit,
            currency=currency,
            cost=cost,
            project_tag=project,
            environment_tag=environment,
            source_row_number=line,
            extra_attributes=dict(list(extra.items())[:MAX_EXTRA_ATTRIBUTES]) or None,
        )
        # Identical rows within one file are legitimate (e.g. split line items); the
        # occurrence index keeps them distinct while re-imports still collide.
        base_key = _fingerprint(record, 0)
        record.fingerprint = _fingerprint(record, occurrences[base_key])
        occurrences[base_key] += 1
        records.append(record)

    result.errors.sort(key=lambda error: error.line or 0)
    if result.error_count == 0:
        result.records = records
    return result
