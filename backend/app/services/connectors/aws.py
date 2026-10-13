"""Minimal AWS client: Signature Version 4, STS and request helpers over httpx.

CloudPulse needs four read-only calls (sts:GetCallerIdentity, sts:AssumeRole,
ce:GetCostAndUsage, s3:ListBucket/GetObject). Signing them directly keeps the
dependency surface small and lets tests use httpx's MockTransport. The signer is
verified against the worked example in the AWS SigV4 documentation.
"""

import hashlib
import hmac
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote, urlencode

import httpx

from app.services.connectors.base import ConnectorError, send

STS_HOST = "sts.amazonaws.com"
STS_NS = "{https://sts.amazonaws.com/doc/2011-06-15/}"
_UNRESERVED = "-_.~"

# Patched in tests for deterministic signatures.
utcnow: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731


@dataclass(frozen=True)
class AwsCredentials:
    access_key_id: str
    secret_access_key: str
    session_token: str | None = None


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def signing_key(secret: str, datestamp: str, region: str, service: str) -> bytes:
    key = _hmac(f"AWS4{secret}".encode(), datestamp)
    key = _hmac(key, region)
    key = _hmac(key, service)
    return _hmac(key, "aws4_request")


def canonical_query(params: list[tuple[str, str]]) -> str:
    encoded = sorted(
        (quote(str(k), safe=_UNRESERVED), quote(str(v), safe=_UNRESERVED)) for k, v in params
    )
    return "&".join(f"{k}={v}" for k, v in encoded)


def canonical_path(path: str, service: str) -> str:
    encoded = quote(path or "/", safe="/" + _UNRESERVED)
    # Every service except S3 expects each path segment encoded twice.
    return encoded if service == "s3" else quote(encoded, safe="/" + _UNRESERVED)


def sign_request(
    *,
    method: str,
    host: str,
    path: str,
    params: list[tuple[str, str]],
    headers: dict[str, str],
    body: bytes,
    region: str,
    service: str,
    credentials: AwsCredentials,
    now: datetime,
) -> tuple[str, dict[str, str]]:
    """Return (url, headers) for a SigV4-signed request."""
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(body).hexdigest()

    signed = {k.lower(): " ".join(str(v).split()) for k, v in headers.items()}
    signed["host"] = host
    signed["x-amz-date"] = amz_date
    if credentials.session_token:
        signed["x-amz-security-token"] = credentials.session_token
    if service == "s3":
        signed["x-amz-content-sha256"] = payload_hash
    names = sorted(signed)
    signed_headers = ";".join(names)
    query = canonical_query(params)

    canonical_request = "\n".join(
        [
            method,
            canonical_path(path, service),
            query,
            "".join(f"{name}:{signed[name]}\n" for name in names),
            signed_headers,
            payload_hash,
        ]
    )
    scope = f"{datestamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signature = hmac.new(
        signing_key(credentials.secret_access_key, datestamp, region, service),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    out = {name: value for name, value in signed.items() if name != "host"}
    out["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={credentials.access_key_id}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    url = f"https://{host}{quote(path or '/', safe='/' + _UNRESERVED)}"
    if query:
        url += f"?{query}"
    return url, out


def signed_request_builder(
    *,
    method: str,
    host: str,
    path: str = "/",
    params: list[tuple[str, str]] | None = None,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
    region: str,
    service: str,
    credentials: AwsCredentials,
) -> Callable[[], httpx.Request]:
    def build() -> httpx.Request:
        url, signed = sign_request(
            method=method,
            host=host,
            path=path,
            params=params or [],
            headers=headers or {},
            body=body,
            region=region,
            service=service,
            credentials=credentials,
            now=utcnow(),
        )
        return httpx.Request(method, url, headers=signed, content=body)

    return build


def _sts_call(
    client: httpx.Client, credentials: AwsCredentials, params: dict[str, str], what: str
) -> ET.Element:
    body = urlencode({**params, "Version": "2011-06-15"}).encode("ascii")
    response = send(
        client,
        signed_request_builder(
            method="POST",
            host=STS_HOST,
            headers={"content-type": "application/x-www-form-urlencoded; charset=utf-8"},
            body=body,
            region="us-east-1",
            service="sts",
            credentials=credentials,
        ),
        what=what,
    )
    try:
        return ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise ConnectorError(f"{what}: AWS returned a response that is not XML.") from exc


def _text(root: ET.Element, path: str) -> str:
    element = root.find(path)
    if element is None or not element.text:
        raise ConnectorError(f"AWS STS response is missing {path.split('}')[-1]}.")
    return element.text


def get_caller_identity(client: httpx.Client, credentials: AwsCredentials) -> dict[str, str]:
    root = _sts_call(
        client, credentials, {"Action": "GetCallerIdentity"}, "AWS STS GetCallerIdentity"
    )
    result = f"{STS_NS}GetCallerIdentityResult/{STS_NS}"
    return {"account": _text(root, result + "Account"), "arn": _text(root, result + "Arn")}


def assume_role(
    client: httpx.Client,
    credentials: AwsCredentials,
    role_arn: str,
    external_id: str | None,
) -> AwsCredentials:
    params = {
        "Action": "AssumeRole",
        "RoleArn": role_arn,
        "RoleSessionName": "CloudPulse",
        "DurationSeconds": "3600",
    }
    if external_id:
        params["ExternalId"] = external_id
    root = _sts_call(client, credentials, params, "AWS STS AssumeRole")
    creds = f"{STS_NS}AssumeRoleResult/{STS_NS}Credentials/{STS_NS}"
    return AwsCredentials(
        access_key_id=_text(root, creds + "AccessKeyId"),
        secret_access_key=_text(root, creds + "SecretAccessKey"),
        session_token=_text(root, creds + "SessionToken"),
    )


def resolve_credentials(
    client: httpx.Client, secrets: dict[str, str], config: dict[str, object]
) -> AwsCredentials:
    """Access keys from the stored secrets, optionally exchanged for an assumed role."""
    base = AwsCredentials(
        access_key_id=secrets["access_key_id"],
        secret_access_key=secrets["secret_access_key"],
        session_token=secrets.get("session_token") or None,
    )
    role_arn = config.get("role_arn")
    if role_arn:
        external_id = config.get("external_id")
        return assume_role(client, base, str(role_arn), str(external_id) if external_id else None)
    return base
