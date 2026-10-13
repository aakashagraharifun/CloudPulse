"""The connector catalog: what each kind needs, how it is validated and run.

The catalog is also served to the dashboard, which renders the connect form
from it, so field definitions live in one place.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.models import ConnectorKind
from app.services.connectors import (
    anthropic_costs,
    aws_cost_explorer,
    aws_cur,
    openai_costs,
)
from app.services.connectors.base import FetchResult, VerifyResult

FieldType = Literal["text", "secret", "select", "number", "toggle"]


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    type: FieldType
    required: bool = False
    secret: bool = False
    help: str = ""
    placeholder: str = ""
    default: Any = None
    options: tuple[tuple[str, str], ...] = ()
    # Show only when another field has this value, e.g. ("group_by", "TAG").
    show_if: tuple[str, str] | None = None
    # "auth" fields identify the account; sandbox connectors do not use them.
    section: Literal["settings", "auth"] = "settings"


@dataclass(frozen=True)
class KindDef:
    kind: ConnectorKind
    provider: str
    name: str
    tagline: str
    auth: str
    docs_url: str
    fields: tuple[FieldDef, ...]
    permissions: tuple[str, ...]
    supports_lookback: bool
    config_model: type[BaseModel]
    secrets_model: type[BaseModel]
    verify: Callable[[httpx.Client, dict[str, str], dict[str, Any]], VerifyResult]
    notes: tuple[str, ...] = field(default=())


# --- validation models -------------------------------------------------------------

_ROLE_ARN = re.compile(r"^arn:aws[a-z-]*:iam::\d{12}:role/[\w+=,.@/-]{1,512}$")
_EXTERNAL_ID = re.compile(r"^[\w+=,.@:/-]{2,1224}$")
_BUCKET = re.compile(r"^(?!xn--)(?!.*\.\.)[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_REGION = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d{1,2}$")
_TAG_KEY = re.compile(r"^[\w.:+=@/-]{1,128}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AwsSecrets(_Strict):
    access_key_id: str = Field(pattern=r"^[A-Z0-9]{16,128}$")
    secret_access_key: str = Field(min_length=16, max_length=256)
    session_token: str | None = Field(None, max_length=4096)


class _ConnectorConfig(_Strict):
    # Set by the service from the credentials type, never trusted from input alone.
    sandbox: bool = False


class AwsRoleConfig(_ConnectorConfig):
    role_arn: str | None = None
    external_id: str | None = None

    @field_validator("role_arn")
    @classmethod
    def _role(cls, value: str | None) -> str | None:
        if value and not _ROLE_ARN.match(value):
            raise ValueError("must be an IAM role ARN, e.g. arn:aws:iam::123456789012:role/Name")
        return value or None

    @field_validator("external_id")
    @classmethod
    def _external(cls, value: str | None) -> str | None:
        if value and not _EXTERNAL_ID.match(value):
            raise ValueError("must be 2-1224 characters: letters, digits and +=,.@:/-")
        return value or None


class CostExplorerConfig(AwsRoleConfig):
    group_by: Literal["LINKED_ACCOUNT", "REGION", "USAGE_TYPE", "TAG"] = "LINKED_ACCOUNT"
    tag_key: str | None = None

    @model_validator(mode="after")
    def _tag(self) -> "CostExplorerConfig":
        if self.group_by == "TAG":
            if not self.tag_key or not _TAG_KEY.match(self.tag_key):
                raise ValueError("tag_key is required when grouping by a cost allocation tag")
        else:
            self.tag_key = None
        return self


class CurConfig(AwsRoleConfig):
    bucket: str
    region: str
    prefix: str = Field("", max_length=1024)
    billing_periods: int = Field(2, ge=1, le=12)
    include_resource_ids: bool = True
    project_tag_key: str = "project"
    environment_tag_key: str = "environment"

    @field_validator("bucket")
    @classmethod
    def _bucket(cls, value: str) -> str:
        if not _BUCKET.match(value):
            raise ValueError("is not a valid S3 bucket name")
        return value

    @field_validator("region")
    @classmethod
    def _region(cls, value: str) -> str:
        if not _REGION.match(value):
            raise ValueError("must be an AWS region code such as us-east-1")
        return value

    @field_validator("prefix")
    @classmethod
    def _prefix(cls, value: str) -> str:
        return value.strip("/")

    @field_validator("project_tag_key", "environment_tag_key")
    @classmethod
    def _tag_keys(cls, value: str) -> str:
        if not _TAG_KEY.match(value):
            raise ValueError("is not a valid tag key")
        return value


class AdminKeySecrets(_Strict):
    admin_key: str = Field(min_length=20, max_length=512, pattern=r"^\S+$")


class SandboxSecrets(_Strict):
    sandbox_token: str = Field(min_length=20, max_length=1024, pattern=r"^cpsbx_\S+$")


class OpenAIConfig(_ConnectorConfig):
    map_projects: bool = True


class AnthropicConfig(_ConnectorConfig):
    map_workspaces: bool = True


# --- catalog -------------------------------------------------------------------

_AWS_KEY_FIELDS = (
    FieldDef(
        "access_key_id",
        "Access key ID",
        "text",
        required=True,
        secret=True,
        placeholder="AKIA…",
        help=(
            "The public half of an AWS access key: 20 characters starting with AKIA "
            "(an IAM user) or ASIA (temporary). Create one in the AWS console under "
            "IAM → Users → Security credentials → Create access key, for a read-only user."
        ),
        section="auth",
    ),
    FieldDef(
        "secret_access_key",
        "Secret access key",
        "secret",
        required=True,
        secret=True,
        help="The private half, shown once when the access key is created.",
        section="auth",
    ),
    FieldDef(
        "session_token",
        "Session token",
        "secret",
        secret=True,
        help="Only for temporary credentials. They expire, so scheduled syncs will stop.",
        section="auth",
    ),
    FieldDef(
        "role_arn",
        "Role to assume",
        "text",
        placeholder="arn:aws:iam::123456789012:role/CloudPulseBilling",
        help="Recommended: a read-only role in the payer account, assumed with sts:AssumeRole.",
        section="auth",
    ),
    FieldDef(
        "external_id",
        "External ID",
        "text",
        help="Set when the role's trust policy requires one.",
        section="auth",
    ),
)

CATALOG: dict[ConnectorKind, KindDef] = {
    ConnectorKind.AWS_CUR_S3: KindDef(
        kind=ConnectorKind.AWS_CUR_S3,
        provider="aws",
        name="AWS Cost and Usage Report",
        tagline="Line-item billing from CUR files in S3: resources, tags and every account.",
        auth="IAM access key, optionally assuming a read-only role",
        docs_url="https://docs.aws.amazon.com/cur/latest/userguide/what-is-data-exports.html",
        fields=(
            FieldDef(
                "bucket", "S3 bucket", "text", required=True, placeholder="acme-billing-reports"
            ),
            FieldDef("region", "Bucket region", "text", required=True, default="us-east-1"),
            FieldDef(
                "prefix",
                "Report path prefix",
                "text",
                placeholder="cur/cloudpulse",
                help="The S3 path prefix plus the report or export name.",
            ),
            FieldDef(
                "billing_periods",
                "Billing months per sync",
                "number",
                default=2,
                help="The newest months are re-read each sync (AWS restates the current month).",
            ),
            FieldDef("include_resource_ids", "Include resource IDs", "toggle", default=True),
            FieldDef("project_tag_key", "Project tag key", "text", default="project"),
            FieldDef("environment_tag_key", "Environment tag key", "text", default="environment"),
            *_AWS_KEY_FIELDS,
        ),
        permissions=("s3:ListBucket", "s3:GetObject", "sts:AssumeRole (if a role is set)"),
        supports_lookback=False,
        config_model=CurConfig,
        secrets_model=AwsSecrets,
        verify=aws_cur.verify,
        notes=("Create the export with CSV format and GZIP compression; Parquet is not read.",),
    ),
    ConnectorKind.AWS_COST_EXPLORER: KindDef(
        kind=ConnectorKind.AWS_COST_EXPLORER,
        provider="aws",
        name="AWS Cost Explorer",
        tagline="Daily cost by service in minutes, with no export to set up.",
        auth="IAM access key, optionally assuming a read-only role",
        docs_url="https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetCostAndUsage.html",
        fields=(
            FieldDef(
                "group_by",
                "Second dimension",
                "select",
                default="LINKED_ACCOUNT",
                options=(
                    ("LINKED_ACCOUNT", "Linked account"),
                    ("REGION", "Region"),
                    ("USAGE_TYPE", "Usage type"),
                    ("TAG", "Cost allocation tag → project"),
                ),
                help="Cost Explorer groups by service plus one more dimension.",
            ),
            FieldDef(
                "tag_key", "Tag key", "text", placeholder="project", show_if=("group_by", "TAG")
            ),
            *_AWS_KEY_FIELDS,
        ),
        permissions=("ce:GetCostAndUsage", "sts:AssumeRole (if a role is set)"),
        supports_lookback=True,
        config_model=CostExplorerConfig,
        secrets_model=AwsSecrets,
        verify=aws_cost_explorer.verify,
        notes=("AWS bills each Cost Explorer API request (USD 0.01).",),
    ),
    ConnectorKind.OPENAI_COSTS: KindDef(
        kind=ConnectorKind.OPENAI_COSTS,
        provider="openai",
        name="OpenAI usage & costs",
        tagline="Daily organization spend by model, line item and project.",
        auth="Organization Admin API key (sk-admin-…)",
        docs_url="https://platform.openai.com/docs/api-reference/usage/costs",
        fields=(
            FieldDef(
                "admin_key",
                "Admin API key",
                "secret",
                required=True,
                secret=True,
                placeholder="sk-admin-…",
                help="Organization settings → Admin keys. Project API keys are rejected.",
                section="auth",
            ),
            FieldDef(
                "map_projects", "Use project names as CloudPulse projects", "toggle", default=True
            ),
        ),
        permissions=("Admin key: read organization costs and projects",),
        supports_lookback=True,
        config_model=OpenAIConfig,
        secrets_model=AdminKeySecrets,
        verify=openai_costs.verify,
    ),
    ConnectorKind.ANTHROPIC_COSTS: KindDef(
        kind=ConnectorKind.ANTHROPIC_COSTS,
        provider="anthropic",
        name="Anthropic Claude usage & costs",
        tagline="Daily Claude API spend by model, token type and workspace.",
        auth="Admin API key (sk-ant-admin…)",
        docs_url="https://platform.claude.com/docs/en/manage-claude/usage-cost-api",
        fields=(
            FieldDef(
                "admin_key",
                "Admin API key",
                "secret",
                required=True,
                secret=True,
                placeholder="sk-ant-admin01-…",
                help="Claude Console → Settings → Admin keys. Workspace API keys are rejected.",
                section="auth",
            ),
            FieldDef(
                "map_workspaces",
                "Use workspace names as CloudPulse projects",
                "toggle",
                default=True,
            ),
        ),
        permissions=("Admin key: GET /v1/organizations/me, /cost_report, /workspaces",),
        supports_lookback=True,
        config_model=AnthropicConfig,
        secrets_model=AdminKeySecrets,
        verify=anthropic_costs.verify,
        notes=("Priority Tier costs are not included in Anthropic's cost report.",),
    ),
}


class InvalidConnectorInput(ValueError):
    def __init__(self, details: list[dict[str, str]]) -> None:
        super().__init__("The connector settings are invalid.")
        self.details = details


def _validate(model: type[BaseModel], data: dict[str, Any], section: str) -> dict[str, Any]:
    try:
        return model.model_validate(data).model_dump()
    except ValidationError as exc:
        raise InvalidConnectorInput(
            [
                {
                    "location": ".".join([section, *(str(p) for p in err["loc"])]),
                    "message": err["msg"],
                }
                for err in exc.errors()
            ]
        ) from exc


def validate_config(kind: ConnectorKind, config: dict[str, Any]) -> dict[str, Any]:
    return _validate(CATALOG[kind].config_model, config, "config")


def is_sandbox(secrets: dict[str, Any]) -> bool:
    return "sandbox_token" in secrets


def validate_secrets(kind: ConnectorKind, secrets: dict[str, Any]) -> dict[str, Any]:
    model = SandboxSecrets if is_sandbox(secrets) else CATALOG[kind].secrets_model
    cleaned = _validate(model, secrets, "credentials")
    return {k: v for k, v in cleaned.items() if v not in (None, "")}


def secret_for_hint(kind: ConnectorKind, secrets: dict[str, Any]) -> str:
    return str(
        secrets.get("admin_key")
        or secrets.get("access_key_id")
        or secrets.get("sandbox_token")
        or ""
    )


def run_fetch(
    kind: ConnectorKind,
    client: httpx.Client,
    secrets: dict[str, str],
    config: dict[str, Any],
    *,
    start: date,
    end: date,
    max_rows: int,
    max_download_bytes: int,
) -> FetchResult:
    if kind == ConnectorKind.AWS_CUR_S3:
        return aws_cur.fetch(
            client,
            secrets,
            config,
            max_rows=max_rows,
            max_download_bytes=max_download_bytes,
            today=end,
        )
    module = {
        ConnectorKind.AWS_COST_EXPLORER: aws_cost_explorer,
        ConnectorKind.OPENAI_COSTS: openai_costs,
        ConnectorKind.ANTHROPIC_COSTS: anthropic_costs,
    }[kind]
    return module.fetch(client, secrets, config, start=start, end=end)
