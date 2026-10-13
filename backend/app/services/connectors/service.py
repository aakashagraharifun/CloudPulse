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
from app.services.connectors.base import (
    ConnectorError,
    VerifyResult,
    build_http_client,
    rows_to_csv,
)
from app.services.connectors.registry import (
    CATALOG,
    run_fetch,
    secret_for_hint,
    validate_config,
    validate_secrets,
)
from app.services.ingestion.service import ReplaceScope, import_billing_file

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
    connector = Connector(
        kind=kind,
        name=name,
        enabled=enabled,
        config=clean_config,
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
    connector.config = validate_config(kind, config)
    connector.name = name
    connector.enabled = enabled
    connector.sync_interval_hours = sync_interval_hours
    connector.lookback_days = lookback_days
    if credentials:
        secrets = validate_secrets(kind, credentials)
        connector.credentials_encrypted = encrypt_json(settings, secrets)
        connector.credentials_hint = mask_secret(secret_for_hint(kind, secrets))
        connector.last_verified_at = None
        connector.verified_identity = None
        return True
    return False


def verify_credentials(
    settings: Settings, kind: ConnectorKind, config: dict[str, Any], secrets: dict[str, Any]
) -> VerifyResult:
    with http_client_factory(settings) as client:
        return CATALOG[kind].verify(client, secrets, config)


def verify_connector(db: Session, settings: Settings, connector: Connector) -> VerifyResult:
    secrets = decrypt_json(settings, connector.credentials_encrypted)
    result = verify_credentials(settings, ConnectorKind(connector.kind), connector.config, secrets)
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
