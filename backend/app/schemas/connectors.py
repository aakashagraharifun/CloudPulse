"""Connector API schemas. Credentials are write-only: they are never returned."""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from app.schemas.common import APIModel

KindLiteral = Literal["aws_cur_s3", "aws_cost_explorer", "openai_costs", "anthropic_costs"]


class FieldOption(APIModel):
    value: str
    label: str


class CatalogField(APIModel):
    key: str
    label: str
    type: Literal["text", "secret", "select", "number", "toggle"]
    required: bool
    secret: bool
    help: str
    placeholder: str
    default: Any
    options: list[FieldOption]
    show_if: dict[str, str] | None
    section: Literal["settings", "auth"]


class CatalogEntry(APIModel):
    kind: KindLiteral
    provider: str
    name: str
    tagline: str
    auth: str
    docs_url: str
    permissions: list[str]
    notes: list[str]
    supports_lookback: bool
    fields: list[CatalogField]


class ConnectorCatalog(APIModel):
    encryption_configured: bool
    kinds: list[CatalogEntry]


class _ConnectorSettings(APIModel):
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    sync_interval_hours: int = Field(24, ge=0, le=168, description="0 = manual syncs only")
    lookback_days: int = Field(30, ge=1, le=365)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("name must not be blank")
        return value


class ConnectorCreate(_ConnectorSettings):
    kind: KindLiteral
    credentials: dict[str, Any]


class ConnectorUpdate(_ConnectorSettings):
    credentials: dict[str, Any] | None = Field(
        None, description="New credentials; omit to keep the stored ones."
    )


class ConnectorVerifyRequest(APIModel):
    kind: KindLiteral
    config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any]


class VerifyStepRead(APIModel):
    key: str
    label: str
    status: Literal["ok", "failed", "skipped"]
    detail: str


class VerifyResponse(APIModel):
    ok: bool
    identity: str | None
    steps: list[VerifyStepRead]


class ConnectorRead(APIModel):
    id: int
    kind: KindLiteral
    provider: str
    name: str
    enabled: bool
    # Simulated provider: syncs validate data but never import it.
    sandbox: bool
    config: dict[str, Any]
    credentials_hint: str
    sync_interval_hours: int
    lookback_days: int
    last_verified_at: datetime | None
    verified_identity: str | None
    last_sync_status: Literal["running", "succeeded", "failed"] | None
    last_sync_started_at: datetime | None
    last_sync_finished_at: datetime | None
    last_sync_message: str | None
    last_import_id: int | None
    next_sync_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SandboxAuthorizeRequest(APIModel):
    kind: KindLiteral


class SandboxAuthorizeResponse(APIModel):
    token: str
    identity: str
    expires_in_seconds: int


class SyncResponse(APIModel):
    connector: ConnectorRead
    status: Literal["succeeded", "failed"]
    message: str
    changed: bool
    import_id: int | None
