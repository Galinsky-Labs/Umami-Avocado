"""optimization rounds

Revision ID: 0015
Revises: 0014
"""
import sqlalchemy as sa
from alembic import op

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('optimization_rounds',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('objective', sa.String(length=40), nullable=False),
    sa.Column('origin', sa.String(length=16), nullable=False),
    sa.Column('bounds', sa.JSON(), nullable=False),
    sa.Column('observations', sa.JSON(), nullable=False),
    sa.Column('suggestions', sa.JSON(), nullable=False),
    sa.Column('queued_run_ids', sa.JSON(), nullable=False),
    sa.Column('strategy', sa.String(length=40), nullable=False),
    sa.Column('requested_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requested_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.execute("""
        CREATE TRIGGER optimization_rounds_append_only BEFORE UPDATE OR DELETE ON optimization_rounds
        FOR EACH ROW EXECUTE FUNCTION umami_reject_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER optimization_rounds_append_only ON optimization_rounds")
    op.drop_table('optimization_rounds')
