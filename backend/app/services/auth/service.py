"""Authentication: first-run setup, login with lockout, sessions, password changes.

CloudPulse is a single workspace. Every user sees the same billing data;
what they may *change* is governed by their role (viewer < member < admin).
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ConflictError
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    hash_password,
    hash_token,
    new_session_token,
    password_problem,
    verify_password,
)
from app.models import User, UserRole, UserSession

logger = logging.getLogger(__name__)
SETUP_LOCK_KEY = 7_420_002
INVALID_CREDENTIALS = "Email or password is incorrect."


@dataclass
class IssuedSession:
    token: str
    expires_at: datetime
    user: User


def normalize_email(email: str) -> str:
    return email.strip().lower()


def ensure_password_ok(password: str) -> None:
    problem = password_problem(password)
    if problem:
        raise AppError(problem, code="weak_password", status_code=422)


def user_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User)) or 0


def create_user(db: Session, *, email: str, name: str, password: str, role: UserRole) -> User:
    ensure_password_ok(password)
    email = normalize_email(email)
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise ConflictError(f"A user with the email {email} already exists.")
    user = User(email=email, name=name.strip(), password_hash=hash_password(password), role=role)
    db.add(user)
    db.flush()
    return user


def issue_session(
    db: Session,
    user: User,
    settings: Settings,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> IssuedSession:
    token = new_session_token()
    expires_at = datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=expires_at,
            user_agent=(user_agent or "")[:255] or None,
            ip_address=ip_address,
        )
    )
    return IssuedSession(token=token, expires_at=expires_at, user=user)


def setup_first_admin(db: Session, *, email: str, name: str, password: str) -> User:
    """Create the first admin. Only allowed while no user exists (race-safe)."""
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SETUP_LOCK_KEY})
    if user_count(db) > 0:
        raise ConflictError("Setup has already been completed. Sign in instead.")
    return create_user(db, email=email, name=name, password=password, role=UserRole.ADMIN)


def authenticate(db: Session, email: str, password: str, settings: Settings) -> User:
    """Return the user for valid credentials; raise 401/429 otherwise."""
    now = datetime.now(UTC)
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        verify_password(password, DUMMY_PASSWORD_HASH)  # equalize timing
        raise AppError(INVALID_CREDENTIALS, code="invalid_credentials", status_code=401)

    if user.locked_until is not None and user.locked_until > now:
        minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        raise AppError(
            f"Too many failed sign-in attempts. Try again in {minutes} minute(s).",
            code="account_locked",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(minutes * 60)},
        )

    if not verify_password(password, user.password_hash) or not user.is_active:
        if user.is_active:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.auth_max_failed_logins:
                user.locked_until = now + timedelta(minutes=settings.auth_lockout_minutes)
                user.failed_login_count = 0
                logger.warning(
                    "Account locked after failed logins", extra={"context": {"user_id": user.id}}
                )
        db.commit()
        raise AppError(INVALID_CREDENTIALS, code="invalid_credentials", status_code=401)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    return user


def resolve_session(db: Session, token: str) -> tuple[UserSession, User] | None:
    now = datetime.now(UTC)
    row = db.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(
            UserSession.token_hash == hash_token(token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
            User.is_active.is_(True),
        )
    ).first()
    if row is None:
        return None
    session, user = row
    # Record activity at most every 5 minutes to avoid a write on every request.
    if session.last_used_at is None or now - session.last_used_at > timedelta(minutes=5):
        session.last_used_at = now
        db.commit()
    return session, user


def revoke_session(db: Session, session_id: int) -> None:
    db.execute(
        update(UserSession)
        .where(UserSession.id == session_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def revoke_user_sessions(db: Session, user_id: int, *, except_session_id: int | None = None) -> int:
    statement = update(UserSession).where(
        UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
    )
    if except_session_id is not None:
        statement = statement.where(UserSession.id != except_session_id)
    result = db.execute(statement.values(revoked_at=datetime.now(UTC)))
    return result.rowcount or 0


def set_password(db: Session, user: User, new_password: str) -> None:
    ensure_password_ok(new_password)
    user.password_hash = hash_password(new_password)
    user.failed_login_count = 0
    user.locked_until = None


def active_admin_count(db: Session) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == UserRole.ADMIN, User.is_active.is_(True))
        )
        or 0
    )


def purge_expired_sessions(db: Session, *, older_than_days: int = 7) -> int:
    """Delete sessions that expired or were revoked more than `older_than_days` ago."""
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    result = db.execute(
        UserSession.__table__.delete().where(
            (UserSession.expires_at < cutoff)
            | (UserSession.revoked_at.is_not(None) & (UserSession.revoked_at < cutoff))
        )
    )
    db.commit()
    return result.rowcount or 0
