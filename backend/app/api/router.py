"""Top-level API router. All endpoints are versioned under /api/v1."""

from fastapi import APIRouter

from app.api.v1 import (
    allocation_rules,
    anomalies,
    budgets,
    costs,
    health,
    imports,
    incidents,
    notifications,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(imports.router)
api_router.include_router(costs.router)
api_router.include_router(allocation_rules.router)
api_router.include_router(anomalies.router)
api_router.include_router(incidents.router)
api_router.include_router(budgets.router)
api_router.include_router(notifications.router)
