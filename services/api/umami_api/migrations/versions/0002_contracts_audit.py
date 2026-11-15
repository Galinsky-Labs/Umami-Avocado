"""research contracts and append-only audit

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('audit_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=False),
    sa.Column('actor_kind', sa.String(length=16), nullable=False),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('resource_type', sa.String(length=64), nullable=True),
    sa.Column('resource_id', sa.String(length=64), nullable=True),
    sa.Column('decision', sa.String(length=8), nullable=False),
    sa.Column('reason', sa.String(length=80), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("decision IN ('allow', 'deny')", name='ck_audit_decision'),
    sa.ForeignKeyConstraint(['actor_id'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_workspace_time', 'audit_events', ['workspace_id', 'occurred_at'], unique=False)
    op.create_table('research_contracts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('agent_id', sa.Uuid(), nullable=False),
    sa.Column('granted_by', sa.Uuid(), nullable=False),
    sa.Column('purpose', sa.Text(), nullable=False),
    sa.Column('actions', sa.JSON(), nullable=False),
    sa.Column('project_ids', sa.JSON(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['principals.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['granted_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['revoked_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_contracts_agent', 'research_contracts', ['workspace_id', 'agent_id'], unique=False)
    op.execute("""
        CREATE FUNCTION umami_reject_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'append-only table %: % is not permitted', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION umami_reject_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION umami_reject_mutation()")
    op.drop_index('ix_contracts_agent', table_name='research_contracts')
    op.drop_table('research_contracts')
    op.drop_index('ix_audit_workspace_time', table_name='audit_events')
    op.drop_table('audit_events')
