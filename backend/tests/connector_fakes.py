"""In-process fakes of the provider billing APIs, served through httpx.MockTransport."""

import gzip
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import parse_qs

import httpx

Handler = Callable[[httpx.Request], httpx.Response]


class FakeProviders:
    """Routes requests by (method, host, path); records every request it serves."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str, str], Handler] = {}
        self.requests: list[httpx.Request] = []

    def route(self, method: str, host: str, path: str, handler: Handler) -> None:
        self.routes[(method, host, path)] = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        handler = self.routes.get((request.method, request.url.host, request.url.path))
        if handler is None:
            return httpx.Response(404, json={"error": {"message": f"no route {request.url}"}})
        return handler(request)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def hits(self, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == path]


# --- Anthropic -------------------------------------------------------------------


def anthropic_routes(
    fake: FakeProviders,
    costs_by_day: dict[date, list[dict]],
    *,
    workspaces: dict[str, str] | None = None,
    page_size: int = 31,
    key: str = "sk-ant-admin01-test-key-123456",
) -> None:
    host = "api.anthropic.com"

    def authorized(request: httpx.Request) -> bool:
        return request.headers.get("x-api-key") == key

    def unauthorized() -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "type": "error",
                "error": {"type": "authentication_error", "message": "invalid x-api-key"},
            },
        )

    def me(request: httpx.Request) -> httpx.Response:
        if not authorized(request):
            return unauthorized()
        return httpx.Response(
            200, json={"id": "org_123", "type": "organization", "name": "Acme AI"}
        )

    def list_workspaces(request: httpx.Request) -> httpx.Response:
        if not authorized(request):
            return unauthorized()
        data = [
            {"id": wid, "name": name, "type": "workspace"}
            for wid, name in (workspaces or {}).items()
        ]
        return httpx.Response(
            200, json={"data": data, "has_more": False, "first_id": None, "last_id": None}
        )

    def cost_report(request: httpx.Request) -> httpx.Response:
        if not authorized(request):
            return unauthorized()
        params = request.url.params
        start = date.fromisoformat(params["starting_at"][:10])
        end = date.fromisoformat(params["ending_at"][:10]) if "ending_at" in params else start
        days = [start + timedelta(days=i) for i in range((end - start).days)]
        offset = int(params.get("page", "0"))
        page = days[offset : offset + min(page_size, int(params.get("limit", "7")))]
        buckets = [
            {
                "starting_at": f"{day.isoformat()}T00:00:00Z",
                "ending_at": f"{(day + timedelta(days=1)).isoformat()}T00:00:00Z",
                "results": costs_by_day.get(day, []),
            }
            for day in page
        ]
        more = offset + len(page) < len(days)
        return httpx.Response(
            200,
            json={
                "data": buckets,
                "has_more": more,
                "next_page": str(offset + len(page)) if more else None,
            },
        )

    fake.route("GET", host, "/v1/organizations/me", me)
    fake.route("GET", host, "/v1/organizations/workspaces", list_workspaces)
    fake.route("GET", host, "/v1/organizations/cost_report", cost_report)


def anthropic_result(
    cents: str,
    *,
    workspace_id: str | None = "wrkspc_support",
    model: str = "claude-sonnet-5",
    token_type: str = "output_tokens",
) -> dict:
    return {
        "amount": cents,
        "currency": "USD",
        "workspace_id": workspace_id,
        "description": f"{model} Usage - {token_type}",
        "cost_type": "tokens",
        "model": model,
        "token_type": token_type,
        "service_tier": "standard",
        "context_window": "0-200k",
        "inference_geo": "global",
    }


# --- OpenAI ----------------------------------------------------------------------


def openai_routes(
    fake: FakeProviders,
    costs_by_day: dict[date, list[dict]],
    *,
    projects: dict[str, str],
    key: str = "sk-admin-test-key-1234567890",
) -> None:
    host = "api.openai.com"

    def authorized(request: httpx.Request) -> bool:
        return request.headers.get("authorization") == f"Bearer {key}"

    def projects_handler(request: httpx.Request) -> httpx.Response:
        if not authorized(request):
            return httpx.Response(401, json={"error": {"message": "Incorrect API key provided"}})
        items = [
            {"id": pid, "object": "organization.project", "name": name}
            for pid, name in projects.items()
        ]
        return httpx.Response(200, json={"data": items, "has_more": False, "last_id": None})

    def costs(request: httpx.Request) -> httpx.Response:
        if not authorized(request):
            return httpx.Response(401, json={"error": {"message": "Incorrect API key provided"}})
        params = request.url.params
        start = datetime.fromtimestamp(int(params["start_time"]), UTC).date()
        end = (
            datetime.fromtimestamp(int(params["end_time"]), UTC).date()
            if "end_time" in params
            else start + timedelta(days=1)
        )
        days = [start + timedelta(days=i) for i in range((end - start).days)]
        offset = int(params.get("page", "0"))
        page = days[offset : offset + int(params.get("limit", "7"))]
        buckets = [
            {
                "object": "bucket",
                "start_time": int(datetime.combine(day, time.min, tzinfo=UTC).timestamp()),
                "end_time": int(
                    datetime.combine(day + timedelta(days=1), time.min, tzinfo=UTC).timestamp()
                ),
                "results": costs_by_day.get(day, []),
            }
            for day in page
        ]
        more = offset + len(page) < len(days)
        # Raw JSON so the float literal reaches the client exactly as OpenAI sends it.
        body = json.dumps(
            {
                "object": "page",
                "data": buckets,
                "has_more": more,
                "next_page": str(offset + len(page)) if more else None,
            }
        )
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    fake.route("GET", host, "/v1/organization/projects", projects_handler)
    fake.route("GET", host, "/v1/organization/costs", costs)


# --- AWS -------------------------------------------------------------------------

STS_XML = (
    '<GetCallerIdentityResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">'
    "<GetCallerIdentityResult><Arn>{arn}</Arn><UserId>AIDAEXAMPLE</UserId>"
    "<Account>{account}</Account></GetCallerIdentityResult></GetCallerIdentityResponse>"
)
ASSUME_XML = (
    '<AssumeRoleResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/"><AssumeRoleResult>'
    "<Credentials><AccessKeyId>ASIAASSUMEDKEY000001</AccessKeyId>"
    "<SecretAccessKey>assumed-secret-key-value-0000</SecretAccessKey>"
    "<SessionToken>assumed-session-token</SessionToken>"
    "<Expiration>2030-01-01T00:00:00Z</Expiration></Credentials>"
    "<AssumedRoleUser><Arn>arn:aws:sts::999999999999:assumed-role/Billing/CloudPulse</Arn>"
    "<AssumedRoleId>AROAEXAMPLE:CloudPulse</AssumedRoleId></AssumedRoleUser>"
    "</AssumeRoleResult></AssumeRoleResponse>"
)


def sts_routes(fake: FakeProviders, *, account: str = "123456789012") -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if form.get("Action") == "AssumeRole":
            return httpx.Response(200, text=ASSUME_XML)
        credential = request.headers["authorization"].split("Credential=")[1].split("/")[0]
        arn = (
            "arn:aws:sts::999999999999:assumed-role/Billing/CloudPulse"
            if credential.startswith("ASIA")
            else f"arn:aws:iam::{account}:user/billing-reader"
        )
        return httpx.Response(200, text=STS_XML.format(arn=arn, account=account))

    fake.route("POST", "sts.amazonaws.com", "/", handler)


def cost_explorer_route(fake: FakeProviders, pages: list[dict]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        index = int(body.get("NextPageToken", "0"))
        return httpx.Response(200, json=pages[index])

    fake.route("POST", "ce.us-east-1.amazonaws.com", "/", handler)


def s3_routes(
    fake: FakeProviders, bucket: str, region: str, objects: dict[str, tuple[bytes, str]]
) -> None:
    """objects: key -> (content, last_modified)."""
    host = f"{bucket}.s3.{region}.amazonaws.com"

    def list_handler(request: httpx.Request) -> httpx.Response:
        prefix = request.url.params.get("prefix", "")
        items = "".join(
            f"<Contents><Key>{key}</Key><LastModified>{modified}</LastModified>"
            f"<Size>{len(content)}</Size></Contents>"
            for key, (content, modified) in sorted(objects.items())
            if key.startswith(prefix)
        )
        xml = (
            '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            f"<Name>{bucket}</Name><IsTruncated>false</IsTruncated>{items}</ListBucketResult>"
        )
        return httpx.Response(200, text=xml)

    fake.route("GET", host, "/", list_handler)
    for key, (content, _) in objects.items():
        fake.route(
            "GET", host, f"/{key}", lambda _r, content=content: httpx.Response(200, content=content)
        )


def gz(text: str) -> bytes:
    return gzip.compress(text.encode("utf-8"))
