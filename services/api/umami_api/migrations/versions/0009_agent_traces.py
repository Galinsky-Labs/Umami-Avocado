"""agent traces

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('agent_traces',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=64), nullable=False),
    sa.Column('input_sha256', sa.String(length=64), nullable=False),
    sa.Column('input', sa.JSON(), nullable=False),
    sa.Column('output', sa.JSON(), nullable=True),
    sa.Column('outcome', sa.String(length=32), nullable=False),
    sa.Column('errors', sa.JSON(), nullable=False),
    sa.Column('proposal_id', sa.Uuid(), nullable=True),
    sa.Column('requested_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['proposal_id'], ['experiment_proposals.id'], ),
    sa.ForeignKeyConstraint(['requested_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_agent_traces_project', 'agent_traces', ['project_id', 'created_at'], unique=False)
    op.execute("""
        CREATE TRIGGER agent_traces_append_only BEFORE UPDATE OR DELETE ON agent_traces
        FOR EACH ROW EXECUTE FUNCTION umami_reject_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER agent_traces_append_only ON agent_traces")
    op.drop_index('ix_agent_traces_project', table_name='agent_traces')
    op.drop_table('agent_traces')
