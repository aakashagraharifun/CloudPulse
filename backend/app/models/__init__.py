"""ORM models. Importing this package registers every table on Base.metadata."""

from app.db.base import Base
from app.models.allocation import AllocationRule, MatchField, MatchOperator
from app.models.anomaly import (
    AnomalyDetection,
    DetectionRun,
    DetectionSettings,
    Incident,
    IncidentEvent,
    IncidentStatus,
    Severity,
)
from app.models.auth import ROLE_RANK, AuditEvent, User, UserRole, UserSession
from app.models.billing import BillingImport, BillingRecord, ImportSource, ImportStatus
from app.models.budget import Budget, BudgetAlert, NotificationChannel, NotificationDelivery
from app.models.connector import Connector, ConnectorKind, SyncStatus

__all__ = [
    "AllocationRule",
    "ROLE_RANK",
    "AnomalyDetection",
    "AuditEvent",
    "Base",
    "BillingImport",
    "BillingRecord",
    "Budget",
    "BudgetAlert",
    "Connector",
    "ConnectorKind",
    "DetectionRun",
    "DetectionSettings",
    "ImportSource",
    "ImportStatus",
    "Incident",
    "IncidentEvent",
    "IncidentStatus",
    "MatchField",
    "MatchOperator",
    "NotificationChannel",
    "NotificationDelivery",
    "Severity",
    "SyncStatus",
    "User",
    "UserRole",
    "UserSession",
]
