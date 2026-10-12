"""Helpers that insert billing data directly for analytics/detection tests."""

import hashlib
import itertools
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import BillingImport, BillingRecord

_counter = itertools.count()


def make_import(db: Session, source: str = "upload") -> BillingImport:
    n = next(_counter)
    billing_import = BillingImport(
        filename=f"test-{n}.csv",
        source=source,
        file_sha256=hashlib.sha256(str(n).encode()).hexdigest(),
        file_size_bytes=1,
        status="completed",
    )
    db.add(billing_import)
    db.flush()
    return billing_import


def add_cost(
    db: Session,
    billing_import: BillingImport,
    day: date,
    cost: str | Decimal | float,
    *,
    service: str = "EC2",
    currency: str = "USD",
    provider: str = "aws",
    resource_id: str | None = None,
    region: str | None = None,
    usage_type: str | None = None,
    usage_quantity: str | Decimal | None = None,
    project: str | None = None,
    environment: str | None = None,
) -> BillingRecord:
    n = next(_counter)
    record = BillingRecord(
        import_id=billing_import.id,
        usage_date=day,
        provider=provider,
        service=service,
        resource_id=resource_id,
        region=region,
        usage_type=usage_type,
        usage_quantity=None if usage_quantity is None else Decimal(str(usage_quantity)),
        currency=currency,
        cost=Decimal(str(cost)),
        project_tag=project,
        environment_tag=environment,
        project=project,
        environment=environment,
        source_row_number=n,
        fingerprint=hashlib.sha256(f"record-{n}".encode()).hexdigest(),
    )
    db.add(record)
    return record


def add_daily_series(
    db: Session,
    billing_import: BillingImport,
    start: date,
    values: list[str | float | Decimal | None],
    **kwargs,
) -> None:
    """One record per day starting at `start`; None skips the day (missing data)."""
    for offset, value in enumerate(values):
        if value is not None:
            add_cost(db, billing_import, start + timedelta(days=offset), value, **kwargs)
