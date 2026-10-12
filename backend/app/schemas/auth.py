"""Authentication, user and audit-log schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from app.schemas.common import APIModel

RoleLiteral = Literal["viewer", "member", "admin"]
EMAIL_PATTERN = r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$"


def _clean_name(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("must not be blank")
    return value


class UserRead(APIModel):
    id: int
    email: str
    name: str
    role: RoleLiteral
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class AuthStatus(APIModel):
    setup_required: bool


class LoginInput(APIModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class SetupInput(APIModel):
    email: str = Field(max_length=254, pattern=EMAIL_PATTERN)
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean_name(value)


class SessionResponse(APIModel):
    token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: UserRead


class ChangePasswordInput(APIModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class UserCreateInput(APIModel):
    email: str = Field(max_length=254, pattern=EMAIL_PATTERN)
    name: str = Field(min_length=1, max_length=80)
    role: RoleLiteral = "viewer"
    password: str = Field(min_length=1, max_length=256, description="Initial password")

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean_name(value)


class UserUpdateInput(APIModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    role: RoleLiteral | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _clean_name(value)


class PasswordResetInput(APIModel):
    password: str = Field(min_length=1, max_length=256)


class AuditEventRead(APIModel):
    id: int
    actor_user_id: int | None
    actor_email: str | None
    action: str
    target_type: str | None
    target_id: str | None
    details: dict[str, Any] | None
    ip_address: str | None
    request_id: str | None
    created_at: datetime
