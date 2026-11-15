"""Request/response models for the authenticated v1 research API."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Slug = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
Name = Field(min_length=1, max_length=120)
Role = Literal["owner", "admin", "scientist", "reviewer", "viewer", "agent"]
Program = Literal["M1", "M2", "A1", "OTHER"]
ProjectStatus = Literal["planning", "active", "paused", "archived"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PrincipalOut(Output):
    id: uuid.UUID
    kind: Literal["human", "agent"]
    display_name: str
    email: str | None
    created_at: datetime


class WorkspaceOut(Output):
    id: uuid.UUID
    slug: str
    name: str
    created_at: datetime


class WorkspaceMembershipOut(Output):
    workspace: WorkspaceOut
    role: Role


class MeOut(Output):
    principal: PrincipalOut
    memberships: list[WorkspaceMembershipOut]
    live_lab_orders_enabled: Literal[False] = False


class TokenOut(Output):
    id: uuid.UUID
    label: str
    prefix: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None


class IssuedToken(Output):
    token: TokenOut
    secret: str = Field(description="Shown exactly once. Only a digest is stored.")


class BootstrapIn(Input):
    display_name: str = Name
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    workspace_name: str = Name
    workspace_slug: str = Slug


class BootstrapOut(Output):
    principal: PrincipalOut
    workspace: WorkspaceOut
    issued: IssuedToken


class WorkspaceIn(Input):
    name: str = Name
    slug: str = Slug


class MemberIn(Input):
    """Create a new principal in this workspace and issue its first token."""
    kind: Literal["human", "agent"]
    display_name: str = Name
    email: str | None = Field(default=None, min_length=3, max_length=254,
                              pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: Role


class MemberOut(Output):
    principal: PrincipalOut
    role: Role


class MemberCreated(Output):
    member: MemberOut
    issued: IssuedToken


class TokenIn(Input):
    label: str = Field(min_length=1, max_length=80)
    ttl_days: int | None = Field(default=None, ge=1, le=365)


class ProjectIn(Input):
    name: str = Name
    slug: str = Slug
    program: Program
    objective: str = Field(default="", max_length=4000)


class ProjectPatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: ProjectStatus | None = None
    objective: str | None = Field(default=None, max_length=4000)


class ProjectOut(Output):
    id: uuid.UUID
    workspace_id: uuid.UUID
    slug: str
    name: str
    program: Program
    status: ProjectStatus
    objective: str
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
