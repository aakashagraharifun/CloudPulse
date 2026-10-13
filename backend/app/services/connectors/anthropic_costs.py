"""Anthropic connector: daily Claude API costs from the Usage & Cost Admin API.

GET https://api.anthropic.com/v1/organizations/cost_report with an Admin API key
(sk-ant-admin...), grouped by workspace and description. Amounts are decimal
strings in cents ("123.45" = USD 1.2345); grouping by description adds the
structured `model`, `cost_type`, `token_type` and `service_tier` fields.
Workspace IDs resolve to workspace names, which become the CloudPulse project;
the default workspace has a null ID. Priority Tier costs are not part of this
endpoint (an Anthropic limitation).
"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
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

API = "https://api.anthropic.com/v1/organizations"
ANTHROPIC_VERSION = "2023-06-01"
PAGE_BUCKETS = 31  # the cost report's maximum
MAX_PAGES = 100
DEFAULT_WORKSPACE = "default"
SERVICE_BY_COST_TYPE = {
    "tokens": "Claude API",
    "web_search": "Claude API web search",
    "code_execution": "Claude API code execution",
    "session_usage": "Claude Managed Agents",
}


def _headers(secrets: dict[str, str]) -> dict[str, str]:
    return {
        "x-api-key": secrets["admin_key"],
        "anthropic-version": ANTHROPIC_VERSION,
        "Accept": "application/json",
    }


def _get(
    client: httpx.Client, secrets: dict[str, str], path: str, params: list[tuple[str, str]], what
) -> dict[str, Any]:
    response = send(
        client,
        lambda: httpx.Request("GET", f"{API}{path}", params=params, headers=_headers(secrets)),
        what=what,
    )
    return parse_json(response, what)


def _rfc3339(day: date) -> str:
    return datetime.combine(day, time.min, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def organization(client: httpx.Client, secrets: dict[str, str]) -> dict[str, Any]:
    return _get(client, secrets, "/me", [], "Anthropic organization lookup")


def workspace_names(client: httpx.Client, secrets: dict[str, str]) -> dict[str, str]:
    names: dict[str, str] = {}
    after: str | None = None
    for _ in range(MAX_PAGES):
        params = [("limit", "100"), ("include_archived", "true")]
        if after:
            params.append(("after_id", after))
        body = _get(client, secrets, "/workspaces", params, "Anthropic list workspaces")
        for workspace in body.get("data", []):
            if workspace.get("id"):
                names[str(workspace["id"])] = str(workspace.get("name") or workspace["id"])
        after = body.get("last_id")
        if not body.get("has_more") or not after:
            break
    return names


def fetch(
    client: httpx.Client,
    secrets: dict[str, str],
    config: dict[str, Any],
    *,
    start: date,
    end: date,
) -> FetchResult:
    names: dict[str, str] = {}
    notes: list[str] = []
    if config.get("map_workspaces", True):
        try:
            names = workspace_names(client, secrets)
        except ConnectorError as exc:
            # Costs are still correct without names; say why projects show IDs.
            notes.append(f"Workspace names unavailable ({exc}); workspace IDs are used instead.")
    rows: list[CanonicalRow] = []
    page: str | None = None
    for _ in range(MAX_PAGES):
        params = [
            ("starting_at", _rfc3339(start)),
            ("ending_at", _rfc3339(end + timedelta(days=1))),
            ("bucket_width", "1d"),
            ("group_by[]", "workspace_id"),
            ("group_by[]", "description"),
            ("limit", str(PAGE_BUCKETS)),
        ]
        if page:
            params.append(("page", page))
        body = _get(client, secrets, "/cost_report", params, "Anthropic cost report")
        for bucket in body.get("data", []):
            day = date.fromisoformat(str(bucket["starting_at"])[:10])
            for result in bucket.get("results", []):
                row = _result_row(day, result, names, bool(config.get("map_workspaces", True)))
                if row is not None:
                    rows.append(row)
        page = body.get("next_page")
        if not body.get("has_more") or not page:
            break
    else:
        raise ConnectorError("Anthropic cost report returned more pages than expected.")
    return FetchResult(
        rows=rows,
        ranges=[(start, end)],
        filename=f"anthropic-costs-{start.isoformat()}-to-{end.isoformat()}.csv",
        detected_format="anthropic_cost_report",
        notes=notes,
    )


def _result_row(
    day: date, result: dict[str, Any], names: dict[str, str], map_workspaces: bool
) -> CanonicalRow | None:
    cents = to_decimal(result.get("amount", "0"), "Anthropic cost amount")
    if cents == 0:
        return None
    workspace_id = result.get("workspace_id") or None
    cost_type = result.get("cost_type")
    if map_workspaces:
        project = names.get(workspace_id, workspace_id) if workspace_id else "Default workspace"
    else:
        project = None
    row = CanonicalRow(
        usage_date=day,
        provider="anthropic",
        service=SERVICE_BY_COST_TYPE.get(str(cost_type), "Claude API"),
        cost=cents / Decimal(100),
        currency=str(result.get("currency") or "USD").upper(),
        account_id=(workspace_id or DEFAULT_WORKSPACE)[:128],
        region=result.get("inference_geo") or None,
        model=result.get("model") or None,
        usage_type=(result.get("token_type") or cost_type or result.get("description") or None),
        usage_unit="tokens" if cost_type == "tokens" else None,
        project=project[:128] if project else None,
    )
    for key in ("description", "service_tier", "context_window"):
        if result.get(key):
            row.extra[key] = str(result[key])
    return row


def verify(client: httpx.Client, secrets: dict[str, str], config: dict[str, Any]) -> VerifyResult:
    steps: list[VerifyStep] = []
    try:
        org = organization(client, secrets)
    except ConnectorError as exc:
        steps.append(
            VerifyStep("authenticate", "Authenticate the Admin API key", "failed", str(exc))
        )
        steps.append(VerifyStep("permission", "Read the cost report", "skipped", "Not attempted."))
        return VerifyResult(False, None, steps)
    org_name = str(org.get("name") or org.get("id") or "your organization")
    steps.append(
        VerifyStep(
            "authenticate",
            "Authenticate the Admin API key",
            "ok",
            f"Authorized for organization {org_name}.",
        )
    )
    today = datetime.now(UTC).date()
    try:
        _get(
            client,
            secrets,
            "/cost_report",
            [
                ("starting_at", _rfc3339(today - timedelta(days=1))),
                ("ending_at", _rfc3339(today)),
                ("limit", "1"),
            ],
            "Anthropic cost report",
        )
    except ConnectorError as exc:
        steps.append(VerifyStep("permission", "Read the cost report", "failed", str(exc)))
        return VerifyResult(False, org_name, steps)
    steps.append(
        VerifyStep(
            "permission", "Read the cost report", "ok", "Usage & Cost Admin API is readable."
        )
    )
    return VerifyResult(True, org_name, steps)
