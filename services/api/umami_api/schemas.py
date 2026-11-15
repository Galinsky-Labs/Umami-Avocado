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


AgentAction = Literal["evidence.add", "claim.propose", "measurement.record_simulated",
                      "experiment.draft", "experiment.submit_simulated", "quote.record",
                      "agent.run"]


class ResearchContractIn(Input):
    agent_id: uuid.UUID
    purpose: str = Field(min_length=1, max_length=2000)
    actions: list[AgentAction] = Field(min_length=1, max_length=16)
    project_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    ttl_days: int = Field(ge=1, le=90)


class ResearchContractOut(Output):
    id: uuid.UUID
    workspace_id: uuid.UUID
    agent_id: uuid.UUID
    granted_by: uuid.UUID
    purpose: str
    actions: list[str]
    project_ids: list[str] | None
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime


class AuditEventOut(Output):
    id: uuid.UUID
    actor_id: uuid.UUID
    actor_kind: str
    action: str
    resource_type: str | None
    resource_id: str | None
    decision: Literal["allow", "deny"]
    reason: str
    occurred_at: datetime


class PolicyDecisionOut(Output):
    action: str
    allowed: bool
    reason: str


Origin = Literal["SIMULATED", "PHYSICAL"]


class UnitOut(Output):
    symbol: str
    name: str
    dimension: dict[str, int]
    convertible: bool


class QuantityKindOut(Output):
    key: str
    label: str
    canonical_unit: str
    admissible_units: list[str]


class OntologyOut(Output):
    units: list[UnitOut]
    quantity_kinds: list[QuantityKindOut]
    replicate_semantics: str


class ConvertIn(Input):
    value: float = Field(allow_inf_nan=False)
    from_unit: str = Field(max_length=16)
    to_unit: str = Field(max_length=16)


class ConvertOut(Output):
    value: float
    unit: str


class AssayIn(Input):
    key: str = Slug
    name: str = Name
    quantity_kind: str = Field(max_length=64)
    unit: str = Field(max_length=16)
    method: str = Field(default="", max_length=8000)


class AssayOut(Output):
    id: uuid.UUID
    key: str
    version: int
    name: str
    quantity_kind: str
    unit: str
    method: str
    created_by: uuid.UUID
    created_at: datetime


class MeasurementIn(Input):
    assay_id: uuid.UUID
    origin: Origin
    sample_label: str = Field(min_length=1, max_length=120)
    biological_replicate: int = Field(ge=1, le=1000)
    technical_replicate: int = Field(default=1, ge=1, le=1000)
    value: float = Field(allow_inf_nan=False)
    unit: str = Field(max_length=16)
    observed_at: datetime
    provenance: str = Field(default="", max_length=4000)
    supersedes_id: uuid.UUID | None = None


class MeasurementOut(Output):
    id: uuid.UUID
    project_id: uuid.UUID
    assay_id: uuid.UUID
    origin: Origin
    sample_label: str
    biological_replicate: int
    technical_replicate: int
    value: float
    unit: str
    value_canonical: float
    observed_at: datetime
    run_id: uuid.UUID | None
    provenance: str
    supersedes_id: uuid.UUID | None
    recorded_by: uuid.UUID
    recorded_at: datetime


class SampleSummaryOut(Output):
    sample_label: str
    origin: Origin
    unit: str
    mean: float | None
    sd: float | None
    n_biological: int
    n_technical: int
