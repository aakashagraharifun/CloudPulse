"""Budgets: CRUD, live utilization and threshold-alert history."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_member
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.models import Budget, BudgetAlert, User
from app.schemas.anomalies import ScopeLiteral
from app.schemas.common import APIModel, Money, Page
from app.services.audit import record_audit
from app.services.budgeting.service import budget_status, evaluate_budgets

router = APIRouter(prefix="/budgets", tags=["budgets"])


class BudgetInput(APIModel):
    name: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(gt=0, le=Decimal("9999999999"), decimal_places=2)
    currency: str = Field(pattern="^[A-Za-z]{3}$")
    period: Literal["monthly", "quarterly", "yearly"] = "monthly"
    scope_type: ScopeLiteral = "total"
    scope_value: str = Field("", max_length=512)
    thresholds: list[int] = Field(
        default_factory=lambda: [50, 80, 100], min_length=1, max_length=10
    )
    renotify_hours: int | None = Field(None, ge=1, le=24 * 31)
    enabled: bool = True

    @field_validator("thresholds")
    @classmethod
    def _thresholds(cls, values: list[int]) -> list[int]:
        if any(v < 1 or v > 1000 for v in values):
            raise ValueError("Thresholds must be between 1 and 1000 percent.")
        return sorted(set(values))

    @model_validator(mode="after")
    def _normalize(self) -> "BudgetInput":
        self.name = self.name.strip()
        self.currency = self.currency.upper()
        self.scope_value = self.scope_value.strip()
        if not self.name:
            raise ValueError("name must not be blank")
        if self.scope_type == "total":
            self.scope_value = ""
        elif not self.scope_value:
            raise ValueError("scope_value is required unless scope_type is 'total'.")
        return self


class BudgetRead(BudgetInput):
    id: int
    amount: Money
    created_at: datetime
    updated_at: datetime


class BudgetStatusRead(APIModel):
    budget: BudgetRead
    as_of: date | None
    period_start: date | None
    period_end: date | None
    actual: Money
    utilization_pct: Decimal | None
    projected_total: Money | None
    projected_utilization_pct: Decimal | None
    days_remaining: int | None
    state: Literal["no_data", "ok", "warning", "over_budget"]
    message: str
    thresholds_crossed: list[int]


class BudgetAlertRead(APIModel):
    id: int
    budget_id: int
    period_start: date
    period_end: date
    threshold_pct: int
    actual_amount: Money
    budget_amount: Money
    utilization_pct: Decimal
    data_as_of: date
    crossed_at: datetime
    last_notified_at: datetime | None
    notification_count: int


class EvaluationResult(APIModel):
    notifications_sent: int


def _get(db: Session, budget_id: int) -> Budget:
    budget = db.get(Budget, budget_id)
    if budget is None:
        raise NotFoundError("Budget", budget_id)
    return budget


@router.get("", response_model=list[BudgetStatusRead], summary="Budgets with live utilization")
def list_budgets(db: Session = Depends(get_db)) -> list[BudgetStatusRead]:
    budgets = db.scalars(select(Budget).order_by(Budget.id)).all()
    return [BudgetStatusRead.model_validate(budget_status(db, b)) for b in budgets]


@router.post(
    "", response_model=BudgetStatusRead, status_code=status.HTTP_201_CREATED, summary="Create"
)
def create_budget(
    payload: BudgetInput,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_member),
) -> BudgetStatusRead:
    budget = Budget(**payload.model_dump())
    db.add(budget)
    db.flush()
    record_audit(
        db,
        "budget.created",
        actor=user,
        request=request,
        target_type="budget",
        target_id=budget.id,
        details=payload.model_dump(mode="json"),
    )
    db.commit()
    db.refresh(budget)
    return BudgetStatusRead.model_validate(budget_status(db, budget))


@router.get("/alerts", response_model=Page[BudgetAlertRead], summary="Threshold crossings")
def list_alerts(
    budget_id: int | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> Page[BudgetAlertRead]:
    conditions = [BudgetAlert.budget_id == budget_id] if budget_id is not None else []
    total = db.scalar(select(func.count()).select_from(BudgetAlert).where(*conditions)) or 0
    alerts = db.scalars(
        select(BudgetAlert)
        .where(*conditions)
        .order_by(BudgetAlert.crossed_at.desc(), BudgetAlert.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return Page[BudgetAlertRead](
        items=[BudgetAlertRead.model_validate(a) for a in alerts],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/evaluate",
    response_model=EvaluationResult,
    summary="Check every budget now and send any due threshold alerts",
)
def evaluate_now(
    db: Session = Depends(get_db), _: User = Depends(require_member)
) -> EvaluationResult:
    return EvaluationResult(notifications_sent=evaluate_budgets(db))


@router.get("/{budget_id}", response_model=BudgetStatusRead)
def get_budget(budget_id: int, db: Session = Depends(get_db)) -> BudgetStatusRead:
    return BudgetStatusRead.model_validate(budget_status(db, _get(db, budget_id)))


@router.put("/{budget_id}", response_model=BudgetStatusRead)
def update_budget(
    budget_id: int,
    payload: BudgetInput,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_member),
) -> BudgetStatusRead:
    budget = _get(db, budget_id)
    for key, value in payload.model_dump().items():
        setattr(budget, key, value)
    record_audit(
        db,
        "budget.updated",
        actor=user,
        request=request,
        target_type="budget",
        target_id=budget_id,
        details=payload.model_dump(mode="json"),
    )
    db.commit()
    db.refresh(budget)
    return BudgetStatusRead.model_validate(budget_status(db, budget))


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(
    budget_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_member),
) -> Response:
    budget = _get(db, budget_id)
    db.delete(budget)
    record_audit(
        db,
        "budget.deleted",
        actor=user,
        request=request,
        target_type="budget",
        target_id=budget_id,
        details={"name": budget.name},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
