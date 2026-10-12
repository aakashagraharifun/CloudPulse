"""Notification channels, test messages and delivery history."""

import re
import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.errors import AppError, NotFoundError
from app.db.session import get_db
from app.models import NotificationChannel, NotificationDelivery, User
from app.schemas.anomalies import SeverityLiteral
from app.schemas.common import APIModel, Page
from app.services.audit import record_audit
from app.services.notifications.service import Notification, deliver, parse_recipients

router = APIRouter(prefix="/notifications", tags=["notifications"])

_EMAIL = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+$")


def mask_target(channel_type: str, target: str) -> str:
    """Webhook URLs often embed secrets; only the scheme, host and last 4 characters are shown."""
    if channel_type != "webhook":
        return target
    parts = urlsplit(target)
    return f"{parts.scheme}://{parts.netloc}/…{target[-4:]}" if len(target) > 12 else "…"


class ChannelBase(APIModel):
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    notify_budget_alerts: bool = True
    notify_incidents: bool = True
    min_severity: SeverityLiteral = "medium"


class ChannelInput(ChannelBase):
    type: Literal["webhook", "email"]
    target: str | None = Field(
        None,
        max_length=2048,
        description="Webhook URL or comma-separated e-mail addresses. On update, omit to keep.",
    )

    @model_validator(mode="after")
    def _validate_target(self) -> "ChannelInput":
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name must not be blank")
        if self.target is None:
            return self
        self.target = self.target.strip()
        if self.type == "webhook":
            parts = urlsplit(self.target)
            if parts.scheme not in ("http", "https") or not parts.netloc:
                raise ValueError("Webhook target must be an http(s) URL.")
        else:
            recipients = parse_recipients(self.target)
            if not recipients or not all(_EMAIL.match(r) for r in recipients):
                raise ValueError("E-mail target must be one or more comma-separated addresses.")
            self.target = ", ".join(recipients)
        return self


class ChannelRead(ChannelBase):
    id: int
    type: Literal["webhook", "email"]
    target_display: str
    created_at: datetime
    updated_at: datetime


class DeliveryRead(APIModel):
    id: int
    channel_id: int | None
    channel_name: str
    channel_type: str
    event_type: str
    subject: str
    status: Literal["pending", "sent", "failed"]
    attempts: int
    last_error: str | None
    created_at: datetime
    last_attempt_at: datetime | None
    sent_at: datetime | None


def _read(channel: NotificationChannel) -> ChannelRead:
    return ChannelRead(
        id=channel.id,
        name=channel.name,
        type=channel.type,  # type: ignore[arg-type]
        enabled=channel.enabled,
        notify_budget_alerts=channel.notify_budget_alerts,
        notify_incidents=channel.notify_incidents,
        min_severity=channel.min_severity,  # type: ignore[arg-type]
        target_display=mask_target(channel.type, channel.target),
        created_at=channel.created_at,
        updated_at=channel.updated_at,
    )


def _get(db: Session, channel_id: int) -> NotificationChannel:
    channel = db.get(NotificationChannel, channel_id)
    if channel is None:
        raise NotFoundError("Notification channel", channel_id)
    return channel


@router.get("/channels", response_model=list[ChannelRead], summary="List channels")
def list_channels(db: Session = Depends(get_db)) -> list[ChannelRead]:
    channels = db.scalars(select(NotificationChannel).order_by(NotificationChannel.id)).all()
    return [_read(c) for c in channels]


@router.post(
    "/channels",
    response_model=ChannelRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a webhook or e-mail channel",
)
def create_channel(
    payload: ChannelInput,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> ChannelRead:
    if not payload.target:
        raise AppError("target is required.", code="validation_error", status_code=422)
    channel = NotificationChannel(**payload.model_dump())
    db.add(channel)
    db.flush()
    record_audit(
        db,
        "channel.created",
        actor=user,
        request=request,
        target_type="notification_channel",
        target_id=channel.id,
        details={"name": channel.name, "type": channel.type},
    )
    db.commit()
    db.refresh(channel)
    return _read(channel)


@router.put("/channels/{channel_id}", response_model=ChannelRead, summary="Update a channel")
def update_channel(
    channel_id: int,
    payload: ChannelInput,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> ChannelRead:
    channel = _get(db, channel_id)
    data = payload.model_dump()
    if data["target"] is None:
        if data["type"] != channel.type:
            raise AppError(
                "A new target is required when changing the channel type.",
                code="validation_error",
                status_code=422,
            )
        data.pop("target")
    for key, value in data.items():
        setattr(channel, key, value)
    record_audit(
        db,
        "channel.updated",
        actor=user,
        request=request,
        target_type="notification_channel",
        target_id=channel_id,
        details={k: v for k, v in data.items() if k != "target"}
        | {"target_changed": "target" in data},
    )
    db.commit()
    db.refresh(channel)
    return _read(channel)


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_channel(
    channel_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> Response:
    channel = _get(db, channel_id)
    db.delete(channel)
    record_audit(
        db,
        "channel.deleted",
        actor=user,
        request=request,
        target_type="notification_channel",
        target_id=channel_id,
        details={"name": channel.name},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/channels/{channel_id}/test",
    response_model=DeliveryRead,
    summary="Send a test message now and return the delivery outcome",
)
def test_channel(
    channel_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> DeliveryRead:
    channel = _get(db, channel_id)
    notification = Notification(
        event_type="test",
        event_key=f"test:{uuid.uuid4()}",
        subject="[CloudPulse] Test notification",
        body=f"This is a test message for channel '{channel.name}'. Delivery is working.",
        data={"channel_id": channel.id},
    )
    deliveries = deliver(db, notification, [channel])
    if not deliveries:
        raise AppError(
            "The test delivery could not be recorded.", code="internal_error", status_code=500
        )
    return DeliveryRead.model_validate(deliveries[0])


@router.get("/deliveries", response_model=Page[DeliveryRead], summary="Delivery history")
def list_deliveries(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> Page[DeliveryRead]:
    total = db.scalar(select(func.count()).select_from(NotificationDelivery)) or 0
    rows = db.scalars(
        select(NotificationDelivery)
        .order_by(NotificationDelivery.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return Page[DeliveryRead](
        items=[DeliveryRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
