"""Connector lifecycle: store (encrypted), verify, and sync into CloudPulse.

A sync fetches the provider's data for the connector's window, writes it as a
canonical CSV and imports it with `ReplaceScope`, so it gets the same
validation, allocation rules and duplicate protection as an upload, and a
re-sync reconciles restated days instead of double-counting them.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.crypto import decrypt_json, encrypt_json, mask_secret
from app.core.errors import AppError, ConflictError, NotFoundError
from app.models import (
    BillingImport,
    Connector,
    ConnectorKind,
    ImportSource,
    ImportStatus,
    SyncStatus,
    User,
)
from app.services.connectors import sandbox
from app.services.connectors.base import (
    ConnectorError,
    VerifyResult,
    build_http_client,
    rows_to_csv,
)
from app.services.connectors.registry import (
    CATALOG,
    is_sandbox,
    run_fetch,
    secret_for_hint,
    validate_config,
    validate_secrets,
)
from app.services.ingestion.service import ReplaceScope, import_billing_file
from app.services.normalization.normalizer import FileValidationError, normalize_csv

logger = logging.getLogger(__name__)

# A sync that has been "running" longer than this is assumed to have crashed.
STALE_SYNC_AFTER = timedelta(hours=1)
# Tests replace this to inject an httpx.MockTransport.
http_client_factory: Callable[[Settings], httpx.Client] = lambda settings: build_http_client(  # noqa: E731
    settings.connector_timeout_seconds
)


@dataclass
class SyncOutcome:
    connector: Connector
    status: str
    message: str
    billing_import: BillingImport | None
    changed: bool


def _check_sandbox(settings: Settings, kind: ConnectorKind, secrets: dict, *, fresh: bool) -> None:
    try:
        sandbox.check_token(settings, secrets["sandbox_token"], kind, fresh=fresh)
    except sandbox.InvalidSandboxToken as exc:
        raise AppError(str(exc), code="invalid_sandbox_token", status_code=422) from exc


def issue_sandbox_token(settings: Settings, kind: ConnectorKind) -> tuple[str, str]:
    """A fresh sandbox token and the simulated account it stands for."""
    return sandbox.issue_token(settings, kind), sandbox.IDENTITY[kind]


def get_connector(db: Session, connector_id: int) -> Connector:
    connector = db.get(Connector, connector_id)
    if connector is None:
        raise NotFoundError("Connector", connector_id)
    return connector


def list_connectors(db: Session) -> list[Connector]:
    return list(db.scalars(select(Connector).order_by(Connector.id)))


def create_connector(
    db: Session,
    settings: Settings,
    *,
    kind: ConnectorKind,
    name: str,
    config: dict[str, Any],
    credentials: dict[str, Any],
    enabled: bool,
    sync_interval_hours: int,
    lookback_days: int,
    user: User,
) -> Connector:
    clean_config = validate_config(kind, config)
    secrets = validate_secrets(kind, credentials)
    clean_config["sandbox"] = is_sandbox(secrets)
    identity = None
    if clean_config["sandbox"]:
        _check_sandbox(settings, kind, secrets, fresh=True)
        identity = sandbox.IDENTITY[kind]
    connector = Connector(
        kind=kind,
        name=name,
        enabled=enabled,
        config=clean_config,
        # A sandbox token is verified by construction: CloudPulse issued it.
        verified_identity=identity,
        last_verified_at=datetime.now(UTC) if identity else None,
        credentials_encrypted=encrypt_json(settings, secrets),
        credentials_hint=mask_secret(secret_for_hint(kind, secrets)),
        sync_interval_hours=sync_interval_hours,
        lookback_days=lookback_days,
        created_by_id=user.id,
    )
    db.add(connector)
    db.flush()
    return connector


def update_connector(
    db: Session,
    settings: Settings,
    connector: Connector,
    *,
    name: str,
    config: dict[str, Any],
    credentials: dict[str, Any] | None,
    enabled: bool,
    sync_interval_hours: int,
    lookback_days: int,
) -> bool:
    """Apply changes; returns True when the credentials were replaced."""
    kind = ConnectorKind(connector.kind)
    clean_config = validate_config(kind, config)
    was_sandbox = bool(connector.config.get("sandbox"))
    secrets = validate_secrets(kind, credentials) if credentials else None
    clean_config["sandbox"] = is_sandbox(secrets) if secrets is not None else was_sandbox
    if secrets is not None and clean_config["sandbox"]:
        _check_sandbox(settings, kind, secrets, fresh=True)
    connector.config = clean_config
    connector.name = name
    connector.enabled = enabled
    connector.sync_interval_hours = sync_interval_hours
    connector.lookback_days = lookback_days
    if secrets is not None:
        connector.credentials_encrypted = encrypt_json(settings, secrets)
        connector.credentials_hint = mask_secret(secret_for_hint(kind, secrets))
        sandboxed = clean_config["sandbox"]
        connector.last_verified_at = datetime.now(UTC) if sandboxed else None
        connector.verified_identity = sandbox.IDENTITY[kind] if sandboxed else None
        return True
    return False


def verify_credentials(
    settings: Settings,
    kind: ConnectorKind,
    config: dict[str, Any],
    secrets: dict[str, Any],
    *,
    fresh: bool = True,
) -> VerifyResult:
    if is_sandbox(secrets):
        _check_sandbox(settings, kind, secrets, fresh=fresh)
        return sandbox.verify(kind)
    with http_client_factory(settings) as client:
        return CATALOG[kind].verify(client, secrets, config)


def verify_connector(db: Session, settings: Settings, connector: Connector) -> VerifyResult:
    secrets = decrypt_json(settings, connector.credentials_encrypted)
    result = verify_credentials(
        settings, ConnectorKind(connector.kind), connector.config, secrets, fresh=False
    )
    if result.ok:
        connector.last_verified_at = datetime.now(UTC)
        connector.verified_identity = (result.identity or "")[:255] or None
    return result


def sync_window(connector: Connector, today: date) -> tuple[date, date]:
    return today - timedelta(days=connector.lookback_days - 1), today


def _claim(db: Session, connector_id: int) -> Connector:
    """Mark the connector as syncing; refuse if another sync is in progress."""
    connector = db.get(Connector, connector_id, with_for_update=True)
    if connector is None:
        raise NotFoundError("Connector", connector_id)
    now = datetime.now(UTC)
    if (
        connector.last_sync_status == SyncStatus.RUNNING
        and connector.last_sync_started_at is not None
        and now - connector.last_sync_started_at < STALE_SYNC_AFTER
    ):
        db.rollback()
        raise ConflictError("A sync of this connector is already running.")
    connector.last_sync_status = SyncStatus.RUNNING
    connector.last_sync_started_at = now
    connector.last_sync_message = None
    db.commit()
    return connector


def _finish(
    db: Session,
    connector: Connector,
    status: SyncStatus,
    message: str,
    billing_import: BillingImport | None = None,
    changed: bool = False,
) -> SyncOutcome:
    connector.last_sync_status = status
    connector.last_sync_finished_at = datetime.now(UTC)
    connector.last_sync_message = message[:2000]
    if billing_import is not None and billing_import.id is not None and changed:
        connector.last_import_id = billing_import.id
    db.commit()
    logger.info(
        "Connector sync finished",
        extra={"context": {"connector_id": connector.id, "status": status, "message": message}},
    )
    return SyncOutcome(connector, status, message, billing_import, changed)


def sync_connector(
    db: Session, settings: Settings, connector_id: int, *, today: date | None = None
) -> SyncOutcome:
    connector = _claim(db, connector_id)
    kind = ConnectorKind(connector.kind)
    today = today or datetime.now(UTC).date()
    start, end = sync_window(connector, today)
    if connector.config.get("sandbox"):
        return _sandbox_sync(db, settings, connector, kind, start, end)
    try:
        secrets = decrypt_json(settings, connector.credentials_encrypted)
        with http_client_factory(settings) as client:
            fetched = run_fetch(
                kind,
                client,
                secrets,
                connector.config,
                start=start,
                end=end,
                max_rows=settings.max_upload_rows,
                max_download_bytes=settings.connector_max_download_bytes,
            )
    except ConnectorError as exc:
        return _finish(db, connector, SyncStatus.FAILED, str(exc))
    except AppError as exc:  # e.g. credentials that no longer decrypt
        return _finish(db, connector, SyncStatus.FAILED, exc.message)
    except Exception:  # never leave the connector stuck in "running"
        db.rollback()
        logger.exception(
            "Connector sync crashed", extra={"context": {"connector_id": connector_id}}
        )
        return _finish(
            db, connector, SyncStatus.FAILED, "An unexpected error occurred during the sync."
        )

    notes = " ".join(fetched.notes)
    if not fetched.rows:
        # An empty answer may be transient; keep the existing data rather than delete it.
        message = "The provider reported no costs for the sync window; nothing was changed."
        return _finish(db, connector, SyncStatus.SUCCEEDED, f"{message} {notes}".strip())

    try:
        billing_import = import_billing_file(
            db,
            filename=fetched.filename,
            content=rows_to_csv(fetched.rows),
            settings=settings,
            source=ImportSource.CONNECTOR,
            # Window ends are inclusive and may be today; allow today's partial data.
            today=today,
            replace=ReplaceScope(connector.id, tuple(fetched.ranges)),
            detected_format=fetched.detected_format,
        )
    except Exception:
        db.rollback()
        logger.exception(
            "Connector import crashed", extra={"context": {"connector_id": connector_id}}
        )
        return _finish(db, connector, SyncStatus.FAILED, "The synced data could not be imported.")
    if billing_import.status == ImportStatus.FAILED:
        message = f"The provider's data failed validation: {billing_import.error_summary}"
        return _finish(db, connector, SyncStatus.FAILED, message, billing_import, changed=True)

    changed = billing_import.rows_inserted > 0 or billing_import.rows_replaced > 0
    if not changed:
        # Nothing new: drop the empty import so scheduled syncs don't clutter the history.
        db.delete(billing_import)
        db.commit()
        message = f"Up to date: {len(fetched.rows):,} cost lines unchanged."
        return _finish(db, connector, SyncStatus.SUCCEEDED, f"{message} {notes}".strip())

    message = (
        f"{billing_import.rows_inserted:,} new or updated, "
        f"{billing_import.rows_duplicate:,} unchanged, "
        f"{billing_import.rows_replaced:,} stale removed "
        f"({billing_import.date_start} to {billing_import.date_end})."
    )
    return _finish(
        db, connector, SyncStatus.SUCCEEDED, f"{message} {notes}".strip(), billing_import, True
    )


def _sandbox_sync(
    db: Session,
    settings: Settings,
    connector: Connector,
    kind: ConnectorKind,
    start: date,
    end: date,
) -> SyncOutcome:
    """Fetch from the simulated API and validate like a real import, but write nothing."""
    try:
        fetched = sandbox.fetch(kind, connector.config, start=start, end=end)
        result = normalize_csv(
            rows_to_csv(fetched.rows),
            max_rows=settings.max_upload_rows,
            max_errors=settings.max_reported_errors,
            today=end,
        )
    except (ConnectorError, FileValidationError) as exc:
        return _finish(db, connector, SyncStatus.FAILED, f"Sandbox sync failed: {exc}")
    if not result.is_valid:
        return _finish(
            db,
            connector,
            SyncStatus.FAILED,
            f"Sandbox data failed validation ({result.error_count}).",
        )
    total = sum((r.cost for r in result.records), start=Decimal(0))
    first, last = fetched.ranges[0][0], fetched.ranges[-1][1]
    message = (
        f"Sandbox sync: the simulated API returned {len(result.records):,} cost lines "
        f"(USD {total:,.2f}) for {first} to {last}, and all passed validation. "
        "Sandbox connectors never write billing data."
    )
    return _finish(db, connector, SyncStatus.SUCCEEDED, message)


def due_connectors(db: Session, now: datetime | None = None) -> list[int]:
    now = now or datetime.now(UTC)
    due = []
    for connector in db.scalars(
        select(Connector).where(Connector.enabled.is_(True), Connector.sync_interval_hours > 0)
    ):
        last = connector.last_sync_started_at
        if last is None or now - last >= timedelta(hours=connector.sync_interval_hours):
            due.append(connector.id)
    return due
