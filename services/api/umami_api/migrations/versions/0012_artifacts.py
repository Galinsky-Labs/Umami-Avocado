"""immutable artifacts

Revision ID: 0012
Revises: 0011
"""
import sqlalchemy as sa
from alembic import op

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('artifact_blobs',
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('content', sa.LargeBinary(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('sha256')
    )
    op.create_table('artifacts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('material_id', sa.Uuid(), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('media_type', sa.String(length=100), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('store', sa.String(length=16), nullable=False),
    sa.Column('origin', sa.String(length=16), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('provenance', sa.JSON(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("origin IN ('SIMULATED', 'PHYSICAL')", name='ck_artifact_origin'),
    sa.CheckConstraint("source IN ('upload', 'adapter', 'simulator', 'cro_exchange', 'export')", name='ck_artifact_source'),
    sa.ForeignKeyConstraint(['created_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['material_id'], ['materials.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['experiment_runs.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_artifacts_project', 'artifacts', ['project_id', 'created_at'], unique=False)
    op.create_table('artifact_ingestions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('artifact_id', sa.Uuid(), nullable=False),
    sa.Column('parser', sa.String(length=40), nullable=False),
    sa.Column('assay_map', sa.JSON(), nullable=False),
    sa.Column('measurement_count', sa.Integer(), nullable=False),
    sa.Column('ingested_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['artifact_id'], ['artifacts.id'], ),
    sa.ForeignKeyConstraint(['ingested_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('artifact_id', name='uq_ingestion_artifact')
    )
    op.execute("""
        CREATE TRIGGER artifact_blobs_append_only BEFORE UPDATE OR DELETE ON artifact_blobs
        FOR EACH ROW EXECUTE FUNCTION umami_reject_mutation()
    """)
    op.execute("""
        CREATE TRIGGER artifacts_append_only BEFORE UPDATE OR DELETE ON artifacts
        FOR EACH ROW EXECUTE FUNCTION umami_reject_mutation()
    """)
    op.execute("""
        CREATE TRIGGER artifact_ingestions_append_only BEFORE UPDATE OR DELETE ON artifact_ingestions
        FOR EACH ROW EXECUTE FUNCTION umami_reject_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER artifact_blobs_append_only ON artifact_blobs")
    op.execute("DROP TRIGGER artifacts_append_only ON artifacts")
    op.execute("DROP TRIGGER artifact_ingestions_append_only ON artifact_ingestions")
    op.drop_table('artifact_ingestions')
    op.drop_index('ix_artifacts_project', table_name='artifacts')
    op.drop_table('artifacts')
    op.drop_table('artifact_blobs')
