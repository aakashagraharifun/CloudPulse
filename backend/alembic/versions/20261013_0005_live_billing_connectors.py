"""live billing connectors (AWS CUR, Cost Explorer, OpenAI, Anthropic)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-13 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0005'
down_revision: str | Sequence[str] | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'connectors',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('credentials_encrypted', sa.Text(), nullable=False),
        sa.Column('credentials_hint', sa.String(length=64), nullable=False),
        sa.Column('sync_interval_hours', sa.Integer(), nullable=False),
        sa.Column('lookback_days', sa.Integer(), nullable=False),
        sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('verified_identity', sa.String(length=255), nullable=True),
        sa.Column('last_sync_status', sa.String(length=16), nullable=True),
        sa.Column('last_sync_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sync_finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sync_message', sa.Text(), nullable=True),
        sa.Column('last_import_id', sa.Integer(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('aws_cur_s3', 'aws_cost_explorer', 'openai_costs', 'anthropic_costs')",
            name=op.f('ck_connectors_kind_valid'),
        ),
        sa.CheckConstraint(
            "last_sync_status IS NULL OR last_sync_status IN ('running', 'succeeded', 'failed')",
            name=op.f('ck_connectors_last_sync_status_valid'),
        ),
        sa.CheckConstraint(
            'sync_interval_hours BETWEEN 0 AND 168', name=op.f('ck_connectors_interval_range')
        ),
        sa.CheckConstraint('lookback_days BETWEEN 1 AND 365', name=op.f('ck_connectors_lookback_range')),
        sa.ForeignKeyConstraint(
            ['created_by_id'], ['users.id'],
            name=op.f('fk_connectors_created_by_id_users'), ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_connectors')),
    )

    op.add_column(
        'billing_imports',
        sa.Column('rows_replaced', sa.Integer(), server_default='0', nullable=False),
    )
    op.alter_column('billing_imports', 'rows_replaced', server_default=None)
    op.add_column('billing_imports', sa.Column('connector_id', sa.Integer(), nullable=True))
    op.create_index(
        op.f('ix_billing_imports_connector_id'), 'billing_imports', ['connector_id'], unique=False
    )
    op.create_foreign_key(
        op.f('fk_billing_imports_connector_id_connectors'), 'billing_imports', 'connectors',
        ['connector_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        op.f('fk_connectors_last_import_id_billing_imports'), 'connectors', 'billing_imports',
        ['last_import_id'], ['id'], ondelete='SET NULL',
    )

    op.drop_constraint(op.f('ck_billing_imports_source_valid'), 'billing_imports', type_='check')
    op.create_check_constraint(
        op.f('ck_billing_imports_source_valid'), 'billing_imports',
        "source IN ('upload', 'sample', 'connector')",
    )
    # Connector syncs are reconciled per window instead of by whole-file hash.
    op.drop_index('uq_billing_imports_completed_sha256', table_name='billing_imports')
    op.create_index(
        'uq_billing_imports_completed_sha256', 'billing_imports', ['file_sha256'], unique=True,
        postgresql_where=sa.text("status = 'completed' AND source <> 'connector'"),
    )


def downgrade() -> None:
    # Connector data cannot be represented in the previous schema; remove it.
    op.execute("DELETE FROM billing_imports WHERE source = 'connector'")
    op.drop_index('uq_billing_imports_completed_sha256', table_name='billing_imports')
    op.create_index(
        'uq_billing_imports_completed_sha256', 'billing_imports', ['file_sha256'], unique=True,
        postgresql_where=sa.text("status = 'completed'"),
    )
    op.drop_constraint(op.f('ck_billing_imports_source_valid'), 'billing_imports', type_='check')
    op.create_check_constraint(
        op.f('ck_billing_imports_source_valid'), 'billing_imports',
        "source IN ('upload', 'sample')",
    )
    op.drop_constraint(
        op.f('fk_connectors_last_import_id_billing_imports'), 'connectors', type_='foreignkey'
    )
    op.drop_constraint(
        op.f('fk_billing_imports_connector_id_connectors'), 'billing_imports', type_='foreignkey'
    )
    op.drop_index(op.f('ix_billing_imports_connector_id'), table_name='billing_imports')
    op.drop_column('billing_imports', 'connector_id')
    op.drop_column('billing_imports', 'rows_replaced')
    op.drop_table('connectors')
