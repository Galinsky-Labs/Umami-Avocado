"""manual cro work orders

Revision ID: 0013
Revises: 0012
"""
import sqlalchemy as sa
from alembic import op

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('work_orders',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('laboratory_id', sa.Uuid(), nullable=False),
    sa.Column('proposal_id', sa.Uuid(), nullable=False),
    sa.Column('reservation_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.String(length=160), nullable=False),
    sa.Column('state', sa.String(length=20), nullable=False),
    sa.Column('package_artifact_id', sa.Uuid(), nullable=True),
    sa.Column('package_sha256', sa.String(length=64), nullable=True),
    sa.Column('author_id', sa.Uuid(), nullable=False),
    sa.Column('approved_by', sa.Uuid(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("state IN ('draft', 'approved', 'dispatched', 'in_progress', 'results_received', 'closed', 'cancelled')", name='ck_work_order_state'),
    sa.ForeignKeyConstraint(['approved_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['author_id'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['laboratory_id'], ['laboratories.id'], ),
    sa.ForeignKeyConstraint(['package_artifact_id'], ['artifacts.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['proposal_id'], ['experiment_proposals.id'], ),
    sa.ForeignKeyConstraint(['reservation_id'], ['reservations.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('exchange_items',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('work_order_id', sa.Uuid(), nullable=False),
    sa.Column('direction', sa.String(length=10), nullable=False),
    sa.Column('artifact_id', sa.Uuid(), nullable=True),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('recorded_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("direction IN ('outbound', 'inbound', 'note')", name='ck_exchange_direction'),
    sa.ForeignKeyConstraint(['artifact_id'], ['artifacts.id'], ),
    sa.ForeignKeyConstraint(['recorded_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.execute("""
        CREATE TRIGGER exchange_items_append_only BEFORE UPDATE OR DELETE ON exchange_items
        FOR EACH ROW EXECUTE FUNCTION umami_reject_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER exchange_items_append_only ON exchange_items")
    op.drop_table('exchange_items')
    op.drop_table('work_orders')
