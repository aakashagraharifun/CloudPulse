"""AWS Cost Explorer connector: daily unblended cost via ce:GetCostAndUsage.

Cost Explorer is the quickest AWS source to set up (no export to configure) but
is pre-aggregated: one row per day x service x one more dimension. Every API
request is billed by AWS (USD 0.01 at the time of writing), so a sync pages
through as few requests as possible. Recent days are estimates until AWS
finalizes them; each sync replaces its whole window, so they converge.

Required IAM permission: ce:GetCostAndUsage (and sts:AssumeRole when a role is used).
"""

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from app.services.connectors.aws import (
    get_caller_identity,
    resolve_credentials,
    signed_request_builder,
)
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

CE_HOST = "ce.us-east-1.amazonaws.com"
MAX_PAGES = 200
GROUP_DIMENSIONS = {"LINKED_ACCOUNT", "REGION", "USAGE_TYPE"}


def _call(client: httpx.Client, credentials, payload: dict[str, Any]) -> dict[str, Any]:
    response = send(
        client,
        signed_request_builder(
            method="POST",
            host=CE_HOST,
            headers={
                "content-type": "application/x-amz-json-1.1",
                "x-amz-target": "AWSInsightsIndexService.GetCostAndUsage",
            },
            body=json.dumps(payload).encode("utf-8"),
            region="us-east-1",
            service="ce",
            credentials=credentials,
        ),
        what="AWS Cost Explorer GetCostAndUsage",
    )
    return parse_json(response, "AWS Cost Explorer")


def _secondary_group(config: dict[str, Any]) -> dict[str, str]:
    group_by = config.get("group_by", "LINKED_ACCOUNT")
    if group_by == "TAG":
        return {"Type": "TAG", "Key": str(config["tag_key"])}
    if group_by not in GROUP_DIMENSIONS:
        raise ConnectorError(f"Unsupported Cost Explorer grouping {group_by!r}.")
    return {"Type": "DIMENSION", "Key": group_by}


def fetch(
    client: httpx.Client,
    secrets: dict[str, str],
    config: dict[str, Any],
    *,
    start: date,
    end: date,
) -> FetchResult:
    """Daily costs for start..end (inclusive)."""
    credentials = resolve_credentials(client, secrets, config)
    secondary = _secondary_group(config)
    payload: dict[str, Any] = {
        "TimePeriod": {"Start": start.isoformat(), "End": (end + timedelta(days=1)).isoformat()},
        "Granularity": "DAILY",
        "Metrics": ["UnblendedCost"],
        "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}, secondary],
    }
    rows: list[CanonicalRow] = []
    estimated_days: set[str] = set()
    for _ in range(MAX_PAGES):
        body = _call(client, credentials, payload)
        for period in body.get("ResultsByTime", []):
            day = date.fromisoformat(period["TimePeriod"]["Start"])
            if period.get("Estimated"):
                estimated_days.add(day.isoformat())
            for group in period.get("Groups", []):
                rows.extend(_group_rows(day, group, secondary))
        token = body.get("NextPageToken")
        if not token:
            break
        payload["NextPageToken"] = token
    else:
        raise ConnectorError("AWS Cost Explorer returned more pages than expected.")

    notes = []
    if estimated_days:
        notes.append(f"{len(estimated_days)} day(s) are AWS estimates and will be refreshed.")
    return FetchResult(
        rows=rows,
        ranges=[(start, end)],
        filename=f"aws-cost-explorer-{start.isoformat()}-to-{end.isoformat()}.csv",
        detected_format="aws_cost_explorer",
        notes=notes,
    )


def _group_rows(day: date, group: dict[str, Any], secondary: dict[str, str]) -> list[CanonicalRow]:
    keys = group.get("Keys") or []
    metric = (group.get("Metrics") or {}).get("UnblendedCost") or {}
    amount = to_decimal(metric.get("Amount", "0"), "Cost Explorer amount")
    if amount == 0 or len(keys) != 2:
        return []
    service, value = str(keys[0]), str(keys[1])
    row = CanonicalRow(
        usage_date=day,
        provider="aws",
        service=service[:255],
        cost=amount,
        currency=str(metric.get("Unit") or "USD").upper(),
    )
    if secondary["Type"] == "TAG":
        # Tag groups come back as "<key>$<value>"; an empty value means untagged.
        _, _, tag_value = value.partition("$")
        row.project = tag_value[:128] or None
    elif secondary["Key"] == "LINKED_ACCOUNT":
        row.account_id = value[:128]
    elif secondary["Key"] == "REGION":
        row.region = value[:64] if value not in ("", "NoRegion") else None
    else:
        row.usage_type = value[:255]
    return [row]


def verify(client: httpx.Client, secrets: dict[str, str], config: dict[str, Any]) -> VerifyResult:
    steps: list[VerifyStep] = []
    try:
        credentials = resolve_credentials(client, secrets, config)
        identity = get_caller_identity(client, credentials)
    except ConnectorError as exc:
        steps.append(VerifyStep("authenticate", "Authenticate with AWS STS", "failed", str(exc)))
        steps.append(VerifyStep("permission", "Read Cost Explorer", "skipped", "Not attempted."))
        return VerifyResult(False, None, steps)
    via_role = " (assumed role)" if config.get("role_arn") else ""
    steps.append(
        VerifyStep(
            "authenticate",
            "Authenticate with AWS STS",
            "ok",
            f"Signed in as {identity['arn']}{via_role}.",
        )
    )
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    try:
        _call(
            client,
            credentials,
            {
                "TimePeriod": {
                    "Start": yesterday.isoformat(),
                    "End": (yesterday + timedelta(days=1)).isoformat(),
                },
                "Granularity": "DAILY",
                "Metrics": ["UnblendedCost"],
            },
        )
    except ConnectorError as exc:
        steps.append(VerifyStep("permission", "Read Cost Explorer", "failed", str(exc)))
        return VerifyResult(False, identity["arn"], steps)
    steps.append(
        VerifyStep(
            "permission",
            "Read Cost Explorer",
            "ok",
            "ce:GetCostAndUsage is allowed (1 request, billed by AWS at USD 0.01).",
        )
    )
    return VerifyResult(True, f"AWS account {identity['account']}", steps)
