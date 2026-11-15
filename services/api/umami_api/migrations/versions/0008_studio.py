"""protocols and proposals

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('protocol_versions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=160), nullable=False),
    sa.Column('content', sa.JSON(), nullable=False),
    sa.Column('change_note', sa.Text(), nullable=False),
    sa.Column('author_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workspace_id', 'key', 'version', name='uq_protocol_version')
    )
    op.create_table('experiment_proposals',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('protocol_version_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=160), nullable=False),
    sa.Column('hypothesis', sa.Text(), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('evidence_claim_ids', sa.JSON(), nullable=False),
    sa.Column('evidence_source_ids', sa.JSON(), nullable=False),
    sa.Column('target_origin', sa.String(length=16), nullable=False),
    sa.Column('state', sa.String(length=20), nullable=False),
    sa.Column('preflight', sa.JSON(), nullable=True),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('author_id', sa.Uuid(), nullable=False),
    sa.Column('author_kind', sa.String(length=16), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("state IN ('draft', 'preflight_failed', 'ready', 'executing', 'executed', 'withdrawn')", name='ck_proposal_state'),
    sa.CheckConstraint("target_origin IN ('SIMULATED', 'PHYSICAL')", name='ck_proposal_target'),
    sa.ForeignKeyConstraint(['author_id'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['protocol_version_id'], ['protocol_versions.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['experiment_runs.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.execute("""
        CREATE TRIGGER protocol_versions_immutable BEFORE UPDATE OR DELETE ON protocol_versions
        FOR EACH ROW EXECUTE FUNCTION umami_reject_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER protocol_versions_immutable ON protocol_versions")
    op.drop_table('experiment_proposals')
    op.drop_table('protocol_versions')
