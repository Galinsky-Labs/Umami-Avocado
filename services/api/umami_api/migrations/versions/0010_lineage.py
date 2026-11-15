"""materials lineage custody

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('materials',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=False),
    sa.Column('organism', sa.String(length=120), nullable=True),
    sa.Column('origin', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('custodian', sa.String(length=120), nullable=False),
    sa.Column('location', sa.String(length=200), nullable=False),
    sa.Column('attributes', sa.JSON(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind IN ('strain', 'culture', 'sample', 'extract', 'plant_material', 'reagent')", name='ck_material_kind'),
    sa.CheckConstraint("origin IN ('SIMULATED', 'PHYSICAL')", name='ck_material_origin'),
    sa.CheckConstraint("status IN ('active', 'consumed', 'disposed')", name='ck_material_status'),
    sa.ForeignKeyConstraint(['created_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['experiment_runs.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workspace_id', 'label', name='uq_material_label')
    )
    op.create_table('custody_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('material_id', sa.Uuid(), nullable=False),
    sa.Column('event', sa.String(length=16), nullable=False),
    sa.Column('from_party', sa.String(length=120), nullable=True),
    sa.Column('to_party', sa.String(length=120), nullable=True),
    sa.Column('location', sa.String(length=200), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('recorded_by', sa.Uuid(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("event IN ('registered', 'transferred', 'received', 'stored', 'shipped', 'consumed', 'disposed')", name='ck_custody_event'),
    sa.ForeignKeyConstraint(['material_id'], ['materials.id'], ),
    sa.ForeignKeyConstraint(['recorded_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_custody_material', 'custody_events', ['material_id', 'occurred_at'], unique=False)
    op.create_table('lineage_edges',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('parent_id', sa.Uuid(), nullable=False),
    sa.Column('child_id', sa.Uuid(), nullable=False),
    sa.Column('relation', sa.String(length=32), nullable=False),
    sa.Column('recorded_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("relation IN ('derived_from', 'split_from', 'pooled_from', 'subcultured_from')", name='ck_lineage_relation'),
    sa.CheckConstraint('parent_id <> child_id', name='ck_lineage_no_self'),
    sa.ForeignKeyConstraint(['child_id'], ['materials.id'], ),
    sa.ForeignKeyConstraint(['parent_id'], ['materials.id'], ),
    sa.ForeignKeyConstraint(['recorded_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('parent_id', 'child_id', name='uq_lineage_edge')
    )
    op.create_index('ix_lineage_child', 'lineage_edges', ['child_id'], unique=False)
    op.execute("""
        CREATE TRIGGER lineage_edges_append_only BEFORE UPDATE OR DELETE ON lineage_edges
        FOR EACH ROW EXECUTE FUNCTION umami_reject_mutation()
    """)
    op.execute("""
        CREATE TRIGGER custody_events_append_only BEFORE UPDATE OR DELETE ON custody_events
        FOR EACH ROW EXECUTE FUNCTION umami_reject_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER lineage_edges_append_only ON lineage_edges")
    op.execute("DROP TRIGGER custody_events_append_only ON custody_events")
    op.drop_index('ix_lineage_child', table_name='lineage_edges')
    op.drop_table('lineage_edges')
    op.drop_index('ix_custody_material', table_name='custody_events')
    op.drop_table('custody_events')
    op.drop_table('materials')
