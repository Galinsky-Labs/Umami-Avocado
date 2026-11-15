"""experiment runs

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('experiment_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('origin', sa.String(length=16), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=False),
    sa.Column('model_version', sa.String(length=40), nullable=False),
    sa.Column('design', sa.JSON(), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('summary', sa.JSON(), nullable=True),
    sa.Column('job_id', sa.Uuid(), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("origin IN ('SIMULATED', 'PHYSICAL')", name='ck_run_origin'),
    sa.CheckConstraint("state IN ('queued', 'running', 'completed', 'failed', 'cancelled')", name='ck_run_state'),
    sa.ForeignKeyConstraint(['created_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_runs_project', 'experiment_runs', ['project_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_runs_project', table_name='experiment_runs')
    op.drop_table('experiment_runs')
