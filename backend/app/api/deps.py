"""Authentication and authorization dependencies.

Every router except health/auth is mounted with `CurrentUser` (any signed-in
user can read). Endpoints that change data additionally declare
`require_member` or `require_admin`.
"""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.session import get_db
from app.models import ROLE_RANK, User, UserRole, UserSession
from app.services.auth.service import resolve_session

bearer_scheme = HTTPBearer(auto_error=False, description="Session token from /auth/login")
_CHALLENGE = {"WWW-Authenticate": "Bearer"}


@dataclass
class AuthContext:
    user: User
    session: UserSession


def get_auth_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AuthContext:
    if credentials is None or not credentials.credentials:
        raise AppError(
            "Sign in to use CloudPulse.",
            code="not_authenticated",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers=_CHALLENGE,
        )
    resolved = resolve_session(db, credentials.credentials)
    if resolved is None:
        raise AppError(
            "Your session has expired or is no longer valid. Sign in again.",
            code="invalid_token",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers=_CHALLENGE,
        )
    session, user = resolved
    request.state.user_id = user.id
    return AuthContext(user=user, session=session)


def get_current_user(context: AuthContext = Depends(get_auth_context)) -> User:
    return context.user


def require_role(minimum: UserRole) -> Callable[..., User]:
    def dependency(user: User = Depends(get_current_user)) -> User:
        if ROLE_RANK[UserRole(user.role)] < ROLE_RANK[minimum]:
            raise AppError(
                f"This action requires the {minimum.value} role (you are a {user.role}).",
                code="forbidden",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return user

    dependency.__name__ = f"require_{minimum.value}"
    return dependency


require_member = require_role(UserRole.MEMBER)
require_admin = require_role(UserRole.ADMIN)
