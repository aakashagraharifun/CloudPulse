"""User administration and the audit log (admins only)."""

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.errors import ConflictError, NotFoundError
from app.db.session import get_db
from app.models import AuditEvent, User, UserRole
from app.schemas.auth import (
    AuditEventRead,
    PasswordResetInput,
    UserCreateInput,
    UserRead,
    UserUpdateInput,
)
from app.schemas.common import Page
from app.services.audit import record_audit
from app.services.auth import service as auth

router = APIRouter(tags=["users"])


def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User", user_id)
    return user


@router.get("/users", response_model=list[UserRead], summary="List users")
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[UserRead]:
    return [UserRead.model_validate(u) for u in db.scalars(select(User).order_by(User.id)).all()]


@router.post(
    "/users", response_model=UserRead, status_code=status.HTTP_201_CREATED, summary="Add a user"
)
def create_user(
    payload: UserCreateInput,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> UserRead:
    user = auth.create_user(
        db,
        email=payload.email,
        name=payload.name,
        password=payload.password,
        role=UserRole(payload.role),
    )
    record_audit(
        db,
        "user.created",
        actor=admin,
        request=request,
        target_type="user",
        target_id=user.id,
        details={"email": user.email, "role": user.role},
    )
    db.commit()
    return UserRead.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserRead, summary="Change name, role or status")
def update_user(
    user_id: int,
    payload: UserUpdateInput,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> UserRead:
    user = _get_user(db, user_id)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    loses_admin = (
        user.role == UserRole.ADMIN
        and user.is_active
        and (
            changes.get("role", UserRole.ADMIN) != UserRole.ADMIN
            or changes.get("is_active") is False
        )
    )
    if loses_admin and user.id == admin.id:
        raise ConflictError("You cannot remove your own admin access or deactivate yourself.")
    if loses_admin and auth.active_admin_count(db) <= 1:
        raise ConflictError("At least one active admin must remain.")
    for key, value in changes.items():
        setattr(user, key, value)
    if changes.get("is_active") is False:
        auth.revoke_user_sessions(db, user.id)
    record_audit(
        db,
        "user.updated",
        actor=admin,
        request=request,
        target_type="user",
        target_id=user.id,
        details=changes,
    )
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)


@router.post(
    "/users/{user_id}/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set a new password for a user and sign out their sessions",
)
def reset_password(
    user_id: int,
    payload: PasswordResetInput,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> None:
    user = _get_user(db, user_id)
    auth.set_password(db, user, payload.password)
    revoked = auth.revoke_user_sessions(db, user.id)
    record_audit(
        db,
        "user.password_reset",
        actor=admin,
        request=request,
        target_type="user",
        target_id=user.id,
        details={"sessions_revoked": revoked},
    )
    db.commit()


@router.get("/audit-events", response_model=Page[AuditEventRead], summary="Audit log")
def list_audit_events(
    action: str | None = Query(None, max_length=64, description="Exact action, e.g. auth.login"),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Page[AuditEventRead]:
    conditions = [AuditEvent.action == action] if action else []
    total = db.scalar(select(func.count()).select_from(AuditEvent).where(*conditions)) or 0
    events = db.scalars(
        select(AuditEvent)
        .where(*conditions)
        .order_by(AuditEvent.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return Page[AuditEventRead](
        items=[AuditEventRead.model_validate(e) for e in events],
        total=total,
        limit=limit,
        offset=offset,
    )
