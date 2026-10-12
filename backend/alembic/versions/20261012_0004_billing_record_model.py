"""billing record model (AI/LLM usage)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-12 21:05:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0004'
down_revision: str | Sequence[str] | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable, no default: existing rows keep model = NULL and their fingerprints.
    op.add_column('billing_records', sa.Column('model', sa.String(length=128), nullable=True))
    op.create_index(op.f('ix_billing_records_model'), 'billing_records', ['model'], unique=False)
    # Allocation rules may match on the model, e.g. "model contains claude".
    op.drop_constraint(
        op.f('ck_allocation_rules_match_field_valid'), 'allocation_rules', type_='check'
    )
    op.create_check_constraint(
        op.f('ck_allocation_rules_match_field_valid'),
        'allocation_rules',
        "match_field IN ('provider', 'account_id', 'service', 'resource_id', 'region', "
        "'usage_type', 'model')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM allocation_rules WHERE match_field = 'model'")
    op.drop_constraint(
        op.f('ck_allocation_rules_match_field_valid'), 'allocation_rules', type_='check'
    )
    op.create_check_constraint(
        op.f('ck_allocation_rules_match_field_valid'),
        'allocation_rules',
        "match_field IN ('provider', 'account_id', 'service', 'resource_id', 'region', "
        "'usage_type')",
    )
    op.drop_index(op.f('ix_billing_records_model'), table_name='billing_records')
    op.drop_column('billing_records', 'model')
