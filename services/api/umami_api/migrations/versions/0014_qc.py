"""qc reports

Revision ID: 0014
Revises: 0013
"""
import sqlalchemy as sa
from alembic import op

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('qc_reports',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('assay_id', sa.Uuid(), nullable=False),
    sa.Column('origin', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=8), nullable=False),
    sa.Column('metrics', sa.JSON(), nullable=False),
    sa.Column('flags', sa.JSON(), nullable=False),
    sa.Column('measurement_ids_sha256', sa.String(length=64), nullable=False),
    sa.Column('generated_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("origin IN ('SIMULATED', 'PHYSICAL')", name='ck_qc_origin'),
    sa.CheckConstraint("status IN ('pass', 'warn', 'fail')", name='ck_qc_status'),
    sa.ForeignKeyConstraint(['assay_id'], ['assays.id'], ),
    sa.ForeignKeyConstraint(['generated_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['experiment_runs.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_qc_project', 'qc_reports', ['project_id', 'created_at'], unique=False)
    op.create_table('qc_dispositions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('report_id', sa.Uuid(), nullable=False),
    sa.Column('decision', sa.String(length=10), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('decided_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("decision IN ('accepted', 'rejected')", name='ck_qc_decision'),
    sa.ForeignKeyConstraint(['decided_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['report_id'], ['qc_reports.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('report_id', name='uq_qc_disposition')
    )
    op.execute("""
        CREATE TRIGGER qc_reports_append_only BEFORE UPDATE OR DELETE ON qc_reports
        FOR EACH ROW EXECUTE FUNCTION umami_reject_mutation()
    """)
    op.execute("""
        CREATE TRIGGER qc_dispositions_append_only BEFORE UPDATE OR DELETE ON qc_dispositions
        FOR EACH ROW EXECUTE FUNCTION umami_reject_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER qc_reports_append_only ON qc_reports")
    op.execute("DROP TRIGGER qc_dispositions_append_only ON qc_dispositions")
    op.drop_table('qc_dispositions')
    op.drop_index('ix_qc_project', table_name='qc_reports')
    op.drop_table('qc_reports')
