"""assays and immutable measurements

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('assays',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('quantity_kind', sa.String(length=64), nullable=False),
    sa.Column('unit', sa.String(length=16), nullable=False),
    sa.Column('method', sa.Text(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workspace_id', 'key', 'version', name='uq_assay_version')
    )
    op.create_table('measurements',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('assay_id', sa.Uuid(), nullable=False),
    sa.Column('origin', sa.String(length=16), nullable=False),
    sa.Column('sample_label', sa.String(length=120), nullable=False),
    sa.Column('biological_replicate', sa.Integer(), nullable=False),
    sa.Column('technical_replicate', sa.Integer(), nullable=False),
    sa.Column('value', sa.Double(), nullable=False),
    sa.Column('unit', sa.String(length=16), nullable=False),
    sa.Column('value_canonical', sa.Double(), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('provenance', sa.Text(), nullable=False),
    sa.Column('supersedes_id', sa.Uuid(), nullable=True),
    sa.Column('recorded_by', sa.Uuid(), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("origin IN ('SIMULATED', 'PHYSICAL')", name='ck_measurement_origin'),
    sa.CheckConstraint('biological_replicate >= 1 AND technical_replicate >= 1', name='ck_measurement_replicates'),
    sa.ForeignKeyConstraint(['assay_id'], ['assays.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recorded_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['supersedes_id'], ['measurements.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_measurements_project_assay', 'measurements', ['project_id', 'assay_id', 'origin'], unique=False)
    op.execute("""
        CREATE TRIGGER measurements_immutable BEFORE UPDATE OR DELETE ON measurements
        FOR EACH ROW EXECUTE FUNCTION umami_reject_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER measurements_immutable ON measurements")
    op.drop_index('ix_measurements_project_assay', table_name='measurements')
    op.drop_table('measurements')
    op.drop_table('assays')
