"""laboratories and contracts

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('laboratories',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('adapter_key', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('capabilities', sa.JSON(), nullable=False),
    sa.Column('public_contact', sa.String(length=200), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('prospect', 'onboarding', 'contracted', 'suspended')", name='ck_lab_status'),
    sa.ForeignKeyConstraint(['created_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workspace_id', 'name', name='uq_lab_name')
    )
    op.create_table('lab_contracts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('laboratory_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=160), nullable=False),
    sa.Column('scope', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('max_value_cents', sa.Integer(), nullable=False),
    sa.Column('effective_from', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('recorded_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('draft', 'signed', 'expired', 'terminated')", name='ck_lab_contract_status'),
    sa.ForeignKeyConstraint(['laboratory_id'], ['laboratories.id'], ),
    sa.ForeignKeyConstraint(['recorded_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('lab_contracts')
    op.drop_table('laboratories')
