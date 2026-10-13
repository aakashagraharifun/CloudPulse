"""Sandbox connectors: the full connect flow without a provider account.

An admin "authorizes" a simulated provider in a mock consent window, which
issues a short-lived sandbox token. A connector created with it behaves like a
real one (verify, schedule, sync) but talks to a deterministic simulated API:
its syncs fetch and validate realistic cost lines and report what *would* be
imported, without writing billing data, so demo connectors never mix fake
costs into real analytics.

Tokens are Fernet tokens (encrypted and authenticated with
CONNECTOR_ENCRYPTION_KEY, timestamped), so the API can check it issued one,
for which connector kind, and that it is fresh, without storing it.
"""

import json
import random
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from cryptography.fernet import InvalidToken

from app.core.config import Settings
from app.core.crypto import cipher
from app.models import ConnectorKind
from app.services.connectors.base import (
    CanonicalRow,
    ConnectorError,
    FetchResult,
    VerifyResult,
    VerifyStep,
)

TOKEN_PREFIX = "cpsbx_"
TOKEN_TTL_SECONDS = 15 * 60
SANDBOX_ACCOUNT = "123456789012"

IDENTITY = {
    ConnectorKind.ANTHROPIC_COSTS: "Acme AI (sandbox organization)",
    ConnectorKind.OPENAI_COSTS: "Acme AI (sandbox organization)",
    ConnectorKind.AWS_COST_EXPLORER: f"AWS account {SANDBOX_ACCOUNT} (sandbox)",
    ConnectorKind.AWS_CUR_S3: f"AWS account {SANDBOX_ACCOUNT} (sandbox)",
}


class InvalidSandboxToken(ValueError):
    pass


def issue_token(settings: Settings, kind: ConnectorKind) -> str:
    payload = json.dumps({"kind": kind.value, "purpose": "cloudpulse-sandbox"}).encode()
    return TOKEN_PREFIX + cipher(settings).encrypt(payload).decode("ascii")


def check_token(settings: Settings, token: str, kind: ConnectorKind, *, fresh: bool) -> None:
    """Raise InvalidSandboxToken unless CloudPulse issued `token` for `kind`.

    `fresh` enforces the TTL (when the token is first used); stored tokens of
    saved connectors stay valid.
    """
    if not token.startswith(TOKEN_PREFIX):
        raise InvalidSandboxToken("This is not a CloudPulse sandbox token.")
    try:
        raw = cipher(settings).decrypt(
            token[len(TOKEN_PREFIX) :].encode("ascii"),
            ttl=TOKEN_TTL_SECONDS if fresh else None,
        )
        payload = json.loads(raw)
    except (InvalidToken, ValueError, UnicodeEncodeError) as exc:
        raise InvalidSandboxToken(
            "The sandbox authorization is invalid or expired; authorize again."
        ) from exc
    if payload.get("purpose") != "cloudpulse-sandbox" or payload.get("kind") != kind.value:
        raise InvalidSandboxToken("The sandbox authorization was issued for another connector.")


def verify(kind: ConnectorKind) -> VerifyResult:
    identity = IDENTITY[kind]
    return VerifyResult(
        ok=True,
        identity=identity,
        steps=[
            VerifyStep(
                "authenticate",
                "Authorize the sandbox account",
                "ok",
                f"Access token accepted for {identity}.",
            ),
            VerifyStep(
                "permission",
                "Read billing data",
                "ok",
                "Read-only access to the simulated cost API is granted.",
            ),
        ],
    )


# --- simulated provider data ---------------------------------------------------------


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _rng(kind: ConnectorKind, day: date, salt: str = "") -> random.Random:
    # Seeded per day, so overlapping sync windows report identical history.
    return random.Random(f"{kind.value}:{day.isoformat()}:{salt}")


def _usd(value: float) -> Decimal:
    return Decimal(str(round(value, 6)))


def _weekday_factor(day: date, weekend: float) -> float:
    return weekend if day.weekday() >= 5 else 1.0


def _anthropic(start: date, end: date, config: dict[str, Any]) -> list[CanonicalRow]:
    workspaces = [
        ("wrkspc_sbx_support", "Support assistant", 1.0),
        (None, "Default workspace", 0.25),
    ]
    models = [("claude-sonnet-5", 2.0, 10.0), ("claude-haiku-4-5", 1.0, 5.0)]
    rows = []
    for day in _days(start, end):
        for ws_id, ws_name, share in workspaces:
            for model, price_in, price_out in models:
                rng = _rng(ConnectorKind.ANTHROPIC_COSTS, day, f"{ws_id}{model}")
                scale = share * _weekday_factor(day, 0.6) * rng.uniform(0.85, 1.15)
                for token_type, mtok, price in (
                    ("uncached_input_tokens", 1.4, price_in),
                    ("cache_read_input_tokens", 2.0, price_in * 0.1),
                    ("output_tokens", 0.2, price_out),
                ):
                    tokens = int(mtok * 1_000_000 * scale)
                    rows.append(
                        CanonicalRow(
                            usage_date=day,
                            provider="anthropic",
                            service="Claude API",
                            cost=_usd(tokens / 1_000_000 * price),
                            account_id=ws_id or "default",
                            region="global",
                            usage_type=token_type,
                            model=model,
                            usage_quantity=Decimal(tokens),
                            usage_unit="tokens",
                            project=ws_name if config.get("map_workspaces", True) else None,
                            extra={"service_tier": "standard"},
                        )
                    )
    return rows


def _openai(start: date, end: date, config: dict[str, Any]) -> list[CanonicalRow]:
    projects = [("proj_sbx_search", "Search assistant"), ("proj_sbx_indexing", "Document indexing")]
    lines = [
        ("gpt-4o", "input", 2.5, 1.6),
        ("gpt-4o", "output", 10.0, 0.22),
        ("text-embedding-3-small", "input", 0.02, 30),
    ]
    rows = []
    for day in _days(start, end):
        for project_id, project_name in projects:
            for model, direction, price, mtok in lines:
                rng = _rng(ConnectorKind.OPENAI_COSTS, day, f"{project_id}{model}{direction}")
                tokens = mtok * _weekday_factor(day, 0.5) * rng.uniform(0.8, 1.2)
                rows.append(
                    CanonicalRow(
                        usage_date=day,
                        provider="openai",
                        service="OpenAI API",
                        cost=_usd(tokens * price),
                        account_id=project_id,
                        usage_type=direction,
                        model=model,
                        project=project_name if config.get("map_projects", True) else None,
                        extra={"line_item": f"{model}, {direction}"},
                    )
                )
    return rows


AWS_SERVICES = [
    (
        "Amazon Elastic Compute Cloud - Compute",
        "us-east-1",
        "BoxUsage:m6i.large",
        46.0,
        "storefront",
    ),
    (
        "Amazon Relational Database Service",
        "us-east-1",
        "InstanceUsage:db.r6g.large",
        21.0,
        "storefront",
    ),
    ("Amazon Simple Storage Service", "us-east-1", "TimedStorage-ByteHrs", 7.5, "analytics"),
    ("AWS Lambda", "eu-west-1", "Lambda-GB-Second", 3.2, "billing-api"),
    ("Amazon CloudFront", "global", "DataTransfer-Out-Bytes", 5.8, "storefront"),
]


def _cost_explorer(start: date, end: date, config: dict[str, Any]) -> list[CanonicalRow]:
    group_by = config.get("group_by", "LINKED_ACCOUNT")
    rows = []
    for day in _days(start, end):
        for service, region, usage_type, base, project in AWS_SERVICES:
            rng = _rng(ConnectorKind.AWS_COST_EXPLORER, day, service)
            row = CanonicalRow(
                usage_date=day,
                provider="aws",
                service=service,
                cost=_usd(base * _weekday_factor(day, 0.8) * rng.uniform(0.92, 1.08)),
            )
            if group_by == "LINKED_ACCOUNT":
                row.account_id = SANDBOX_ACCOUNT
            elif group_by == "REGION":
                row.region = None if region == "global" else region
            elif group_by == "USAGE_TYPE":
                row.usage_type = usage_type
            else:
                row.project = project
            rows.append(row)
    return rows


def _cur(end: date, config: dict[str, Any]) -> tuple[list[CanonicalRow], list[tuple[date, date]]]:
    months = int(config.get("billing_periods", 2))
    first = date(end.year, end.month, 1)
    for _ in range(months - 1):
        first = (first - timedelta(days=1)).replace(day=1)
    rows: list[CanonicalRow] = []
    ranges: list[tuple[date, date]] = []
    period = first
    while period <= end:
        last = date(period.year, period.month, monthrange(period.year, period.month)[1])
        ranges.append((period, min(last, end)))
        period = last + timedelta(days=1)
    resources = config.get("include_resource_ids", True)
    for day in _days(first, end):
        for index, (service, region, usage_type, base, project) in enumerate(AWS_SERVICES):
            rng = _rng(ConnectorKind.AWS_CUR_S3, day, service)
            hours = Decimal(24)
            rows.append(
                CanonicalRow(
                    usage_date=day,
                    provider="aws",
                    service=service,
                    cost=_usd(base * _weekday_factor(day, 0.8) * rng.uniform(0.92, 1.08)),
                    account_id=SANDBOX_ACCOUNT,
                    resource_id=f"sbx-resource-{index + 1:02d}" if resources else None,
                    region=None if region == "global" else region,
                    usage_type=usage_type,
                    usage_quantity=hours,
                    usage_unit="Hrs",
                    project=project,
                    environment="production",
                )
            )
    return rows, ranges


def fetch(kind: ConnectorKind, config: dict[str, Any], *, start: date, end: date) -> FetchResult:
    if kind == ConnectorKind.AWS_CUR_S3:
        rows, ranges = _cur(end, config)
        first, last = ranges[0][0], ranges[-1][1]
    else:
        generator = {
            ConnectorKind.ANTHROPIC_COSTS: _anthropic,
            ConnectorKind.OPENAI_COSTS: _openai,
            ConnectorKind.AWS_COST_EXPLORER: _cost_explorer,
        }.get(kind)
        if generator is None:  # pragma: no cover - every kind is covered
            raise ConnectorError(f"No sandbox for {kind}.")
        rows, ranges, first, last = generator(start, end, config), [(start, end)], start, end
    return FetchResult(
        rows=rows,
        ranges=ranges,
        filename=f"sandbox-{kind.value}-{first.isoformat()}-to-{last.isoformat()}.csv",
        detected_format=f"sandbox_{kind.value}",
    )
