"""Live billing connectors: provider clients (mocked HTTP), crypto, and the sync workflow."""

import csv
import io
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import crypto
from app.core.config import get_settings
from app.models import BillingImport, BillingRecord, Connector
from app.services.connectors import (
    anthropic_costs,
    aws,
    aws_cost_explorer,
    aws_cur,
    base,
    openai_costs,
    service,
)
from app.services.connectors.base import CanonicalRow, ConnectorError, rows_to_csv
from tests.connector_fakes import (
    FakeProviders,
    anthropic_result,
    anthropic_routes,
    cost_explorer_route,
    gz,
    openai_routes,
    s3_routes,
    sts_routes,
)
from tests.factories import add_cost, make_import

ANTHROPIC_KEY = "sk-ant-admin01-test-key-123456"
OPENAI_KEY = "sk-admin-test-key-1234567890"
AWS_SECRETS = {
    "access_key_id": "AKIAEXAMPLEKEY000001",
    "secret_access_key": "example-secret-access-key-0000",
}
TODAY = datetime.now(UTC).date()


@pytest.fixture(autouse=True)
def _no_retry_wait(monkeypatch) -> None:
    monkeypatch.setattr(base, "sleep", lambda _seconds: None)


@pytest.fixture()
def fake(monkeypatch) -> FakeProviders:
    """Provider fakes, also used by the API (service.http_client_factory)."""
    providers = FakeProviders()
    monkeypatch.setattr(service, "http_client_factory", lambda _settings: providers.client())
    return providers


# --- AWS Signature Version 4 -----------------------------------------------------


def test_sigv4_matches_the_aws_documentation_example() -> None:
    # Worked example from the AWS SigV4 documentation (IAM ListUsers, 2015-08-30).
    secret = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
    assert (
        aws.signing_key(secret, "20150830", "us-east-1", "iam").hex()
        == "c4afb1cc5771d871763a393e44b703571b55cc28424d1a5e86da6ed3c154a4b9"
    )
    url, headers = aws.sign_request(
        method="GET",
        host="iam.amazonaws.com",
        path="/",
        params=[("Version", "2010-05-08"), ("Action", "ListUsers")],
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
        body=b"",
        region="us-east-1",
        service="iam",
        credentials=aws.AwsCredentials("AKIDEXAMPLE", secret),
        now=datetime(2015, 8, 30, 12, 36, tzinfo=UTC),
    )
    assert url == "https://iam.amazonaws.com/?Action=ListUsers&Version=2010-05-08"
    assert headers["authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/iam/aws4_request, "
        "SignedHeaders=content-type;host;x-amz-date, "
        "Signature=5d672d79c15b13162d9279b0855cfba6789a8edb4c82c400e06b5924a6f2b5d7"
    )


def test_sigv4_s3_paths_are_encoded_once_and_session_token_is_signed() -> None:
    assert aws.canonical_path("/cur/BILLING_PERIOD=2026-10/a b.csv", "s3") == (
        "/cur/BILLING_PERIOD%3D2026-10/a%20b.csv"
    )
    assert aws.canonical_path("/a b", "ce") == "/a%2520b"
    _, headers = aws.sign_request(
        method="GET",
        host="bucket.s3.us-east-1.amazonaws.com",
        path="/key",
        params=[],
        headers={},
        body=b"",
        region="us-east-1",
        service="s3",
        credentials=aws.AwsCredentials("ASIAKEY", "secret", "token-1"),
        now=datetime(2026, 10, 13, tzinfo=UTC),
    )
    assert headers["x-amz-security-token"] == "token-1"
    assert "x-amz-content-sha256" in headers
    assert "x-amz-security-token" in headers["authorization"]


# --- shared HTTP behaviour ---------------------------------------------------------


def test_send_retries_rate_limits_then_reports_upstream_errors() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "1"})
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    response = base.send(client, lambda: httpx.Request("GET", "https://x.test/"), what="Probe")
    assert response.status_code == 200 and len(calls) == 2

    denied = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(403, json={"error": {"message": "key revoked"}})
        )
    )
    with pytest.raises(
        ConnectorError, match=r"Probe: the credentials .* \(HTTP 403\) — key revoked"
    ):
        base.send(denied, lambda: httpx.Request("GET", "https://x.test/"), what="Probe")


def test_rows_to_csv_is_deterministic_and_guards_reserved_columns() -> None:
    rows = [
        CanonicalRow(date(2026, 10, 2), "openai", "OpenAI API", Decimal("1.5"), model="gpt-4o"),
        CanonicalRow(
            date(2026, 10, 1), "openai", "OpenAI API", Decimal("0.25"), extra={"line_item": "x"}
        ),
    ]
    first = rows_to_csv(rows)
    assert first == rows_to_csv(list(reversed(rows)))
    parsed = list(csv.DictReader(io.StringIO(first.decode())))
    assert [r["usage_date"] for r in parsed] == ["2026-10-01", "2026-10-02"]
    assert parsed[0]["line_item"] == "x"
    with pytest.raises(ValueError, match="canonical field"):
        rows_to_csv(
            [CanonicalRow(date(2026, 10, 1), "aws", "EC2", Decimal(1), extra={"Cost": "1"})]
        )


# --- credentials encryption --------------------------------------------------------


def test_credentials_are_encrypted_rotatable_and_masked() -> None:
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    settings = get_settings().model_copy(update={"connector_encryption_key": SecretStr(old)})
    token = crypto.encrypt_json(settings, {"admin_key": ANTHROPIC_KEY})
    assert ANTHROPIC_KEY not in token
    rotated = settings.model_copy(update={"connector_encryption_key": SecretStr(f"{new},{old}")})
    assert crypto.decrypt_json(rotated, token) == {"admin_key": ANTHROPIC_KEY}
    with pytest.raises(crypto.EncryptionUnavailable, match="cannot be decrypted"):
        crypto.decrypt_json(
            settings.model_copy(update={"connector_encryption_key": SecretStr(new)}), token
        )
    with pytest.raises(crypto.EncryptionUnavailable, match="CONNECTOR_ENCRYPTION_KEY"):
        crypto.encrypt_json(settings.model_copy(update={"connector_encryption_key": None}), {})
    assert crypto.mask_secret(ANTHROPIC_KEY) == "sk-ant-…3456"
    assert crypto.mask_secret("short") == "…"


# --- provider clients ---------------------------------------------------------------


def test_anthropic_fetch_converts_cents_maps_workspaces_and_pages(fake: FakeProviders) -> None:
    start, end = date(2026, 9, 1), date(2026, 10, 10)  # 40 days -> 2 pages of 31
    anthropic_routes(
        fake,
        {
            date(2026, 9, 1): [anthropic_result("123.78912")],
            date(2026, 10, 10): [
                anthropic_result("250", workspace_id=None, token_type="uncached_input_tokens"),
                anthropic_result("0"),
            ],
        },
        workspaces={"wrkspc_support": "Support assistant"},
    )
    with fake.client() as client:
        result = anthropic_costs.fetch(
            client, {"admin_key": ANTHROPIC_KEY}, {"map_workspaces": True}, start=start, end=end
        )
    assert len(fake.hits("/v1/organizations/cost_report")) == 2
    request = fake.hits("/v1/organizations/cost_report")[0]
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert request.url.params.get_list("group_by[]") == ["workspace_id", "description"]
    assert request.url.params["starting_at"] == "2026-09-01T00:00:00Z"
    assert request.url.params["ending_at"] == "2026-10-11T00:00:00Z"

    first, second = sorted(result.rows, key=lambda r: r.usage_date)
    assert first.cost == Decimal("1.2378912")  # cents -> dollars, exact
    assert (first.provider, first.service, first.model) == (
        "anthropic",
        "Claude API",
        "claude-sonnet-5",
    )
    assert (first.account_id, first.project, first.usage_type) == (
        "wrkspc_support",
        "Support assistant",
        "output_tokens",
    )
    assert first.extra["service_tier"] == "standard"
    assert (second.cost, second.account_id, second.project) == (
        Decimal("2.5"),
        "default",
        "Default workspace",
    )
    assert result.ranges == [(start, end)]


def test_anthropic_verify_reports_each_authorization_step(fake: FakeProviders) -> None:
    anthropic_routes(fake, {})
    with fake.client() as client:
        ok = anthropic_costs.verify(client, {"admin_key": ANTHROPIC_KEY}, {})
        bad = anthropic_costs.verify(client, {"admin_key": "sk-ant-admin01-wrong-key-000"}, {})
    assert ok.ok and ok.identity == "Acme AI"
    assert [s.status for s in ok.steps] == ["ok", "ok"]
    assert not bad.ok
    assert [s.status for s in bad.steps] == ["failed", "skipped"]
    assert "invalid x-api-key" in bad.steps[0].detail


def test_openai_fetch_splits_line_items_and_keeps_exact_amounts(fake: FakeProviders) -> None:
    day = date(2026, 10, 5)
    openai_routes(
        fake,
        {
            day: [
                {
                    "object": "organization.costs.result",
                    "amount": {"value": 0.13080438340307526, "currency": "usd"},
                    "line_item": "gpt-4o-2024-08-06, input",
                    "project_id": "proj_search",
                },
                {
                    "object": "organization.costs.result",
                    "amount": {"value": 0.5, "currency": "usd"},
                    "line_item": "assistants api | file search",
                    "project_id": None,
                },
            ]
        },
        projects={"proj_search": "Search assistant"},
        key=OPENAI_KEY,
    )
    with fake.client() as client:
        result = openai_costs.fetch(
            client, {"admin_key": OPENAI_KEY}, {"map_projects": True}, start=day, end=day
        )
    costs_request = fake.hits("/v1/organization/costs")[0]
    assert costs_request.url.params.get_list("group_by") == ["line_item", "project_id"]
    model_row, tool_row = sorted(result.rows, key=lambda r: r.cost)
    assert model_row.cost == Decimal("0.13080438340307526")  # never passed through float
    assert (model_row.model, model_row.usage_type, model_row.project) == (
        "gpt-4o-2024-08-06",
        "input",
        "Search assistant",
    )
    assert (tool_row.service, tool_row.model, tool_row.usage_type) == (
        "OpenAI assistants api",
        None,
        "file search",
    )
    assert openai_costs.split_line_item("evals | gpt-4o-mini, output") == (
        "OpenAI evals",
        "gpt-4o-mini",
        "output",
    )


def test_cost_explorer_assumes_role_signs_requests_and_pages(fake: FakeProviders) -> None:
    sts_routes(fake)
    day = date(2026, 10, 1)
    period = {"TimePeriod": {"Start": "2026-10-01", "End": "2026-10-02"}, "Estimated": True}
    cost_explorer_route(
        fake,
        [
            {
                "ResultsByTime": [
                    {
                        **period,
                        "Groups": [
                            {
                                "Keys": [
                                    "Amazon Elastic Compute Cloud - Compute",
                                    "project$storefront",
                                ],
                                "Metrics": {"UnblendedCost": {"Amount": "12.3456", "Unit": "USD"}},
                            },
                            {
                                "Keys": ["Amazon Simple Storage Service", "project$"],
                                "Metrics": {"UnblendedCost": {"Amount": "0", "Unit": "USD"}},
                            },
                        ],
                    }
                ],
                "NextPageToken": "1",
            },
            {
                "ResultsByTime": [
                    {
                        **period,
                        "Groups": [
                            {
                                "Keys": ["AWS Lambda", "project$"],
                                "Metrics": {"UnblendedCost": {"Amount": "1.5", "Unit": "USD"}},
                            }
                        ],
                    }
                ]
            },
        ],
    )
    config = {
        "group_by": "TAG",
        "tag_key": "project",
        "role_arn": "arn:aws:iam::999999999999:role/Billing",
        "external_id": "cloudpulse-ext",
    }
    with fake.client() as client:
        result = aws_cost_explorer.fetch(client, AWS_SECRETS, config, start=day, end=day)

    ce_requests = fake.hits("/")
    ce_requests = [r for r in ce_requests if r.url.host.startswith("ce.")]
    assert len(ce_requests) == 2
    first = ce_requests[0]
    assert first.headers["x-amz-target"] == "AWSInsightsIndexService.GetCostAndUsage"
    # Signed with the assumed role's temporary key, including its session token.
    assert "Credential=ASIAASSUMEDKEY000001/" in first.headers["authorization"]
    assert first.headers["x-amz-security-token"] == "assumed-session-token"
    payload = json.loads(first.content)
    assert payload["TimePeriod"] == {"Start": "2026-10-01", "End": "2026-10-02"}
    assert payload["GroupBy"][1] == {"Type": "TAG", "Key": "project"}

    by_service = {r.service: r for r in result.rows}
    assert set(by_service) == {"Amazon Elastic Compute Cloud - Compute", "AWS Lambda"}
    assert by_service["Amazon Elastic Compute Cloud - Compute"].project == "storefront"
    assert by_service["AWS Lambda"].project is None
    assert result.notes == ["1 day(s) are AWS estimates and will be refreshed."]


LEGACY_HEADER = (
    "identity/LineItemId,lineItem/UsageStartDate,lineItem/UsageAccountId,lineItem/ProductCode,"
    "product/ProductName,lineItem/ResourceId,product/region,lineItem/UsageType,"
    "lineItem/UsageAmount,pricing/unit,lineItem/CurrencyCode,lineItem/UnblendedCost,"
    "resourceTags/user:project,resourceTags/user:environment\n"
)


def _cur_objects() -> dict[str, tuple[bytes, str]]:
    october = (
        LEGACY_HEADER
        + "a,2026-10-01T00:00:00Z,111122223333,AmazonEC2,Amazon Elastic Compute Cloud,i-1,"
        "us-east-1,BoxUsage:m6i.large,1,Hrs,USD,0.096,storefront,production\n"
        + "b,2026-10-01T01:00:00Z,111122223333,AmazonEC2,Amazon Elastic Compute Cloud,i-1,"
        "us-east-1,BoxUsage:m6i.large,1,Hrs,USD,0.096,storefront,production\n"
        + "c,2026-10-02T00:00:00Z,111122223333,AmazonS3,Amazon Simple Storage Service,bucket-a,"
        "us-east-1,TimedStorage-ByteHrs,5,GB-Mo,USD,0.115,,\n"
    )
    september = (
        LEGACY_HEADER
        + "d,2026-09-30T00:00:00Z,111122223333,AmazonEC2,Amazon Elastic Compute Cloud,i-1,"
        "us-east-1,BoxUsage:m6i.large,24,Hrs,USD,2.304,storefront,production\n"
    )
    stale = (
        LEGACY_HEADER + "x,2026-10-01T00:00:00Z,1,AmazonEC2,EC2,i-9,us-east-1,X,1,Hrs,USD,999,,\n"
    )
    root = "cur/cloudpulse"
    return {
        # October: an older assembly and the newest one; only the newest is read.
        f"{root}/20261001-20261101/old-asm/cloudpulse-Manifest.json": (
            json.dumps(
                {"reportKeys": [f"{root}/20261001-20261101/old-asm/cloudpulse-1.csv.gz"]}
            ).encode(),
            "2026-10-12T01:00:00.000Z",
        ),
        f"{root}/20261001-20261101/old-asm/cloudpulse-1.csv.gz": (
            gz(stale),
            "2026-10-12T01:00:00.000Z",
        ),
        f"{root}/20261001-20261101/new-asm/cloudpulse-Manifest.json": (
            json.dumps(
                {"reportKeys": [f"{root}/20261001-20261101/new-asm/cloudpulse-1.csv.gz"]}
            ).encode(),
            "2026-10-13T01:00:00.000Z",
        ),
        f"{root}/20261001-20261101/new-asm/cloudpulse-1.csv.gz": (
            gz(october),
            "2026-10-13T01:00:00.000Z",
        ),
        f"{root}/20260901-20261001/cloudpulse-Manifest.json": (
            json.dumps(
                {"reportKeys": [f"{root}/20260901-20261001/asm/cloudpulse-1.csv.gz"]}
            ).encode(),
            "2026-10-03T01:00:00.000Z",
        ),
        f"{root}/20260901-20261001/asm/cloudpulse-1.csv.gz": (
            gz(september),
            "2026-10-03T01:00:00.000Z",
        ),
    }


def test_cur_reads_newest_manifest_per_period_and_aggregates_to_daily(fake: FakeProviders) -> None:
    sts_routes(fake)
    s3_routes(fake, "acme-billing", "us-east-1", _cur_objects())
    config = {
        "bucket": "acme-billing",
        "region": "us-east-1",
        "prefix": "cur/cloudpulse",
        "billing_periods": 2,
    }
    with fake.client() as client:
        result = aws_cur.fetch(
            client,
            AWS_SECRETS,
            config,
            max_rows=1000,
            max_download_bytes=10**7,
            today=date(2026, 10, 13),
        )
    assert result.ranges == [
        (date(2026, 9, 1), date(2026, 9, 30)),
        (date(2026, 10, 1), date(2026, 10, 13)),
    ]
    rows = {(r.usage_date, r.resource_id): r for r in result.rows}
    assert len(rows) == 3  # the stale assembly (cost 999) was never read
    ec2 = rows[(date(2026, 10, 1), "i-1")]
    assert (ec2.cost, ec2.usage_quantity, ec2.usage_unit) == (Decimal("0.192"), Decimal("2"), "Hrs")
    assert (ec2.service, ec2.account_id, ec2.region) == (
        "Amazon Elastic Compute Cloud",
        "111122223333",
        "us-east-1",
    )
    assert (ec2.project, ec2.environment) == ("storefront", "production")
    assert rows[(date(2026, 10, 2), "bucket-a")].project is None
    assert rows[(date(2026, 9, 30), "i-1")].cost == Decimal("2.304")


def test_cur2_map_columns_and_parquet_rejection(fake: FakeProviders) -> None:
    sts_routes(fake)
    header = (
        "line_item_usage_start_date,line_item_usage_account_id,line_item_product_code,product,"
        "line_item_resource_id,product_region_code,line_item_usage_type,line_item_usage_amount,"
        "pricing_unit,line_item_currency_code,line_item_unblended_cost,resource_tags\n"
    )
    row = (
        '2026-10-03T00:00:00.000Z,111122223333,AmazonRDS,"{""product_name"": ""Amazon RDS""}",'
        'db-1,eu-west-1,InstanceUsage,1,Hrs,USD,0.5,"{""user_project"": ""billing"", '
        '""user_environment"": ""staging""}"\n'
    )
    base_key = "exports/cp/data/BILLING_PERIOD=2026-10/cp-00001.csv.gz"
    manifest_key = "exports/cp/metadata/BILLING_PERIOD=2026-10/cp-Manifest.json"
    objects = {
        manifest_key: (
            json.dumps({"dataFiles": [f"s3://acme-billing/{base_key}"]}).encode(),
            "2026-10-13T00:00:00Z",
        ),
        base_key: (gz(header + row), "2026-10-13T00:00:00Z"),
    }
    s3_routes(fake, "acme-billing", "eu-west-1", objects)
    config = {
        "bucket": "acme-billing",
        "region": "eu-west-1",
        "prefix": "exports/cp",
        "billing_periods": 1,
    }
    with fake.client() as client:
        result = aws_cur.fetch(
            client,
            AWS_SECRETS,
            config,
            max_rows=1000,
            max_download_bytes=10**7,
            today=date(2026, 10, 13),
        )
    (only,) = result.rows
    assert (only.service, only.project, only.environment) == ("Amazon RDS", "billing", "staging")

    parquet_key = "exports/cp/data/BILLING_PERIOD=2026-10/cp-00001.snappy.parquet"
    objects[manifest_key] = (
        json.dumps({"dataFiles": [f"s3://acme-billing/{parquet_key}"]}).encode(),
        "2026-10-13T00:00:00Z",
    )
    objects[parquet_key] = (b"PAR1", "2026-10-13T00:00:00Z")
    s3_routes(fake, "acme-billing", "eu-west-1", objects)
    with fake.client() as client, pytest.raises(ConnectorError, match="Parquet"):
        aws_cur.fetch(client, AWS_SECRETS, config, max_rows=1000, max_download_bytes=10**7)


def test_cur_reports_wrong_bucket_region_clearly(fake: FakeProviders) -> None:
    sts_routes(fake)
    fake.route(
        "GET",
        "acme-billing.s3.us-east-1.amazonaws.com",
        "/",
        lambda r: httpx.Response(
            301,
            headers={"x-amz-bucket-region": "eu-central-1"},
            text="<Error><Code>PermanentRedirect</Code></Error>",
        ),
    )
    with fake.client() as client:
        result = aws_cur.verify(
            client, AWS_SECRETS, {"bucket": "acme-billing", "region": "us-east-1"}
        )
    assert not result.ok
    assert result.steps[0].status == "ok"
    assert "is in region eu-central-1" in result.steps[1].detail


# --- API and sync workflow -----------------------------------------------------------


def _create_anthropic(client: TestClient, **overrides) -> dict:
    payload = {
        "kind": "anthropic_costs",
        "name": "Claude production org",
        "config": {"map_workspaces": True},
        "credentials": {"admin_key": ANTHROPIC_KEY},
        "lookback_days": 7,
        "sync_interval_hours": 6,
    } | overrides
    response = client.post("/api/v1/connectors", json=payload)
    assert response.status_code == 201, response.json()
    return response.json()


def test_create_stores_credentials_encrypted_and_never_returns_them(
    client: TestClient, db: Session, fake: FakeProviders
) -> None:
    body = _create_anthropic(client)
    assert body["credentials_hint"] == "sk-ant-…3456"
    assert body["provider"] == "anthropic"
    stored = db.scalar(select(Connector.credentials_encrypted))
    assert ANTHROPIC_KEY not in stored
    listed = client.get("/api/v1/connectors")
    assert ANTHROPIC_KEY not in listed.text and "admin_key" not in listed.text

    catalog = client.get("/api/v1/connectors/catalog").json()
    assert catalog["encryption_configured"] is True
    assert {k["kind"] for k in catalog["kinds"]} == {
        "aws_cur_s3",
        "aws_cost_explorer",
        "openai_costs",
        "anthropic_costs",
    }


def test_connector_input_is_validated(client: TestClient, fake: FakeProviders) -> None:
    response = client.post(
        "/api/v1/connectors",
        json={
            "kind": "aws_cur_s3",
            "name": "CUR",
            "config": {"bucket": "Bad_Bucket", "region": "us-east-1"},
            "credentials": AWS_SECRETS,
        },
    )
    assert response.status_code == 422
    locations = {d["location"] for d in response.json()["error"]["details"]}
    assert "config.bucket" in locations
    unknown = client.post(
        "/api/v1/connectors",
        json={
            "kind": "openai_costs",
            "name": "OpenAI",
            "credentials": {"admin_key": OPENAI_KEY, "extra": "x"},
        },
    )
    assert unknown.status_code == 422


def test_verify_unsaved_credentials_returns_steps_without_storing(
    client: TestClient, db: Session, fake: FakeProviders
) -> None:
    anthropic_routes(fake, {})
    response = client.post(
        "/api/v1/connectors/verify",
        json={"kind": "anthropic_costs", "credentials": {"admin_key": ANTHROPIC_KEY}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["identity"] == "Acme AI"
    assert [s["key"] for s in body["steps"]] == ["authenticate", "permission"]
    assert db.scalar(select(func.count()).select_from(Connector)) == 0


def test_sync_imports_then_reconciles_restated_days_without_double_counting(
    client: TestClient, db: Session, fake: FakeProviders
) -> None:
    d1, d2 = TODAY - timedelta(days=2), TODAY - timedelta(days=1)
    costs = {
        d1: [anthropic_result("1000"), anthropic_result("500", token_type="uncached_input_tokens")],
        d2: [anthropic_result("2000")],
    }
    anthropic_routes(fake, costs, workspaces={"wrkspc_support": "Support assistant"})
    # Another source's record on the same day must never be touched by the connector.
    upload = make_import(db)
    add_cost(db, upload, d1, "7.00", provider="anthropic", service="Claude API")
    db.commit()
    connector = _create_anthropic(client)

    first = client.post(f"/api/v1/connectors/{connector['id']}/sync").json()
    assert first["status"] == "succeeded", first
    assert first["changed"] is True
    imported = db.get(BillingImport, first["import_id"])
    assert (imported.source, imported.connector_id, imported.detected_format) == (
        "connector",
        connector["id"],
        "anthropic_cost_report",
    )
    assert imported.rows_inserted == 3
    projects = set(
        db.scalars(select(BillingRecord.project).where(BillingRecord.import_id == imported.id))
    )
    assert projects == {"Support assistant"}

    def total() -> Decimal:
        return db.scalar(select(func.sum(BillingRecord.cost)))

    assert total() == Decimal("42.00")  # 10 + 5 + 20 from Anthropic, 7 uploaded

    # Anthropic restates: day 1 output cost changes, the input line disappears.
    costs[d1] = [anthropic_result("1250")]
    second = client.post(f"/api/v1/connectors/{connector['id']}/sync").json()
    assert second["status"] == "succeeded" and second["changed"] is True
    restated = db.get(BillingImport, second["import_id"])
    assert (restated.rows_inserted, restated.rows_duplicate, restated.rows_replaced) == (1, 1, 2)
    assert total() == Decimal("39.50")  # 12.50 + 20 + 7: nothing counted twice

    # Nothing changed: no empty import is left behind.
    imports_before = db.scalar(select(func.count()).select_from(BillingImport))
    third = client.post(f"/api/v1/connectors/{connector['id']}/sync").json()
    assert third["status"] == "succeeded" and third["changed"] is False
    assert third["message"].startswith("Up to date")
    assert db.scalar(select(func.count()).select_from(BillingImport)) == imports_before
    assert third["connector"]["last_import_id"] == second["import_id"]


def test_failed_sync_is_recorded_and_keeps_existing_data(
    client: TestClient, db: Session, fake: FakeProviders
) -> None:
    anthropic_routes(fake, {}, key="sk-ant-admin01-a-different-key")
    connector = _create_anthropic(client)
    response = client.post(f"/api/v1/connectors/{connector['id']}/sync")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert "credentials were rejected" in body["message"] and "invalid x-api-key" in body["message"]
    assert body["connector"]["last_sync_status"] == "failed"
    assert db.scalar(select(func.count()).select_from(BillingImport)) == 0


def test_test_endpoint_marks_connector_verified(client: TestClient, fake: FakeProviders) -> None:
    anthropic_routes(fake, {})
    connector = _create_anthropic(client)
    result = client.post(f"/api/v1/connectors/{connector['id']}/test").json()
    assert result["ok"] is True
    refreshed = client.get(f"/api/v1/connectors/{connector['id']}").json()
    assert refreshed["verified_identity"] == "Acme AI"
    assert refreshed["last_verified_at"] is not None


def test_update_keeps_or_replaces_credentials_and_delete_keeps_data(
    client: TestClient, db: Session, fake: FakeProviders
) -> None:
    anthropic_routes(fake, {TODAY - timedelta(days=1): [anthropic_result("100")]})
    connector = _create_anthropic(client)
    client.post(f"/api/v1/connectors/{connector['id']}/test")
    settings = {"name": "Renamed", "config": {}, "lookback_days": 3, "sync_interval_hours": 0}

    kept = client.put(f"/api/v1/connectors/{connector['id']}", json=settings).json()
    assert kept["name"] == "Renamed" and kept["verified_identity"] == "Acme AI"
    assert kept["next_sync_at"] is None  # manual only
    synced = client.post(f"/api/v1/connectors/{connector['id']}/sync").json()
    assert synced["status"] == "succeeded"  # the stored key still works

    replaced = client.put(
        f"/api/v1/connectors/{connector['id']}",
        json=settings | {"credentials": {"admin_key": "sk-ant-admin01-new-key-9999"}},
    ).json()
    assert replaced["credentials_hint"] == "sk-ant-…9999"
    assert replaced["verified_identity"] is None

    assert client.delete(f"/api/v1/connectors/{connector['id']}").status_code == 204
    remaining = db.scalars(select(BillingImport)).all()
    assert len(remaining) == 1 and remaining[0].connector_id is None
    assert db.scalar(select(func.count()).select_from(BillingRecord)) == 1


def test_members_can_sync_but_not_configure(client_for, fake: FakeProviders) -> None:
    anthropic_routes(fake, {})
    admin = client_for("admin")
    connector = _create_anthropic(admin)
    member = client_for("member")
    assert member.post(f"/api/v1/connectors/{connector['id']}/sync").status_code == 200
    assert member.post(f"/api/v1/connectors/{connector['id']}/test").status_code == 403
    viewer = client_for("viewer")
    assert viewer.get("/api/v1/connectors").status_code == 200
    assert viewer.post(f"/api/v1/connectors/{connector['id']}/sync").status_code == 403


def test_due_connectors_respects_interval_and_enabled(db: Session, client: TestClient) -> None:
    now = datetime.now(UTC)
    common = {
        "kind": "openai_costs",
        "config": {},
        "credentials_encrypted": "x",
        "credentials_hint": "…",
        "lookback_days": 7,
    }
    never = Connector(name="never synced", sync_interval_hours=24, **common)
    recent = Connector(
        name="recent",
        sync_interval_hours=24,
        last_sync_started_at=now - timedelta(hours=2),
        **common,
    )
    stale = Connector(
        name="stale", sync_interval_hours=6, last_sync_started_at=now - timedelta(hours=7), **common
    )
    manual = Connector(name="manual", sync_interval_hours=0, **common)
    disabled = Connector(name="disabled", sync_interval_hours=1, enabled=False, **common)
    db.add_all([never, recent, stale, manual, disabled])
    db.commit()
    assert set(service.due_connectors(db, now)) == {never.id, stale.id}


def test_concurrent_sync_is_refused(client: TestClient, db: Session, fake: FakeProviders) -> None:
    connector = _create_anthropic(client)
    row = db.get(Connector, connector["id"])
    row.last_sync_status = "running"
    row.last_sync_started_at = datetime.now(UTC)
    db.commit()
    response = client.post(f"/api/v1/connectors/{connector['id']}/sync")
    assert response.status_code == 409
