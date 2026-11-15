"""evidence registry and claim review

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('evidence_sources',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('identifier', sa.String(length=300), nullable=False),
    sa.Column('citation', sa.Text(), nullable=False),
    sa.Column('url', sa.String(length=500), nullable=True),
    sa.Column('added_by', sa.Uuid(), nullable=False),
    sa.Column('added_by_kind', sa.String(length=16), nullable=False),
    sa.Column('verified_by', sa.Uuid(), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind IN ('doi', 'url', 'book', 'dataset', 'internal_measurement', 'other')", name='ck_source_kind'),
    sa.ForeignKeyConstraint(['added_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['verified_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workspace_id', 'identifier', name='uq_source_identifier')
    )
    op.create_table('claims',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=True),
    sa.Column('statement', sa.Text(), nullable=False),
    sa.Column('scope_conditions', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('author_id', sa.Uuid(), nullable=False),
    sa.Column('author_kind', sa.String(length=16), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('draft', 'under_review', 'accepted', 'rejected', 'retracted')", name='ck_claim_status'),
    sa.ForeignKeyConstraint(['author_id'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_claims_workspace_status', 'claims', ['workspace_id', 'status'], unique=False)
    op.create_table('claim_evidence',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('claim_id', sa.Uuid(), nullable=False),
    sa.Column('source_id', sa.Uuid(), nullable=True),
    sa.Column('measurement_id', sa.Uuid(), nullable=True),
    sa.Column('stance', sa.String(length=16), nullable=False),
    sa.Column('excerpt', sa.Text(), nullable=False),
    sa.Column('added_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("stance IN ('supports', 'contradicts', 'context')", name='ck_evidence_stance'),
    sa.CheckConstraint('(source_id IS NULL) <> (measurement_id IS NULL)', name='ck_evidence_exactly_one_target'),
    sa.ForeignKeyConstraint(['added_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['claim_id'], ['claims.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['measurement_id'], ['measurements.id'], ),
    sa.ForeignKeyConstraint(['source_id'], ['evidence_sources.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # claim_reviews is append-only; see trigger below.
    op.create_table('claim_reviews',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('claim_id', sa.Uuid(), nullable=False),
    sa.Column('reviewer_id', sa.Uuid(), nullable=False),
    sa.Column('decision', sa.String(length=16), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('from_status', sa.String(length=16), nullable=False),
    sa.Column('to_status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("decision IN ('accept', 'reject', 'request_changes', 'retract')", name='ck_review_decision'),
    sa.ForeignKeyConstraint(['claim_id'], ['claims.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reviewer_id'], ['principals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.execute("""
        CREATE TRIGGER claim_reviews_append_only BEFORE UPDATE OR DELETE ON claim_reviews
        FOR EACH ROW EXECUTE FUNCTION umami_reject_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER claim_reviews_append_only ON claim_reviews")
    op.drop_table('claim_reviews')
    op.drop_table('claim_evidence')
    op.drop_index('ix_claims_workspace_status', table_name='claims')
    op.drop_table('claims')
    op.drop_table('evidence_sources')
