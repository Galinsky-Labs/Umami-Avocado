"""Persistent schema. Every research record is scoped to exactly one workspace.

Schema changes are made only through Alembic migrations in umami_api/migrations.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
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
