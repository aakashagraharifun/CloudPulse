"""AWS Cost and Usage Report (CUR) connector: reads CUR files from an S3 bucket.

Works with both legacy CUR and CUR 2.0 (Data Exports) delivered as CSV (gzip).
AWS re-delivers the complete file set for the current billing period several
times a day, and describes each delivery in a `*-Manifest.json`. A sync:

1. lists the bucket prefix and finds the newest manifest per billing period,
2. downloads the data files that manifest lists (newest N periods),
3. aggregates hourly line items to one row per day and line-item identity, and
4. replaces those billing periods in CloudPulse (see ReplaceScope).

Parquet exports are not supported; configure the export with CSV + GZIP.
Required IAM permissions: s3:ListBucket on the bucket and s3:GetObject on the prefix.
"""

import csv
import gzip
import io
import json
import re
import tempfile
import xml.etree.ElementTree as ET
from calendar import monthrange
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import IO, Any

import httpx

from app.services.connectors.aws import (
    AwsCredentials,
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
    describe_failure,
    send,
)
from app.services.normalization.schema import normalize_header

S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
MAX_LISTED_KEYS = 50_000
_PERIOD_CUR2 = re.compile(r"BILLING_PERIOD=(\d{4})-(\d{2})")
_PERIOD_LEGACY = re.compile(r"(?:^|/)(\d{4})(\d{2})01-\d{8}(?:/|$)")

# Candidate columns, normalized (legacy CUR first, then CUR 2.0).
COLUMNS = {
    "usage_date": ("lineitem_usagestartdate", "line_item_usage_start_date"),
    "account_id": ("lineitem_usageaccountid", "line_item_usage_account_id"),
    "service": ("product_productname", "product_product_name"),
    "product_code": ("lineitem_productcode", "line_item_product_code"),
    "resource_id": ("lineitem_resourceid", "line_item_resource_id"),
    "region": ("product_region", "product_regioncode", "product_region_code"),
    "usage_type": ("lineitem_usagetype", "line_item_usage_type"),
    "usage_quantity": ("lineitem_usageamount", "line_item_usage_amount"),
    "usage_unit": ("pricing_unit",),
    "currency": ("lineitem_currencycode", "line_item_currency_code"),
    "cost": ("lineitem_unblendedcost", "line_item_unblended_cost"),
}
REQUIRED = ("usage_date", "cost")


@dataclass(frozen=True)
class S3Object:
    key: str
    last_modified: str
    size: int


@dataclass(frozen=True)
class Bucket:
    name: str
    region: str
    credentials: AwsCredentials

    def address(self, key: str) -> tuple[str, str]:
        """(host, path). Bucket names containing dots use path-style (TLS wildcard limits)."""
        if "." in self.name:
            return f"s3.{self.region}.amazonaws.com", f"/{self.name}/{key}"
        return f"{self.name}.s3.{self.region}.amazonaws.com", f"/{key}"


def _s3_failure(what: str, response: httpx.Response, bucket: Bucket) -> ConnectorError:
    actual = response.headers.get("x-amz-bucket-region")
    if actual and actual != bucket.region:
        return ConnectorError(
            f"{what}: bucket {bucket.name} is in region {actual}, not {bucket.region}. "
            "Update the connector's region."
        )
    return ConnectorError(describe_failure(what, response))


def list_objects(
    client: httpx.Client, bucket: Bucket, prefix: str, *, max_keys: int | None = None
) -> list[S3Object]:
    objects: list[S3Object] = []
    token: str | None = None
    host, path = bucket.address("")
    while True:
        params = [("list-type", "2"), ("prefix", prefix)]
        if max_keys:
            params.append(("max-keys", str(max_keys)))
        if token:
            params.append(("continuation-token", token))
        what = f"S3 ListObjectsV2 on s3://{bucket.name}/{prefix}"
        response = send(
            client,
            signed_request_builder(
                method="GET",
                host=host,
                path=path,
                params=params,
                region=bucket.region,
                service="s3",
                credentials=bucket.credentials,
            ),
            what=what,
            failure=lambda r, what=what: _s3_failure(what, r, bucket),
        )
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise ConnectorError(f"{what}: S3 returned a response that is not XML.") from exc
        for item in root.findall(f"{S3_NS}Contents"):
            objects.append(
                S3Object(
                    key=item.findtext(f"{S3_NS}Key", ""),
                    last_modified=item.findtext(f"{S3_NS}LastModified", ""),
                    size=int(item.findtext(f"{S3_NS}Size", "0")),
                )
            )
        if max_keys or root.findtext(f"{S3_NS}IsTruncated") != "true":
            return objects
        if len(objects) >= MAX_LISTED_KEYS:
            raise ConnectorError(
                f"More than {MAX_LISTED_KEYS:,} objects under s3://{bucket.name}/{prefix}. "
                "Point the connector at the report's own prefix."
            )
        token = root.findtext(f"{S3_NS}NextContinuationToken")


def download(
    client: httpx.Client, bucket: Bucket, key: str, sink: IO[bytes], budget: list[int]
) -> None:
    """Stream an object into `sink`; `budget` is the remaining byte allowance (mutated)."""
    host, path = bucket.address(key)
    build = signed_request_builder(
        method="GET",
        host=host,
        path=path,
        region=bucket.region,
        service="s3",
        credentials=bucket.credentials,
    )
    what = f"S3 GetObject s3://{bucket.name}/{key}"
    try:
        response = client.send(build(), stream=True)
    except httpx.HTTPError as exc:
        raise ConnectorError(f"{what}: could not connect to S3 ({exc}).") from exc
    try:
        if not response.is_success:
            response.read()
            raise _s3_failure(what, response, bucket)
        for chunk in response.iter_bytes():
            budget[0] -= len(chunk)
            if budget[0] < 0:
                raise ConnectorError(
                    "The CUR files exceed the download limit for one sync "
                    "(CONNECTOR_MAX_DOWNLOAD_BYTES). Sync fewer billing periods."
                )
            sink.write(chunk)
    except httpx.HTTPError as exc:
        raise ConnectorError(f"{what}: download failed ({exc}).") from exc
    finally:
        response.close()


def _period_of(key: str) -> date | None:
    match = _PERIOD_CUR2.search(key) or _PERIOD_LEGACY.search(key)
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return date(year, month, 1)


def latest_manifests(objects: list[S3Object]) -> dict[date, S3Object]:
    """Newest manifest per billing period."""
    manifests: dict[date, S3Object] = {}
    for obj in objects:
        if not obj.key.lower().endswith("manifest.json"):
            continue
        period = _period_of(obj.key)
        if period is None:
            continue
        current = manifests.get(period)
        if current is None or obj.last_modified > current.last_modified:
            manifests[period] = obj
    return manifests


def manifest_data_keys(manifest: dict[str, Any], bucket_name: str) -> list[str]:
    """Data file keys from a legacy (`reportKeys`) or CUR 2.0 (`dataFiles`) manifest."""
    raw = manifest.get("reportKeys") or manifest.get("dataFiles") or []
    keys = []
    for entry in raw:
        value = str(entry)
        if value.startswith("s3://"):
            _, _, rest = value[5:].partition("/")
            if not value[5:].startswith(f"{bucket_name}/"):
                raise ConnectorError(f"Manifest references a file in another bucket: {value}")
            value = rest
        keys.append(value)
    return keys


def _open_text(path_or_file: IO[bytes], key: str) -> IO[str]:
    lowered = key.lower()
    if lowered.endswith(".parquet") or lowered.endswith(".snappy.parquet"):
        raise ConnectorError(
            "This export is in Parquet format, which CloudPulse does not read. "
            "Create the export with CSV format and GZIP compression."
        )
    if lowered.endswith(".zip"):
        raise ConnectorError("ZIP-compressed CUR files are not supported; use GZIP compression.")
    binary: IO[bytes] = (
        gzip.GzipFile(fileobj=path_or_file) if lowered.endswith(".gz") else (path_or_file)
    )
    return io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")


def _number(raw: str) -> Decimal:
    if not raw:
        return Decimal(0)
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise ConnectorError(
            f"CUR file contains a value that is not a number: {raw[:40]!r}"
        ) from exc


class Aggregator:
    """Sums hourly CUR line items into daily rows."""

    def __init__(self, config: dict[str, Any], max_rows: int) -> None:
        self.include_resources = bool(config.get("include_resource_ids", True))
        self.project_key = str(config.get("project_tag_key") or "project")
        self.environment_key = str(config.get("environment_tag_key") or "environment")
        self.max_rows = max_rows
        self.totals: dict[tuple, list[Decimal | None]] = {}

    def _tag_columns(self, key: str) -> tuple[str, str]:
        # Legacy: "resourceTags/user:project"; CUR 2.0 map key: "user_project".
        return normalize_header(f"resourceTags/user:{key}"), normalize_header(f"user:{key}")

    def add_file(self, text: IO[str], key: str) -> None:
        reader = csv.reader(text)
        try:
            header = next(reader)
        except StopIteration:
            return
        names = [normalize_header(h) for h in header]
        position = {name: i for i, name in enumerate(names)}
        index: dict[str, int] = {}
        for field, candidates in COLUMNS.items():
            for candidate in candidates:
                if candidate in position:
                    index[field] = position[candidate]
                    break
        missing = [f for f in REQUIRED if f not in index]
        if missing:
            raise ConnectorError(
                f"{key} does not look like a CUR file (missing {', '.join(missing)} columns)."
            )
        project_legacy, project_map = self._tag_columns(self.project_key)
        env_legacy, env_map = self._tag_columns(self.environment_key)
        tags_map = position.get("resource_tags")
        product_map = position.get("product")

        def get(row: list[str], field: str) -> str:
            i = index.get(field)
            return row[i].strip() if i is not None and i < len(row) else ""

        for row in reader:
            if not row:
                continue
            raw_date = get(row, "usage_date")[:10]
            try:
                usage_date = date.fromisoformat(raw_date)
            except ValueError as exc:
                raise ConnectorError(f"{key}: invalid usage start date {raw_date!r}.") from exc

            service = get(row, "service")
            if not service and product_map is not None and product_map < len(row):
                service = _map_value(row[product_map], "product_name")
            service = service or get(row, "product_code") or "Unknown service"

            project = row[position[project_legacy]].strip() if project_legacy in position else ""
            environment = row[position[env_legacy]].strip() if env_legacy in position else ""
            if tags_map is not None and tags_map < len(row) and (not project or not environment):
                project = project or _map_value(row[tags_map], project_map)
                environment = environment or _map_value(row[tags_map], env_map)

            identity = (
                usage_date,
                get(row, "account_id")[:128],
                service[:255],
                get(row, "resource_id")[:512] if self.include_resources else "",
                get(row, "region")[:64],
                get(row, "usage_type")[:255],
                get(row, "usage_unit")[:64],
                (get(row, "currency") or "USD").upper(),
                project[:128],
                environment[:128],
            )
            cost = _number(get(row, "cost"))
            quantity = _number(get(row, "usage_quantity")) if "usage_quantity" in index else None
            totals = self.totals.get(identity)
            if totals is None:
                if len(self.totals) >= self.max_rows:
                    raise ConnectorError(
                        f"The CUR data has more than {self.max_rows:,} daily line items. "
                        "Turn off 'include resource IDs' or sync fewer billing periods."
                    )
                self.totals[identity] = [cost, quantity]
            else:
                totals[0] = totals[0] + cost  # type: ignore[operator]
                if quantity is not None and totals[1] is not None:
                    totals[1] = totals[1] + quantity

    def rows(self) -> Iterator[CanonicalRow]:
        for identity, (cost, quantity) in self.totals.items():
            (day, account, service, resource, region, usage_type, unit, currency, project, env) = (
                identity
            )
            if cost == 0 and not quantity:
                continue
            yield CanonicalRow(
                usage_date=day,
                provider="aws",
                account_id=account or None,
                service=service,
                resource_id=resource or None,
                region=region or None,
                usage_type=usage_type or None,
                # Credits can carry negative usage amounts; quantity must not be negative.
                usage_quantity=quantity if quantity is not None and quantity >= 0 else None,
                usage_unit=unit or None,
                currency=currency,
                cost=cost,  # type: ignore[arg-type]
                project=project or None,
                environment=env or None,
            )


def _map_value(raw: str, wanted: str) -> str:
    """Value for `wanted` (normalized key) in a CUR 2.0 map column (JSON object)."""
    if not raw or not raw.startswith("{"):
        return ""
    try:
        data = json.loads(raw)
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    for key, value in data.items():
        if normalize_header(str(key)) == wanted and value is not None:
            return str(value).strip()
    return ""


def _bucket(client: httpx.Client, secrets: dict[str, str], config: dict[str, Any]) -> Bucket:
    credentials = resolve_credentials(client, secrets, config)
    return Bucket(name=str(config["bucket"]), region=str(config["region"]), credentials=credentials)


def _prefix(config: dict[str, Any]) -> str:
    return str(config.get("prefix") or "").lstrip("/")


def fetch(
    client: httpx.Client,
    secrets: dict[str, str],
    config: dict[str, Any],
    *,
    max_rows: int,
    max_download_bytes: int,
    today: date | None = None,
) -> FetchResult:
    today = today or datetime.now(UTC).date()
    bucket = _bucket(client, secrets, config)
    prefix = _prefix(config)
    manifests = latest_manifests(list_objects(client, bucket, prefix))
    if not manifests:
        raise ConnectorError(
            f"No CUR manifest (*-Manifest.json) was found under s3://{bucket.name}/{prefix}. "
            "Check the prefix; AWS can take up to 24 hours to deliver the first report."
        )
    periods = sorted(manifests, reverse=True)[: int(config.get("billing_periods", 2))]
    aggregator = Aggregator(config, max_rows)
    budget = [max_download_bytes]
    ranges: list[tuple[date, date]] = []
    files = 0
    for period in sorted(periods):
        manifest_obj = manifests[period]
        with tempfile.TemporaryFile() as sink:
            download(client, bucket, manifest_obj.key, sink, budget)
            sink.seek(0)
            try:
                manifest = json.loads(sink.read())
            except ValueError as exc:
                raise ConnectorError(f"{manifest_obj.key} is not valid JSON.") from exc
        keys = manifest_data_keys(manifest, bucket.name)
        if not keys:
            continue
        for key in keys:
            with tempfile.TemporaryFile() as sink:
                download(client, bucket, key, sink, budget)
                sink.seek(0)
                aggregator.add_file(_open_text(sink, key), key)
            files += 1
        last_day = date(period.year, period.month, monthrange(period.year, period.month)[1])
        ranges.append((period, min(last_day, today)))
    if not ranges:
        raise ConnectorError("The CUR manifests list no data files yet.")
    first, last = ranges[0][0], ranges[-1][1]
    return FetchResult(
        rows=list(aggregator.rows()),
        ranges=ranges,
        filename=f"aws-cur-{first.isoformat()}-to-{last.isoformat()}.csv",
        detected_format="aws_cur",
        notes=[f"Read {files} CUR file(s) for {len(ranges)} billing period(s)."],
    )


def verify(client: httpx.Client, secrets: dict[str, str], config: dict[str, Any]) -> VerifyResult:
    steps: list[VerifyStep] = []
    try:
        credentials = resolve_credentials(client, secrets, config)
        identity = get_caller_identity(client, credentials)
    except ConnectorError as exc:
        steps.append(VerifyStep("authenticate", "Authenticate with AWS STS", "failed", str(exc)))
        steps.append(VerifyStep("permission", "List the CUR bucket", "skipped", "Not attempted."))
        return VerifyResult(False, None, steps)
    steps.append(
        VerifyStep(
            "authenticate", "Authenticate with AWS STS", "ok", f"Signed in as {identity['arn']}."
        )
    )
    bucket = Bucket(str(config["bucket"]), str(config["region"]), credentials)
    prefix = _prefix(config)
    try:
        objects = list_objects(client, bucket, prefix)
    except ConnectorError as exc:
        steps.append(VerifyStep("permission", "List the CUR bucket", "failed", str(exc)))
        return VerifyResult(False, identity["arn"], steps)
    manifests = latest_manifests(objects)
    location = f"s3://{bucket.name}/{prefix}"
    if not manifests:
        steps.append(
            VerifyStep(
                "permission",
                "List the CUR bucket",
                "failed",
                f"{location} is readable but contains no CUR manifest yet.",
            )
        )
        return VerifyResult(False, identity["arn"], steps)
    newest = max(manifests)
    steps.append(
        VerifyStep(
            "permission",
            "List the CUR bucket",
            "ok",
            f"Found {len(manifests)} billing period(s) in {location}; newest {newest:%Y-%m}.",
        )
    )
    return VerifyResult(True, f"AWS account {identity['account']}", steps)
