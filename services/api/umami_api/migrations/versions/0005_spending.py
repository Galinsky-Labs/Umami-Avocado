"""budgets quotes reservations ledger

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('budgets',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('cap_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('set_by', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('cap_cents >= 0', name='ck_budget_cap'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['set_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', name='uq_budget_project')
    )
    op.create_table('quotes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('vendor', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('origin', sa.String(length=16), nullable=False),
    sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('recorded_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("origin IN ('SIMULATED', 'PHYSICAL')", name='ck_quote_origin'),
    sa.CheckConstraint('amount_cents > 0', name='ck_quote_amount'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recorded_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('reservations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('quote_id', sa.Uuid(), nullable=True),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('purpose', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('requested_by', sa.Uuid(), nullable=False),
    sa.Column('decided_by', sa.Uuid(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('requested', 'approved', 'rejected', 'released', 'consumed')", name='ck_reservation_status'),
    sa.CheckConstraint('amount_cents > 0', name='ck_reservation_amount'),
    sa.ForeignKeyConstraint(['decided_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['quote_id'], ['quotes.id'], ),
    sa.ForeignKeyConstraint(['requested_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('ledger_entries',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('posting_id', sa.Uuid(), nullable=False),
    sa.Column('account', sa.String(length=16), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('reservation_id', sa.Uuid(), nullable=True),
    sa.Column('memo', sa.String(length=200), nullable=False),
    sa.Column('posted_by', sa.Uuid(), nullable=False),
    sa.Column('posted_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("account IN ('funding', 'available', 'reserved', 'spent')", name='ck_ledger_account'),
    sa.ForeignKeyConstraint(['posted_by'], ['principals.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reservation_id'], ['reservations.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ledger_project', 'ledger_entries', ['project_id', 'account'], unique=False)
    op.execute("""
        CREATE TRIGGER ledger_entries_append_only BEFORE UPDATE OR DELETE ON ledger_entries
        FOR EACH ROW EXECUTE FUNCTION umami_reject_mutation()
    """)
    # Each posting must balance; checked when the transaction commits.
    op.execute("""
        CREATE FUNCTION umami_check_posting_balanced() RETURNS trigger AS $$
        BEGIN
            IF (SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries
                WHERE posting_id = NEW.posting_id) <> 0 THEN
                RAISE EXCEPTION 'unbalanced ledger posting' USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER ledger_postings_balanced AFTER INSERT ON ledger_entries
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION umami_check_posting_balanced()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER ledger_postings_balanced ON ledger_entries")
    op.execute("DROP FUNCTION umami_check_posting_balanced()")
    op.execute("DROP TRIGGER ledger_entries_append_only ON ledger_entries")
    op.drop_index('ix_ledger_project', table_name='ledger_entries')
    op.drop_table('ledger_entries')
    op.drop_table('reservations')
    op.drop_table('quotes')
    op.drop_table('budgets')
