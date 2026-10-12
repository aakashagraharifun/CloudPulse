"""Liveness and readiness probes."""

import logging
from typing import Literal

import redis
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str


class DependencyStatus(BaseModel):
    status: Literal["ok", "error"]
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    database: DependencyStatus
    redis: DependencyStatus


@router.get("/health", response_model=HealthResponse, summary="Liveness check")
def health() -> HealthResponse:
    """Returns 200 while the API process is running. Does not touch dependencies."""
    return HealthResponse(status="ok", service=get_settings().app_name)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness check (database and Redis)",
    responses={503: {"model": ReadinessResponse}},
)
def ready(response: Response, db: Session = Depends(get_db)) -> ReadinessResponse:
    db_status = DependencyStatus(status="ok")
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("Database readiness check failed: %s", exc)
        db_status = DependencyStatus(status="error", detail="Database is unreachable.")

    redis_status = DependencyStatus(status="ok")
    try:
        client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
        try:
            client.ping()
        finally:
            client.close()
    except Exception as exc:
        logger.warning("Redis readiness check failed: %s", exc)
        redis_status = DependencyStatus(status="error", detail="Redis is unreachable.")

    is_ready = db_status.status == "ok" and redis_status.status == "ok"
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if is_ready else "not_ready", database=db_status, redis=redis_status
    )
