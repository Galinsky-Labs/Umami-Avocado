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
