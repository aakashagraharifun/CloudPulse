"""Rules that attribute untagged costs to a project and/or environment."""

from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class MatchField(StrEnum):
    PROVIDER = "provider"
    ACCOUNT_ID = "account_id"
    SERVICE = "service"
    RESOURCE_ID = "resource_id"
    REGION = "region"
    USAGE_TYPE = "usage_type"


class MatchOperator(StrEnum):
    EQUALS = "equals"
    PREFIX = "prefix"
    CONTAINS = "contains"


class AllocationRule(TimestampMixin, Base):
    """If a record lacks a project/environment tag and matches, assign these values.

    Source tags always win over rules. Rules are evaluated by ascending priority
    (then id); for each attribute the first matching rule that sets it wins.
    """

    __tablename__ = "allocation_rules"
    __table_args__ = (
        CheckConstraint(
            "match_field IN ('provider', 'account_id', 'service', 'resource_id', 'region', "
            "'usage_type')",
            name="match_field_valid",
        ),
        CheckConstraint(
            "match_operator IN ('equals', 'prefix', 'contains')", name="match_operator_valid"
        ),
        CheckConstraint("project IS NOT NULL OR environment IS NOT NULL", name="assigns_something"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    match_field: Mapped[str] = mapped_column(String(32), nullable=False)
    match_operator: Mapped[str] = mapped_column(String(16), nullable=False)
    match_value: Mapped[str] = mapped_column(String(512), nullable=False)
    project: Mapped[str | None] = mapped_column(String(128))
    environment: Mapped[str | None] = mapped_column(String(128))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
