"""Persistent schema. Every research record is scoped to exactly one workspace.

Schema changes are made only through Alembic migrations in umami_api/migrations.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from umami_api.db import utcnow

PRINCIPAL_KINDS = ("human", "agent")
ROLES = ("owner", "admin", "scientist", "reviewer", "viewer", "agent")
PROJECT_PROGRAMS = ("M1", "M2", "A1", "OTHER")
PROJECT_STATUSES = ("planning", "active", "paused", "archived")


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Principal(TimestampMixin, Base):
    """A human or AI agent identity. Kind is immutable and never inferred from text."""
    __tablename__ = "principals"
    __table_args__ = (CheckConstraint(_in("kind", PRINCIPAL_KINDS), name="ck_principal_kind"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(16))
    display_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))


class Membership(TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "principal_id", name="uq_membership"),
        CheckConstraint(_in("role", ROLES), name="ck_membership_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))


class ApiToken(TimestampMixin, Base):
    """Bearer credentials. Only a SHA-256 digest of the secret is stored."""
    __tablename__ = "api_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(80))
    prefix: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_project_slug"),
        CheckConstraint(_in("program", PROJECT_PROGRAMS), name="ck_project_program"),
        CheckConstraint(_in("status", PROJECT_STATUSES), name="ck_project_status"),
        Index("ix_projects_workspace", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(120))
    program: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default="planning")
    objective: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResearchContract(TimestampMixin, Base):
    """Explicit, expiring scope granted by a human to one agent principal (UA-007)."""
    __tablename__ = "research_contracts"
    __table_args__ = (Index("ix_contracts_agent", "workspace_id", "agent_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id", ondelete="CASCADE"))
    granted_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    purpose: Mapped[str] = mapped_column(Text)
    actions: Mapped[list[str]] = mapped_column(JSON)
    project_ids: Mapped[list[str] | None] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))


class AuditEvent(Base):
    """Append-only record of authorization decisions and state changes.

    A database trigger rejects UPDATE and DELETE (migration 0002)."""
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_workspace_time", "workspace_id", "occurred_at"),
        CheckConstraint("decision IN ('allow', 'deny')", name="ck_audit_decision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    actor_kind: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(8))
    reason: Mapped[str] = mapped_column(String(80))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


RESULT_ORIGINS = ("SIMULATED", "PHYSICAL")


class Assay(TimestampMixin, Base):
    """Versioned measurement method bound to one quantity kind and canonical unit (UA-005)."""
    __tablename__ = "assays"
    __table_args__ = (UniqueConstraint("workspace_id", "key", "version", name="uq_assay_version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(default=1)
    name: Mapped[str] = mapped_column(String(120))
    quantity_kind: Mapped[str] = mapped_column(String(64))
    unit: Mapped[str] = mapped_column(String(16))
    method: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))


class Measurement(Base):
    """Immutable observation. ``origin`` is permanent provenance: SIMULATED and PHYSICAL
    are never converted into one another (a trigger rejects UPDATE/DELETE)."""
    __tablename__ = "measurements"
    __table_args__ = (
        CheckConstraint(_in("origin", RESULT_ORIGINS), name="ck_measurement_origin"),
        CheckConstraint("biological_replicate >= 1 AND technical_replicate >= 1",
                        name="ck_measurement_replicates"),
        Index("ix_measurements_project_assay", "project_id", "assay_id", "origin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    assay_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assays.id"))
    origin: Mapped[str] = mapped_column(String(16))
    sample_label: Mapped[str] = mapped_column(String(120))
    biological_replicate: Mapped[int]
    technical_replicate: Mapped[int]
    value: Mapped[float]
    unit: Mapped[str] = mapped_column(String(16))
    value_canonical: Mapped[float]
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run_id: Mapped[uuid.UUID | None] = mapped_column()
    provenance: Mapped[str] = mapped_column(Text, default="")
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("measurements.id"))
    recorded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


SOURCE_KINDS = ("doi", "url", "book", "dataset", "internal_measurement", "other")
CLAIM_STATUSES = ("draft", "under_review", "accepted", "rejected", "retracted")
STANCES = ("supports", "contradicts", "context")
REVIEW_DECISIONS = ("accept", "reject", "request_changes", "retract")


class EvidenceSource(TimestampMixin, Base):
    """A citable source. Agent-added sources are flagged until a human verifies them (UA-004)."""
    __tablename__ = "evidence_sources"
    __table_args__ = (CheckConstraint(_in("kind", SOURCE_KINDS), name="ck_source_kind"),
                      UniqueConstraint("workspace_id", "identifier", name="uq_source_identifier"))

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    identifier: Mapped[str] = mapped_column(String(300))
    citation: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(500))
    added_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    added_by_kind: Mapped[str] = mapped_column(String(16))
    verified_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Claim(TimestampMixin, Base):
    __tablename__ = "claims"
    __table_args__ = (CheckConstraint(_in("status", CLAIM_STATUSES), name="ck_claim_status"),
                      Index("ix_claims_workspace_status", "workspace_id", "status"))

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    statement: Mapped[str] = mapped_column(Text)
    scope_conditions: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    author_kind: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClaimEvidence(TimestampMixin, Base):
    __tablename__ = "claim_evidence"
    __table_args__ = (
        CheckConstraint(_in("stance", STANCES), name="ck_evidence_stance"),
        CheckConstraint("(source_id IS NULL) <> (measurement_id IS NULL)",
                        name="ck_evidence_exactly_one_target"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"))
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence_sources.id"))
    measurement_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("measurements.id"))
    stance: Mapped[str] = mapped_column(String(16))
    excerpt: Mapped[str] = mapped_column(Text, default="")
    added_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))


class ClaimReview(TimestampMixin, Base):
    __tablename__ = "claim_reviews"
    __table_args__ = (CheckConstraint(_in("decision", REVIEW_DECISIONS), name="ck_review_decision"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"))
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    decision: Mapped[str] = mapped_column(String(16))
    rationale: Mapped[str] = mapped_column(Text)
    from_status: Mapped[str] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16))


RESERVATION_STATUSES = ("requested", "approved", "rejected", "released", "consumed")
LEDGER_ACCOUNTS = ("funding", "available", "reserved", "spent")


class Budget(TimestampMixin, Base):
    """Spending cap for one project, in integer US cents (UA-008)."""
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("project_id", name="uq_budget_project"),
                      CheckConstraint("cap_cents >= 0", name="ck_budget_cap"))

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    cap_cents: Mapped[int]
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    set_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Quote(TimestampMixin, Base):
    """A vendor quotation as recorded; never an order. Simulated quotes are labelled."""
    __tablename__ = "quotes"
    __table_args__ = (CheckConstraint("amount_cents > 0", name="ck_quote_amount"),
                      CheckConstraint(_in("origin", RESULT_ORIGINS), name="ck_quote_origin"))

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    vendor: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    amount_cents: Mapped[int]
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    origin: Mapped[str] = mapped_column(String(16))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))


class Reservation(TimestampMixin, Base):
    __tablename__ = "reservations"
    __table_args__ = (CheckConstraint("amount_cents > 0", name="ck_reservation_amount"),
                      CheckConstraint(_in("status", RESERVATION_STATUSES),
                                      name="ck_reservation_status"))

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    quote_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("quotes.id"))
    amount_cents: Mapped[int]
    purpose: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="requested")
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LedgerEntry(Base):
    """Append-only double-entry ledger: every posting's entries sum to zero."""
    __tablename__ = "ledger_entries"
    __table_args__ = (CheckConstraint(_in("account", LEDGER_ACCOUNTS), name="ck_ledger_account"),
                      Index("ix_ledger_project", "project_id", "account"))

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    posting_id: Mapped[uuid.UUID]
    account: Mapped[str] = mapped_column(String(16))
    amount_cents: Mapped[int]
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reservations.id"))
    memo: Mapped[str] = mapped_column(String(200))
    posted_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


JOB_STATES = ("queued", "running", "succeeded", "failed", "dead", "cancelled")


class Job(TimestampMixin, Base):
    """Durable unit of background work with leasing and bounded retries (UA-009)."""
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(_in("state", JOB_STATES), name="ck_job_state"),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_job_idempotency"),
        Index("ix_jobs_claimable", "state", "run_after"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    kind: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), default="queued")
    payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked_by: Mapped[str | None] = mapped_column(String(80))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxEvent(Base):
    """Transactional outbox: written in the same transaction as the state change it
    announces, delivered later at-least-once by the dispatcher."""
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_pending", "published_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    topic: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(default=0)


RUN_STATES = ("queued", "running", "completed", "failed", "cancelled")


class ExperimentRun(TimestampMixin, Base):
    """An experiment execution. In this codebase origin is always SIMULATED (UA-010);
    physical runs need the supervised adapter path (UA-013/UA-014/UA-027)."""
    __tablename__ = "experiment_runs"
    __table_args__ = (
        CheckConstraint(_in("origin", RESULT_ORIGINS), name="ck_run_origin"),
        CheckConstraint(_in("state", RUN_STATES), name="ck_run_state"),
        Index("ix_runs_project", "project_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    origin: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(120))
    model_version: Mapped[str] = mapped_column(String(40))
    design: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(16), default="queued")
    summary: Mapped[dict | None] = mapped_column(JSON)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


PROPOSAL_STATES = ("draft", "preflight_failed", "ready", "executing", "executed", "withdrawn")


class ProtocolVersion(TimestampMixin, Base):
    """Immutable, versioned protocol content (UA-011). A trigger rejects UPDATE/DELETE."""
    __tablename__ = "protocol_versions"
    __table_args__ = (UniqueConstraint("workspace_id", "key", "version", name="uq_protocol_version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(64))
    version: Mapped[int]
    title: Mapped[str] = mapped_column(String(160))
    content: Mapped[dict] = mapped_column(JSON)
    change_note: Mapped[str] = mapped_column(Text, default="")
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))


class ExperimentProposal(TimestampMixin, Base):
    __tablename__ = "experiment_proposals"
    __table_args__ = (
        CheckConstraint(_in("state", PROPOSAL_STATES), name="ck_proposal_state"),
        CheckConstraint(_in("target_origin", RESULT_ORIGINS), name="ck_proposal_target"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    protocol_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("protocol_versions.id"))
    title: Mapped[str] = mapped_column(String(160))
    hypothesis: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    evidence_claim_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_source_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_origin: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(20), default="draft")
    preflight: Mapped[dict | None] = mapped_column(JSON)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("experiment_runs.id"))
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    author_kind: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentTrace(TimestampMixin, Base):
    """Reviewable record of one planning call: exact input, provider output and the
    platform's validation outcome (UA-019). Append-only (trigger)."""
    __tablename__ = "agent_traces"
    __table_args__ = (Index("ix_agent_traces_project", "project_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    input_sha256: Mapped[str] = mapped_column(String(64))
    input: Mapped[dict] = mapped_column(JSON)
    output: Mapped[dict | None] = mapped_column(JSON)
    outcome: Mapped[str] = mapped_column(String(32))
    errors: Mapped[list[str]] = mapped_column(JSON, default=list)
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("experiment_proposals.id"))
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))


MATERIAL_KINDS = ("strain", "culture", "sample", "extract", "plant_material", "reagent")
MATERIAL_STATUSES = ("active", "consumed", "disposed")
LINEAGE_RELATIONS = ("derived_from", "split_from", "pooled_from", "subcultured_from")
CUSTODY_EVENTS = ("registered", "transferred", "received", "stored", "shipped", "consumed",
                  "disposed")


class Material(TimestampMixin, Base):
    """A biological material or sample (UA-012). Origin is permanent provenance."""
    __tablename__ = "materials"
    __table_args__ = (
        CheckConstraint(_in("kind", MATERIAL_KINDS), name="ck_material_kind"),
        CheckConstraint(_in("status", MATERIAL_STATUSES), name="ck_material_status"),
        CheckConstraint(_in("origin", RESULT_ORIGINS), name="ck_material_origin"),
        UniqueConstraint("workspace_id", "label", name="uq_material_label"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    kind: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(120))
    organism: Mapped[str | None] = mapped_column(String(120))
    origin: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="active")
    custodian: Mapped[str] = mapped_column(String(120))
    location: Mapped[str] = mapped_column(String(200), default="")
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("experiment_runs.id"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))


class LineageEdge(TimestampMixin, Base):
    """parent -> child derivation. Append-only; the graph is kept acyclic in code."""
    __tablename__ = "lineage_edges"
    __table_args__ = (
        UniqueConstraint("parent_id", "child_id", name="uq_lineage_edge"),
        CheckConstraint("parent_id <> child_id", name="ck_lineage_no_self"),
        CheckConstraint(_in("relation", LINEAGE_RELATIONS), name="ck_lineage_relation"),
        Index("ix_lineage_child", "child_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    parent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("materials.id"))
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("materials.id"))
    relation: Mapped[str] = mapped_column(String(32))
    recorded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))


class CustodyEvent(Base):
    """Append-only chain of custody for a material."""
    __tablename__ = "custody_events"
    __table_args__ = (CheckConstraint(_in("event", CUSTODY_EVENTS), name="ck_custody_event"),
                      Index("ix_custody_material", "material_id", "occurred_at"))

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    material_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("materials.id"))
    event: Mapped[str] = mapped_column(String(16))
    from_party: Mapped[str | None] = mapped_column(String(120))
    to_party: Mapped[str | None] = mapped_column(String(120))
    location: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    recorded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


LAB_STATUSES = ("prospect", "onboarding", "contracted", "suspended")
CONTRACT_STATUSES = ("draft", "signed", "expired", "terminated")


class Laboratory(TimestampMixin, Base):
    """A laboratory in the workspace's network with its adapter and capabilities (UA-013)."""
    __tablename__ = "laboratories"
    __table_args__ = (CheckConstraint(_in("status", LAB_STATUSES), name="ck_lab_status"),
                      UniqueConstraint("workspace_id", "name", name="uq_lab_name"))

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    adapter_key: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="prospect")
    capabilities: Mapped[list[dict]] = mapped_column(JSON, default=list)
    public_contact: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LabContract(TimestampMixin, Base):
    """Contract metadata only; documents live in artifact storage (UA-015)."""
    __tablename__ = "lab_contracts"
    __table_args__ = (CheckConstraint(_in("status", CONTRACT_STATUSES),
                                      name="ck_lab_contract_status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    laboratory_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("laboratories.id"))
    title: Mapped[str] = mapped_column(String(160))
    scope: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    max_value_cents: Mapped[int] = mapped_column(default=0)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))


ARTIFACT_SOURCES = ("upload", "adapter", "simulator", "cro_exchange", "export")


class ArtifactBlob(Base):
    """Content-addressed bytes (default store). Immutable via trigger."""
    __tablename__ = "artifact_blobs"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    size: Mapped[int]
    content: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Artifact(TimestampMixin, Base):
    """Immutable laboratory artifact with provenance (UA-015)."""
    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint(_in("origin", RESULT_ORIGINS), name="ck_artifact_origin"),
        CheckConstraint(_in("source", ARTIFACT_SOURCES), name="ck_artifact_source"),
        Index("ix_artifacts_project", "project_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("experiment_runs.id"))
    material_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("materials.id"))
    name: Mapped[str] = mapped_column(String(200))
    media_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    store: Mapped[str] = mapped_column(String(16))
    origin: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))


class ArtifactIngestion(TimestampMixin, Base):
    """At most one ingestion per artifact; records what it produced."""
    __tablename__ = "artifact_ingestions"
    __table_args__ = (UniqueConstraint("artifact_id", name="uq_ingestion_artifact"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artifacts.id"))
    parser: Mapped[str] = mapped_column(String(40))
    assay_map: Mapped[dict] = mapped_column(JSON)
    measurement_count: Mapped[int]
    ingested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))


WORK_ORDER_STATES = ("draft", "approved", "dispatched", "in_progress", "results_received",
                     "closed", "cancelled")


class WorkOrder(TimestampMixin, Base):
    """Supervised manual CRO work order (UA-014). Dispatch is a physical action."""
    __tablename__ = "work_orders"
    __table_args__ = (CheckConstraint(_in("state", WORK_ORDER_STATES), name="ck_work_order_state"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    laboratory_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("laboratories.id"))
    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("experiment_proposals.id"))
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reservations.id"))
    title: Mapped[str] = mapped_column(String(160))
    state: Mapped[str] = mapped_column(String(20), default="draft")
    package_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    package_sha256: Mapped[str | None] = mapped_column(String(64))
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExchangeItem(TimestampMixin, Base):
    """Append-only log of what was exchanged with the CRO, and by whom."""
    __tablename__ = "exchange_items"
    __table_args__ = (CheckConstraint("direction IN ('outbound', 'inbound', 'note')",
                                      name="ck_exchange_direction"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    work_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_orders.id"))
    direction: Mapped[str] = mapped_column(String(10))
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    note: Mapped[str] = mapped_column(Text, default="")
    recorded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))


class QcReport(TimestampMixin, Base):
    """Immutable QC evaluation of one assay dataset; disposition recorded separately."""
    __tablename__ = "qc_reports"
    __table_args__ = (CheckConstraint("status IN ('pass', 'warn', 'fail')", name="ck_qc_status"),
                      CheckConstraint(_in("origin", RESULT_ORIGINS), name="ck_qc_origin"),
                      Index("ix_qc_project", "project_id", "created_at"))

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("experiment_runs.id"))
    assay_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assays.id"))
    origin: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(8))
    metrics: Mapped[dict] = mapped_column(JSON)
    flags: Mapped[list[dict]] = mapped_column(JSON)
    measurement_ids_sha256: Mapped[str] = mapped_column(String(64))
    generated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))


class QcDisposition(TimestampMixin, Base):
    __tablename__ = "qc_dispositions"
    __table_args__ = (UniqueConstraint("report_id", name="uq_qc_disposition"),
                      CheckConstraint("decision IN ('accepted', 'rejected')",
                                      name="ck_qc_decision"))

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("qc_reports.id"))
    decision: Mapped[str] = mapped_column(String(10))
    rationale: Mapped[str] = mapped_column(Text)
    decided_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))


class OptimizationRound(TimestampMixin, Base):
    """Append-only record of one next-experiment selection (UA-020)."""
    __tablename__ = "optimization_rounds"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    objective: Mapped[str] = mapped_column(String(40))
    origin: Mapped[str] = mapped_column(String(16))
    bounds: Mapped[dict] = mapped_column(JSON)
    observations: Mapped[list[dict]] = mapped_column(JSON)
    suggestions: Mapped[list[dict]] = mapped_column(JSON)
    queued_run_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    strategy: Mapped[str] = mapped_column(String(40))
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
