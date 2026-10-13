"""OpenAI connector: daily organization costs from the Costs API.

GET https://api.openai.com/v1/organization/costs, grouped by line item and
project, with an Admin API key (sk-admin-...). Line items look like
"gpt-4o-2024-08-06, input" or "evals | gpt-4o-mini, output"; they are split into
service, model and usage type. Project IDs are resolved to project names, which
become the CloudPulse project (allocation rules still apply on top).
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx

from app.services.connectors.base import (
    CanonicalRow,
    ConnectorError,
    FetchResult,
    VerifyResult,
    VerifyStep,
    parse_json,
    send,
    to_decimal,
)

API = "https://api.openai.com/v1/organization"
PAGE_BUCKETS = 30
MAX_PAGES = 100


def _headers(secrets: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {secrets['admin_key']}", "Accept": "application/json"}


def _get(
    client: httpx.Client, secrets: dict[str, str], path: str, params: list[tuple[str, str]], what
) -> dict[str, Any]:
    response = send(
        client,
        lambda: httpx.Request("GET", f"{API}{path}", params=params, headers=_headers(secrets)),
        what=what,
    )
    return parse_json(response, what)


def _unix(day: date) -> int:
    return int(datetime.combine(day, time.min, tzinfo=UTC).timestamp())


def project_names(client: httpx.Client, secrets: dict[str, str]) -> dict[str, str]:
    names: dict[str, str] = {}
    after: str | None = None
    for _ in range(MAX_PAGES):
        params = [("limit", "100"), ("include_archived", "true")]
        if after:
            params.append(("after", after))
        body = _get(client, secrets, "/projects", params, "OpenAI list projects")
        for project in body.get("data", []):
            if project.get("id"):
                names[str(project["id"])] = str(project.get("name") or project["id"])
        after = body.get("last_id")
        if not body.get("has_more") or not after:
            break
    return names


def split_line_item(line_item: str | None) -> tuple[str, str | None, str | None]:
    """'evals | gpt-4o-mini, input' -> ('OpenAI evals', 'gpt-4o-mini', 'input')."""
    if not line_item:
        return "OpenAI API", None, None
    service = "OpenAI API"
    rest = line_item.strip()
    if " | " in rest:
        prefix, rest = (part.strip() for part in rest.split(" | ", 1))
        service = f"OpenAI {prefix}"
    if ", " in rest:
        model, usage_type = (part.strip() for part in rest.rsplit(", ", 1))
        return service, model or None, usage_type or None
    # No model (e.g. "assistants api | file search"): the remainder is the usage type.
    return service, None, rest or None


def fetch(
    client: httpx.Client,
    secrets: dict[str, str],
    config: dict[str, Any],
    *,
    start: date,
    end: date,
) -> FetchResult:
    names = project_names(client, secrets) if config.get("map_projects", True) else {}
    rows: list[CanonicalRow] = []
    page: str | None = None
    for _ in range(MAX_PAGES):
        params = [
            ("start_time", str(_unix(start))),
            ("end_time", str(_unix(end + timedelta(days=1)))),
            ("bucket_width", "1d"),
            ("group_by", "line_item"),
            ("group_by", "project_id"),
            ("limit", str(PAGE_BUCKETS)),
        ]
        if page:
            params.append(("page", page))
        body = _get(client, secrets, "/costs", params, "OpenAI Costs API")
        for bucket in body.get("data", []):
            day = datetime.fromtimestamp(int(bucket["start_time"]), UTC).date()
            for result in bucket.get("results", []):
                row = _result_row(day, result, names)
                if row is not None:
                    rows.append(row)
        page = body.get("next_page")
        if not body.get("has_more") or not page:
            break
    else:
        raise ConnectorError("OpenAI Costs API returned more pages than expected.")
    return FetchResult(
        rows=rows,
        ranges=[(start, end)],
        filename=f"openai-costs-{start.isoformat()}-to-{end.isoformat()}.csv",
        detected_format="openai_costs",
    )


def _result_row(day: date, result: dict[str, Any], names: dict[str, str]) -> CanonicalRow | None:
    amount = result.get("amount") or {}
    cost = to_decimal(amount.get("value", 0), "OpenAI cost amount")
    if cost == 0:
        return None
    line_item = result.get("line_item")
    service, model, usage_type = split_line_item(line_item)
    project_id = result.get("project_id")
    row = CanonicalRow(
        usage_date=day,
        provider="openai",
        service=service[:255],
        cost=cost,
        currency=str(amount.get("currency") or "usd").upper(),
        account_id=str(project_id)[:128] if project_id else None,
        model=model[:128] if model else None,
        usage_type=usage_type[:255] if usage_type else None,
        project=names.get(str(project_id)) if project_id else None,
    )
    if line_item:
        row.extra["line_item"] = str(line_item)
    return row


def verify(client: httpx.Client, secrets: dict[str, str], config: dict[str, Any]) -> VerifyResult:
    steps: list[VerifyStep] = []
    try:
        body = _get(client, secrets, "/projects", [("limit", "1")], "OpenAI list projects")
    except ConnectorError as exc:
        steps.append(VerifyStep("authenticate", "Authenticate the admin key", "failed", str(exc)))
        steps.append(
            VerifyStep("permission", "Read organization costs", "skipped", "Not attempted.")
        )
        return VerifyResult(False, None, steps)
    first = (body.get("data") or [{}])[0]
    steps.append(
        VerifyStep(
            "authenticate",
            "Authenticate the admin key",
            "ok",
            "Admin key accepted"
            + (f"; first project: {first.get('name')}." if first.get("name") else "."),
        )
    )
    today = datetime.now(UTC).date()
    try:
        costs = _get(
            client,
            secrets,
            "/costs",
            [
                ("start_time", str(_unix(today - timedelta(days=1)))),
                ("bucket_width", "1d"),
                ("limit", "1"),
            ],
            "OpenAI Costs API",
        )
    except ConnectorError as exc:
        steps.append(VerifyStep("permission", "Read organization costs", "failed", str(exc)))
        return VerifyResult(False, None, steps)
    steps.append(
        VerifyStep("permission", "Read organization costs", "ok", "The Costs API is readable.")
    )
    org = next(
        (
            result.get("organization_id")
            for bucket in costs.get("data", [])
            for result in bucket.get("results", [])
            if result.get("organization_id")
        ),
        None,
    )
    return VerifyResult(True, f"OpenAI organization {org}" if org else "OpenAI organization", steps)
