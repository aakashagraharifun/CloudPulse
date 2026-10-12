"""Allocation rules: attribute untagged costs to projects and environments."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.models import AllocationRule, User
from app.schemas.common import APIModel
from app.services.audit import record_audit
from app.services.normalization.allocation import reapply_allocation_rules

router = APIRouter(prefix="/allocation-rules", tags=["allocation rules"])

MatchFieldLiteral = Literal[
    "provider", "account_id", "service", "resource_id", "region", "usage_type"
]


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class AllocationRuleInput(APIModel):
    name: str = Field(min_length=1, max_length=120)
    match_field: MatchFieldLiteral
    match_operator: Literal["equals", "prefix", "contains"]
    match_value: str = Field(min_length=1, max_length=512)
    project: str | None = Field(None, max_length=128)
    environment: str | None = Field(None, max_length=128)
    priority: int = Field(100, ge=0, le=10_000)
    enabled: bool = True

    @model_validator(mode="after")
    def _requires_assignment(self) -> "AllocationRuleInput":
        self.name = self.name.strip()
        self.match_value = self.match_value.strip()
        self.project = _blank_to_none(self.project)
        self.environment = _blank_to_none(self.environment)
        if not self.name or not self.match_value:
            raise ValueError("name and match_value must not be blank")
        if self.project is None and self.environment is None:
            raise ValueError("A rule must assign a project, an environment, or both.")
        return self


class AllocationRuleRead(AllocationRuleInput):
    id: int
    created_at: datetime
    updated_at: datetime


class AllocationRuleMutation(APIModel):
    rule: AllocationRuleRead | None
    records_updated: int


@router.get("", response_model=list[AllocationRuleRead], summary="List allocation rules")
def list_rules(db: Session = Depends(get_db)) -> list[AllocationRuleRead]:
    rules = db.scalars(
        select(AllocationRule).order_by(AllocationRule.priority, AllocationRule.id)
    ).all()
    return [AllocationRuleRead.model_validate(rule) for rule in rules]


@router.post(
    "",
    response_model=AllocationRuleMutation,
    status_code=status.HTTP_201_CREATED,
    summary="Create a rule and re-attribute existing records",
)
def create_rule(
    payload: AllocationRuleInput,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> AllocationRuleMutation:
    rule = AllocationRule(**payload.model_dump())
    db.add(rule)
    db.flush()
    record_audit(
        db,
        "allocation_rule.created",
        actor=user,
        request=request,
        target_type="allocation_rule",
        target_id=rule.id,
        details=payload.model_dump(),
    )
    db.commit()
    updated = reapply_allocation_rules(db)
    return AllocationRuleMutation(
        rule=AllocationRuleRead.model_validate(rule), records_updated=updated
    )


@router.put(
    "/{rule_id}",
    response_model=AllocationRuleMutation,
    summary="Replace a rule and re-attribute existing records",
)
def update_rule(
    rule_id: int,
    payload: AllocationRuleInput,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> AllocationRuleMutation:
    rule = db.get(AllocationRule, rule_id)
    if rule is None:
        raise NotFoundError("Allocation rule", rule_id)
    for key, value in payload.model_dump().items():
        setattr(rule, key, value)
    record_audit(
        db,
        "allocation_rule.updated",
        actor=user,
        request=request,
        target_type="allocation_rule",
        target_id=rule_id,
        details=payload.model_dump(),
    )
    db.commit()
    db.refresh(rule)
    updated = reapply_allocation_rules(db)
    return AllocationRuleMutation(
        rule=AllocationRuleRead.model_validate(rule), records_updated=updated
    )


@router.delete(
    "/{rule_id}",
    response_model=AllocationRuleMutation,
    summary="Delete a rule and re-attribute existing records",
    responses={404: {"description": "Rule not found"}},
)
def delete_rule(
    rule_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> AllocationRuleMutation:
    rule = db.get(AllocationRule, rule_id)
    if rule is None:
        raise NotFoundError("Allocation rule", rule_id)
    db.delete(rule)
    record_audit(
        db,
        "allocation_rule.deleted",
        actor=user,
        request=request,
        target_type="allocation_rule",
        target_id=rule_id,
        details={"name": rule.name},
    )
    db.commit()
    return AllocationRuleMutation(rule=None, records_updated=reapply_allocation_rules(db))
