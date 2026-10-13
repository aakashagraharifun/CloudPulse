"""Building blocks shared by every live billing connector.

A connector only *fetches*: it turns a provider's billing API response into
`CanonicalRow`s. The rows are written as a canonical CloudPulse CSV and go
through the same validation, normalization, allocation and duplicate handling
as an uploaded file (see `app.services.connectors.service`).
"""

import csv
import io
import json
import logging
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal

import httpx

from app.services.normalization.schema import CANONICAL_FIELDS, normalize_header

logger = logging.getLogger(__name__)

USER_AGENT = "CloudPulse/0.1 (cloud cost anomaly detection)"
CSV_COLUMNS = [spec.name for spec in CANONICAL_FIELDS]
_RESERVED_HEADERS = {alias for spec in CANONICAL_FIELDS for alias in spec.aliases}
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 3
MAX_RETRY_DELAY_SECONDS = 10.0
# Patched in tests so retries do not wait.
sleep: Callable[[float], None] = time.sleep


class ConnectorError(Exception):
    """The provider could not be reached, rejected the request, or returned bad data."""


@dataclass
class CanonicalRow:
    usage_date: date
    provider: str
    service: str
    cost: Decimal
    currency: str = "USD"
    account_id: str | None = None
    resource_id: str | None = None
    region: str | None = None
    usage_type: str | None = None
    model: str | None = None
    usage_quantity: Decimal | None = None
    usage_unit: str | None = None
    project: str | None = None
    environment: str | None = None
    # Kept as extra attributes on the record, e.g. {"description": "..."}.
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class FetchResult:
    rows: list[CanonicalRow]
    # Inclusive date ranges the data is authoritative for (replaced on import).
    ranges: list[tuple[date, date]]
    filename: str
    detected_format: str
    notes: list[str] = field(default_factory=list)


@dataclass
class VerifyStep:
    key: str
    label: str
    status: Literal["ok", "failed", "skipped"]
    detail: str


@dataclass
class VerifyResult:
    ok: bool
    identity: str | None
    steps: list[VerifyStep]


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def rows_to_csv(rows: list[CanonicalRow]) -> bytes:
    """Deterministic canonical CSV (sorted rows) so identical data gives identical bytes."""
    extra_columns = sorted({key for row in rows for key in row.extra})
    for name in extra_columns:
        if normalize_header(name) in _RESERVED_HEADERS:
            raise ValueError(f"Extra column {name!r} would be read as a canonical field.")
    header = CSV_COLUMNS + extra_columns
    lines = []
    for row in rows:
        values = {
            "usage_date": row.usage_date,
            "provider": row.provider,
            "account_id": row.account_id,
            "service": row.service,
            "resource_id": row.resource_id,
            "region": row.region,
            "usage_type": row.usage_type,
            "model": row.model,
            "usage_quantity": row.usage_quantity,
            "usage_unit": row.usage_unit,
            "currency": row.currency,
            "cost": row.cost,
            "project": row.project,
            "environment": row.environment,
        }
        lines.append(
            [_cell(values[name]) for name in CSV_COLUMNS]
            + [_cell(row.extra.get(name)) for name in extra_columns]
        )
    lines.sort()
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(lines)
    return buffer.getvalue().encode("utf-8")


def upstream_message(response: httpx.Response) -> str:
    """The provider's own error text (JSON or AWS XML), shortened for display."""
    text = response.text[:4000]
    message = ""
    try:
        body = json.loads(text)
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or error.get("type") or "")
            elif isinstance(error, str):
                message = error
            message = message or str(body.get("message") or body.get("Message") or "")
    except ValueError:
        try:
            root = ET.fromstring(text)
            found = [el.text for el in root.iter() if el.tag.split("}")[-1] == "Message"]
            message = (found[0] or "") if found else ""
        except ET.ParseError:
            message = ""
    message = " ".join(message.split()).rstrip(".")
    return message[:300]


def describe_failure(what: str, response: httpx.Response) -> str:
    detail = upstream_message(response)
    status = response.status_code
    if status in (401, 403):
        reason = "the credentials were rejected or lack permission"
    elif status == 404:
        reason = "the resource was not found"
    elif status == 429:
        reason = "the provider is rate limiting requests; try again later"
    elif status >= 500:
        reason = "the provider had an internal error; try again later"
    else:
        reason = "the request was rejected"
    return f"{what}: {reason} (HTTP {status})" + (f" — {detail}" if detail else "") + "."


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    header = response.headers.get("retry-after", "")
    try:
        delay = float(header)
    except ValueError:
        delay = 0.5 * (2**attempt)
    return max(0.0, min(delay, MAX_RETRY_DELAY_SECONDS))


def send(
    client: httpx.Client,
    build: Callable[[], httpx.Request],
    *,
    what: str,
    failure: Callable[[httpx.Response], ConnectorError] | None = None,
) -> httpx.Response:
    """Send with retries on 429/5xx and transport errors; raise ConnectorError otherwise.

    `build` is called per attempt so signed requests (AWS SigV4) get a fresh timestamp.
    `failure` can turn an error response into a more specific ConnectorError.
    """
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = client.send(build())
        except httpx.TimeoutException as exc:
            if attempt + 1 < MAX_ATTEMPTS:
                continue
            raise ConnectorError(f"{what}: the provider did not respond in time.") from exc
        except httpx.TransportError as exc:
            if attempt + 1 < MAX_ATTEMPTS:
                continue
            raise ConnectorError(f"{what}: could not connect to the provider ({exc}).") from exc
        if response.status_code in RETRY_STATUSES and attempt + 1 < MAX_ATTEMPTS:
            sleep(_retry_delay(response, attempt))
            continue
        if response.is_success:
            return response
        if failure is not None:
            raise failure(response)
        raise ConnectorError(describe_failure(what, response))
    raise AssertionError("unreachable")  # pragma: no cover


def parse_json(response: httpx.Response, what: str) -> dict[str, Any]:
    """JSON body with numbers parsed as Decimal (money must never pass through float)."""
    try:
        body = json.loads(response.content, parse_float=Decimal)
    except ValueError as exc:
        raise ConnectorError(f"{what}: the provider returned a response that is not JSON.") from exc
    if not isinstance(body, dict):
        raise ConnectorError(f"{what}: unexpected response shape.")
    return body


def to_decimal(value: Any, what: str) -> Decimal:
    try:
        return Decimal(str(value))
    except ArithmeticError as exc:
        raise ConnectorError(f"{what}: {value!r} is not a number.") from exc


def build_http_client(timeout: float) -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0)),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=False,
    )
