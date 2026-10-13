"""Top-level API router. All endpoints are versioned under /api/v1.

Public: health/readiness, sign-in/setup, and the (data-free) CSV template.
Everything else requires a signed-in user; endpoints that change data also
require the member or admin role (see app/api/deps.py).
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.v1 import (
    allocation_rules,
    anomalies,
    auth,
    budgets,
    connectors,
    costs,
    health,
    imports,
    incidents,
    notifications,
    users,
)

api_router = APIRouter(prefix="/api/v1")

# Public routes
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(imports.public_router)

# Authenticated routes
signed_in = [Depends(get_current_user)]
for module in (
    imports,
    connectors,
    costs,
    allocation_rules,
    anomalies,
    incidents,
    budgets,
    notifications,
    users,
):
    api_router.include_router(module.router, dependencies=signed_in)
