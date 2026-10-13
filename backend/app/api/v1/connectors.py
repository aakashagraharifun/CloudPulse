"""Live billing connectors: catalog, configuration, verification and syncs."""

from dataclasses import asdict
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_member
from app.core.config import Settings, get_settings
from app.core.crypto import encryption_configured
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Connector, ConnectorKind, User
from app.schemas.connectors import (
    CatalogEntry,
    CatalogField,
    ConnectorCatalog,
    ConnectorCreate,
    ConnectorRead,
    ConnectorUpdate,
    ConnectorVerifyRequest,
    FieldOption,
    SandboxAuthorizeRequest,
    SandboxAuthorizeResponse,
    SyncResponse,
    VerifyResponse,
    VerifyStepRead,
)
from app.services.audit import record_audit
from app.services.connectors import service
from app.services.connectors.base import VerifyResult
from app.services.connectors.registry import (
    CATALOG,
    InvalidConnectorInput,
    validate_config,
    validate_secrets,
)
from app.services.pipeline import run_post_import_evaluation

router = APIRouter(prefix="/connectors", tags=["connectors"])


def _invalid(exc: InvalidConnectorInput) -> AppError:
    return AppError(str(exc), code="validation_error", status_code=422, details=exc.details)


def _read(connector: Connector) -> ConnectorRead:
    next_sync = None
    if connector.enabled and connector.sync_interval_hours > 0:
        if connector.last_sync_started_at is None:
            next_sync = connector.created_at
        else:
            next_sync = connector.last_sync_started_at + timedelta(
                hours=connector.sync_interval_hours
            )
    return ConnectorRead(
        id=connector.id,
        kind=connector.kind,  # type: ignore[arg-type]
        provider=CATALOG[ConnectorKind(connector.kind)].provider,
        name=connector.name,
        enabled=connector.enabled,
        sandbox=bool(connector.config.get("sandbox")),
        config=connector.config,
        credentials_hint=connector.credentials_hint,
        sync_interval_hours=connector.sync_interval_hours,
        lookback_days=connector.lookback_days,
        last_verified_at=connector.last_verified_at,
        verified_identity=connector.verified_identity,
        last_sync_status=connector.last_sync_status,  # type: ignore[arg-type]
        last_sync_started_at=connector.last_sync_started_at,
        last_sync_finished_at=connector.last_sync_finished_at,
        last_sync_message=connector.last_sync_message,
        last_import_id=connector.last_import_id,
        next_sync_at=next_sync,
        created_at=connector.created_at,
        updated_at=connector.updated_at,
    )


def _verify_response(result: VerifyResult) -> VerifyResponse:
    return VerifyResponse(
        ok=result.ok,
        identity=result.identity,
        steps=[VerifyStepRead(**asdict(step)) for step in result.steps],
    )


@router.get("/catalog", response_model=ConnectorCatalog, summary="Available connector types")
def catalog(settings: Settings = Depends(get_settings)) -> ConnectorCatalog:
    return ConnectorCatalog(
        encryption_configured=encryption_configured(settings),
        kinds=[
            CatalogEntry(
                kind=entry.kind.value,  # type: ignore[arg-type]
                provider=entry.provider,
                name=entry.name,
                tagline=entry.tagline,
                auth=entry.auth,
                docs_url=entry.docs_url,
                permissions=list(entry.permissions),
                notes=list(entry.notes),
                supports_lookback=entry.supports_lookback,
                fields=[
                    CatalogField(
                        key=f.key,
                        label=f.label,
                        type=f.type,
                        required=f.required,
                        secret=f.secret,
                        help=f.help,
                        placeholder=f.placeholder,
                        default=f.default,
                        options=[FieldOption(value=v, label=label) for v, label in f.options],
                        show_if={"key": f.show_if[0], "value": f.show_if[1]} if f.show_if else None,
                        section=f.section,
                    )
                    for f in entry.fields
                ],
            )
            for entry in CATALOG.values()
        ],
    )


@router.get("", response_model=list[ConnectorRead], summary="List connectors")
def list_connectors(db: Session = Depends(get_db)) -> list[ConnectorRead]:
    return [_read(c) for c in service.list_connectors(db)]


@router.get("/{connector_id}", response_model=ConnectorRead, summary="Get a connector")
def get_connector(connector_id: int, db: Session = Depends(get_db)) -> ConnectorRead:
    return _read(service.get_connector(db, connector_id))


@router.post(
    "/verify",
    response_model=VerifyResponse,
    summary="Check credentials before saving them (nothing is stored)",
)
def verify_unsaved(
    payload: ConnectorVerifyRequest,
    settings: Settings = Depends(get_settings),
    _: User = Depends(require_admin),
) -> VerifyResponse:
    kind = ConnectorKind(payload.kind)
    try:
        config = validate_config(kind, payload.config)
        secrets = validate_secrets(kind, payload.credentials)
    except InvalidConnectorInput as exc:
        raise _invalid(exc) from exc
    return _verify_response(service.verify_credentials(settings, kind, config, secrets))


@router.post(
    "/sandbox/authorize",
    response_model=SandboxAuthorizeResponse,
    summary="Authorize a simulated provider account (mock consent; returns a sandbox token)",
)
def authorize_sandbox(
    payload: SandboxAuthorizeRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(require_admin),
) -> SandboxAuthorizeResponse:
    kind = ConnectorKind(payload.kind)
    token, identity = service.issue_sandbox_token(settings, kind)
    record_audit(
        db,
        "connector.sandbox_authorized",
        actor=user,
        request=request,
        target_type="connector",
        details={"kind": kind.value},
    )
    db.commit()
    return SandboxAuthorizeResponse(
        token=token,
        identity=identity,
        expires_in_seconds=service.sandbox.TOKEN_TTL_SECONDS,
    )


@router.post(
    "",
    response_model=ConnectorRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a connector (credentials are encrypted at rest)",
)
def create_connector(
    payload: ConnectorCreate,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(require_admin),
) -> ConnectorRead:
    try:
        connector = service.create_connector(
            db,
            settings,
            kind=ConnectorKind(payload.kind),
            name=payload.name,
            config=payload.config,
            credentials=payload.credentials,
            enabled=payload.enabled,
            sync_interval_hours=payload.sync_interval_hours,
            lookback_days=payload.lookback_days,
            user=user,
        )
    except InvalidConnectorInput as exc:
        raise _invalid(exc) from exc
    record_audit(
        db,
        "connector.created",
        actor=user,
        request=request,
        target_type="connector",
        target_id=connector.id,
        details={"name": connector.name, "kind": connector.kind},
    )
    db.commit()
    db.refresh(connector)
    return _read(connector)


@router.put("/{connector_id}", response_model=ConnectorRead, summary="Update a connector")
def update_connector(
    connector_id: int,
    payload: ConnectorUpdate,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(require_admin),
) -> ConnectorRead:
    connector = service.get_connector(db, connector_id)
    try:
        replaced = service.update_connector(
            db,
            settings,
            connector,
            name=payload.name,
            config=payload.config,
            credentials=payload.credentials,
            enabled=payload.enabled,
            sync_interval_hours=payload.sync_interval_hours,
            lookback_days=payload.lookback_days,
        )
    except InvalidConnectorInput as exc:
        raise _invalid(exc) from exc
    record_audit(
        db,
        "connector.updated",
        actor=user,
        request=request,
        target_type="connector",
        target_id=connector_id,
        details={
            "name": connector.name,
            "enabled": connector.enabled,
            "sync_interval_hours": connector.sync_interval_hours,
            "lookback_days": connector.lookback_days,
            "credentials_replaced": replaced,
        },
    )
    db.commit()
    db.refresh(connector)
    return _read(connector)


@router.delete(
    "/{connector_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a connector (imported billing data is kept)",
)
def delete_connector(
    connector_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> Response:
    connector = service.get_connector(db, connector_id)
    details = {"name": connector.name, "kind": connector.kind}
    db.delete(connector)
    record_audit(
        db,
        "connector.deleted",
        actor=user,
        request=request,
        target_type="connector",
        target_id=connector_id,
        details=details,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{connector_id}/test",
    response_model=VerifyResponse,
    summary="Verify the stored credentials against the provider",
)
def test_connector(
    connector_id: int,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(require_admin),
) -> VerifyResponse:
    connector = service.get_connector(db, connector_id)
    result = service.verify_connector(db, settings, connector)
    record_audit(
        db,
        "connector.tested",
        actor=user,
        request=request,
        target_type="connector",
        target_id=connector_id,
        details={"ok": result.ok},
    )
    db.commit()
    return _verify_response(result)


@router.post(
    "/{connector_id}/sync",
    response_model=SyncResponse,
    summary="Pull the latest costs from the provider now",
    responses={409: {"description": "A sync of this connector is already running."}},
)
def sync_connector(
    connector_id: int,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(require_member),
) -> SyncResponse:
    service.get_connector(db, connector_id)
    outcome = service.sync_connector(db, settings, connector_id)
    import_id = (
        outcome.billing_import.id
        if outcome.billing_import is not None and outcome.changed
        else None
    )
    record_audit(
        db,
        "connector.synced",
        actor=user,
        request=request,
        target_type="connector",
        target_id=connector_id,
        details={"status": outcome.status, "import_id": import_id, "message": outcome.message},
    )
    db.commit()
    if outcome.changed and outcome.status == "succeeded":
        run_post_import_evaluation(db)
    db.refresh(outcome.connector)
    return SyncResponse(
        connector=_read(outcome.connector),
        status=outcome.status,  # type: ignore[arg-type]
        message=outcome.message,
        changed=outcome.changed,
        import_id=import_id,
    )
