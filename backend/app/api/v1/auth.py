"""Sign-in, first-run setup, sign-out and password changes."""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.security import verify_password
from app.db.session import get_db
from app.schemas.auth import (
    AuthStatus,
    ChangePasswordInput,
    LoginInput,
    SessionResponse,
    SetupInput,
    UserRead,
)
from app.services.audit import client_ip, record_audit
from app.services.auth import service as auth

router = APIRouter(prefix="/auth", tags=["auth"])


def _session_response(issued: auth.IssuedSession) -> SessionResponse:
    return SessionResponse(
        token=issued.token, expires_at=issued.expires_at, user=UserRead.model_validate(issued.user)
    )


@router.get("/status", response_model=AuthStatus, summary="Whether first-run setup is needed")
def auth_status(db: Session = Depends(get_db)) -> AuthStatus:
    return AuthStatus(setup_required=auth.user_count(db) == 0)


@router.post(
    "/setup",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create the first admin account (only while no users exist)",
)
def setup(
    payload: SetupInput,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SessionResponse:
    user = auth.setup_first_admin(
        db, email=payload.email, name=payload.name, password=payload.password
    )
    issued = auth.issue_session(
        db,
        user,
        settings,
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip(request),
    )
    record_audit(
        db, "auth.setup", actor=user, request=request, target_type="user", target_id=user.id
    )
    db.commit()
    return _session_response(issued)


@router.post(
    "/login",
    response_model=SessionResponse,
    summary="Exchange email and password for a session token",
    responses={401: {"description": "Invalid credentials"}, 429: {"description": "Locked"}},
)
def login(
    payload: LoginInput,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SessionResponse:
    try:
        user = auth.authenticate(db, payload.email, payload.password, settings)
    except AppError as exc:
        record_audit(
            db,
            "auth.login_failed",
            actor=None,
            actor_email=auth.normalize_email(payload.email)[:254],
            request=request,
            details={"reason": exc.code},
        )
        db.commit()
        raise
    issued = auth.issue_session(
        db,
        user,
        settings,
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip(request),
    )
    record_audit(db, "auth.login", actor=user, request=request)
    db.commit()
    return _session_response(issued)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke this session")
def logout(
    request: Request,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> Response:
    auth.revoke_session(db, context.session.id)
    record_audit(db, "auth.logout", actor=context.user, request=request)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserRead, summary="The signed-in user")
def me(context: AuthContext = Depends(get_auth_context)) -> UserRead:
    return UserRead.model_validate(context.user)


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change your password; signs out your other sessions",
)
def change_password(
    payload: ChangePasswordInput,
    request: Request,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> Response:
    user = context.user
    if not verify_password(payload.current_password, user.password_hash):
        raise AppError(
            "The current password is incorrect.", code="invalid_credentials", status_code=400
        )
    auth.set_password(db, user, payload.new_password)
    revoked = auth.revoke_user_sessions(db, user.id, except_session_id=context.session.id)
    record_audit(
        db,
        "auth.password_changed",
        actor=user,
        request=request,
        target_type="user",
        target_id=user.id,
        details={"other_sessions_revoked": revoked},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
