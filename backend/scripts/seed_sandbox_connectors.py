"""Add sandbox (simulated) Claude and AWS connectors and run their first sync.

Sandbox connectors exercise the whole connector flow without provider accounts;
their syncs validate simulated data but never import billing data. Connectors
that already exist (same name) are left alone, so the script is safe to re-run.

Usage (from the backend directory, with the virtualenv active):
    python -m scripts.seed_sandbox_connectors
In Docker:
    docker compose exec api python -m scripts.seed_sandbox_connectors
"""

import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.models import Connector, ConnectorKind, User, UserRole
from app.services.audit import record_audit
from app.services.connectors import service

SANDBOX_CONNECTORS = (
    (
        ConnectorKind.ANTHROPIC_COSTS,
        "Claude (sandbox)",
        {"map_workspaces": True},
        {"sync_interval_hours": 6, "lookback_days": 30},
    ),
    (
        ConnectorKind.AWS_COST_EXPLORER,
        "AWS Cost Explorer (sandbox)",
        {"group_by": "LINKED_ACCOUNT"},
        {"sync_interval_hours": 24, "lookback_days": 30},
    ),
)


def main() -> int:
    settings = get_settings()
    with get_sessionmaker()() as db:
        admin = db.scalar(
            select(User)
            .where(User.role == UserRole.ADMIN, User.is_active.is_(True))
            .order_by(User.id)
        )
        if admin is None:
            print("No active admin exists yet; finish first-run setup in the dashboard first.")
            return 1
        for kind, name, config, schedule in SANDBOX_CONNECTORS:
            if db.scalar(select(Connector).where(Connector.name == name)) is not None:
                print(f"{name}: already exists, skipped")
                continue
            token, _ = service.issue_sandbox_token(settings, kind)
            connector = service.create_connector(
                db,
                settings,
                kind=kind,
                name=name,
                config=config,
                credentials={"sandbox_token": token},
                enabled=True,
                user=admin,
                **schedule,
            )
            record_audit(
                db,
                "connector.created",
                actor=admin,
                target_type="connector",
                target_id=connector.id,
                details={"name": name, "kind": kind.value, "via": "seed_sandbox_connectors"},
            )
            db.commit()
            outcome = service.sync_connector(db, settings, connector.id)
            print(f"{name}: created (id {connector.id}); first sync {outcome.status}")
            print(f"  {outcome.message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
