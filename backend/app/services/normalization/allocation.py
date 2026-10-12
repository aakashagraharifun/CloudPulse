"""Apply allocation rules to compute each record's effective project/environment."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import AllocationRule, BillingRecord

REAPPLY_BATCH_SIZE = 5000


@dataclass(frozen=True)
class CompiledRule:
    field: str
    operator: str
    value: str  # lower-cased; matching is case-insensitive
    project: str | None
    environment: str | None

    def matches(self, record: Mapping[str, Any]) -> bool:
        candidate = record.get(self.field)
        if not candidate:
            return False
        candidate = str(candidate).lower()
        if self.operator == "equals":
            return candidate == self.value
        if self.operator == "prefix":
            return candidate.startswith(self.value)
        return self.value in candidate


class AllocationEngine:
    def __init__(self, rules: list[CompiledRule]) -> None:
        self.rules = rules

    @classmethod
    def load(cls, db: Session) -> "AllocationEngine":
        rows = db.scalars(
            select(AllocationRule)
            .where(AllocationRule.enabled.is_(True))
            .order_by(AllocationRule.priority, AllocationRule.id)
        ).all()
        return cls(
            [
                CompiledRule(
                    r.match_field, r.match_operator, r.match_value.lower(), r.project, r.environment
                )
                for r in rows
            ]
        )

    def attribute(self, record: Mapping[str, Any]) -> tuple[str | None, str | None]:
        """Return (project, environment): source tags first, then the first matching rules."""
        project = record.get("project_tag") or None
        environment = record.get("environment_tag") or None
        for rule in self.rules:
            if project is not None and environment is not None:
                break
            needs_project = project is None and rule.project is not None
            needs_environment = environment is None and rule.environment is not None
            if (needs_project or needs_environment) and rule.matches(record):
                if needs_project:
                    project = rule.project
                if needs_environment:
                    environment = rule.environment
        return project, environment


def reapply_allocation_rules(db: Session) -> int:
    """Recompute effective attribution for all records. Returns the number changed."""
    engine = AllocationEngine.load(db)
    columns = (
        BillingRecord.id,
        BillingRecord.provider,
        BillingRecord.account_id,
        BillingRecord.service,
        BillingRecord.resource_id,
        BillingRecord.region,
        BillingRecord.usage_type,
        BillingRecord.project_tag,
        BillingRecord.environment_tag,
        BillingRecord.project,
        BillingRecord.environment,
    )
    changes: list[dict[str, Any]] = []
    changed = 0
    last_id = 0
    while True:
        batch = (
            db.execute(
                select(*columns)
                .where(BillingRecord.id > last_id)
                .order_by(BillingRecord.id)
                .limit(REAPPLY_BATCH_SIZE)
            )
            .mappings()
            .all()
        )
        if not batch:
            break
        last_id = batch[-1]["id"]
        for row in batch:
            project, environment = engine.attribute(row)
            if project != row["project"] or environment != row["environment"]:
                changes.append({"id": row["id"], "project": project, "environment": environment})
        if changes:
            db.execute(update(BillingRecord), changes)
            changed += len(changes)
            changes = []
    db.commit()
    return changed
