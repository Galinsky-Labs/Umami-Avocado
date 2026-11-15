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


SourceKind = Literal["doi", "url", "book", "dataset", "internal_measurement", "other"]
ClaimStatus = Literal["draft", "under_review", "accepted", "rejected", "retracted"]
Stance = Literal["supports", "contradicts", "context"]


class SourceIn(Input):
    kind: SourceKind
    identifier: str = Field(min_length=1, max_length=300)
    citation: str = Field(min_length=1, max_length=4000)
    url: str | None = Field(default=None, max_length=500, pattern=r"^https?://\S+$")


class SourceOut(Output):
    id: uuid.UUID
    kind: SourceKind
    identifier: str
    citation: str
    url: str | None
    added_by: uuid.UUID
    added_by_kind: str
    verified_by: uuid.UUID | None
    verified_at: datetime | None
    created_at: datetime


class ClaimIn(Input):
    statement: str = Field(min_length=5, max_length=4000)
    scope_conditions: str = Field(default="", max_length=4000)
    project_id: uuid.UUID | None = None


class EvidenceIn(Input):
    source_id: uuid.UUID | None = None
    measurement_id: uuid.UUID | None = None
    stance: Stance
    excerpt: str = Field(default="", max_length=4000)


class EvidenceOut(Output):
    id: uuid.UUID
    source_id: uuid.UUID | None
    measurement_id: uuid.UUID | None
    stance: Stance
    excerpt: str
    added_by: uuid.UUID
    created_at: datetime


class ReviewIn(Input):
    decision: Literal["accept", "reject", "request_changes", "retract"]
    rationale: str = Field(min_length=10, max_length=4000)


class ReviewOut(Output):
    id: uuid.UUID
    reviewer_id: uuid.UUID
    decision: str
    rationale: str
    from_status: ClaimStatus
    to_status: ClaimStatus
    created_at: datetime


class ClaimOut(Output):
    id: uuid.UUID
    project_id: uuid.UUID | None
    statement: str
    scope_conditions: str
    status: ClaimStatus
    author_id: uuid.UUID
    author_kind: str
    created_at: datetime
    updated_at: datetime


class ClaimDetailOut(ClaimOut):
    evidence: list[EvidenceOut]
    reviews: list[ReviewOut]


Cents = Field(gt=0, le=100_000_000)


class BudgetIn(Input):
    cap_cents: int = Field(ge=0, le=100_000_000)


class BalancesOut(Output):
    project_id: uuid.UUID
    cap_cents: int
    available_cents: int
    reserved_cents: int
    spent_cents: int
    platform_cap_cents: int
    currency: Literal["USD"] = "USD"


class QuoteIn(Input):
    project_id: uuid.UUID
    vendor: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=4000)
    amount_cents: int = Cents
    origin: Origin
    valid_until: datetime | None = None


class QuoteOut(Output):
    id: uuid.UUID
    project_id: uuid.UUID
    vendor: str
    description: str
    amount_cents: int
    currency: str
    origin: Origin
    valid_until: datetime | None
    recorded_by: uuid.UUID
    created_at: datetime


class ReservationIn(Input):
    project_id: uuid.UUID
    amount_cents: int = Cents
    purpose: str = Field(min_length=5, max_length=2000)
    quote_id: uuid.UUID | None = None


class ReservationOut(Output):
    id: uuid.UUID
    project_id: uuid.UUID
    quote_id: uuid.UUID | None
    amount_cents: int
    purpose: str
    status: Literal["requested", "approved", "rejected", "released", "consumed"]
    requested_by: uuid.UUID
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    created_at: datetime


class LedgerEntryOut(Output):
    id: uuid.UUID
    posting_id: uuid.UUID
    account: str
    amount_cents: int
    reservation_id: uuid.UUID | None
    memo: str
    posted_by: uuid.UUID
    posted_at: datetime


class JobIn(Input):
    kind: Literal["diagnostic.echo"]
    payload: dict = Field(default_factory=dict)
    project_id: uuid.UUID | None = None
    max_attempts: int = Field(default=3, ge=1, le=10)


class JobOut(Output):
    id: uuid.UUID
    project_id: uuid.UUID | None
    kind: str
    state: Literal["queued", "running", "succeeded", "failed", "dead", "cancelled"]
    payload: dict
    result: dict | None
    attempts: int
    max_attempts: int
    run_after: datetime
    last_error: str | None
    idempotency_key: str | None
    created_by: uuid.UUID
    created_at: datetime
    finished_at: datetime | None


class OutboxEventOut(Output):
    id: uuid.UUID
    topic: str
    payload: dict
    created_at: datetime
    published_at: datetime | None


class SimulationDesignIn(Input):
    label: str = Field(min_length=1, max_length=120)
    temperature_c: float = Field(ge=4, le=45, allow_inf_nan=False)
    ph: float = Field(ge=3, le=8, allow_inf_nan=False)
    initial_glucose_g_l: float = Field(gt=0, le=150, allow_inf_nan=False)
    initial_biomass_g_l: float = Field(default=0.1, gt=0, le=5, allow_inf_nan=False)
    duration_h: float = Field(default=24, gt=0, le=96, allow_inf_nan=False)
    sample_interval_h: float = Field(default=2, ge=0.5, le=24, allow_inf_nan=False)
    biological_replicates: int = Field(default=3, ge=1, le=6)
    technical_replicates: int = Field(default=1, ge=1, le=3)
    seed: int = Field(default=1, ge=0, le=2**31 - 1)


class RunOut(Output):
    id: uuid.UUID
    project_id: uuid.UUID
    origin: Origin
    label: str
    model_version: str
    design: dict
    state: Literal["queued", "running", "completed", "failed", "cancelled"]
    summary: dict | None
    job_id: uuid.UUID | None
    created_by: uuid.UUID
    created_at: datetime
    completed_at: datetime | None


class MilestoneCheckOut(Output):
    key: str
    description: str
    met: bool


class DigitalMilestoneOut(Output):
    project_id: uuid.UUID
    achieved: bool
    checks: list[MilestoneCheckOut]
    physical_results_exist: bool
    note: str


Organism = Literal["Saccharomyces cerevisiae", "Cyberlindnera jadinii", "Kluyveromyces marxianus"]


class ProtocolContent(Input):
    organism: Organism
    biosafety_level: Literal[1] = 1
    medium: str = Field(min_length=1, max_length=500)
    temperature_c: float = Field(ge=4, le=45, allow_inf_nan=False)
    ph: float = Field(ge=3, le=8, allow_inf_nan=False)
    initial_glucose_g_l: float = Field(gt=0, le=150, allow_inf_nan=False)
    initial_biomass_g_l: float = Field(default=0.1, gt=0, le=5, allow_inf_nan=False)
    duration_h: float = Field(gt=0, le=96, allow_inf_nan=False)
    sample_interval_h: float = Field(default=2, ge=0.5, le=24, allow_inf_nan=False)
    biological_replicates: int = Field(default=3, ge=1, le=6)
    technical_replicates: int = Field(default=1, ge=1, le=3)
    assay_keys: list[str] = Field(default_factory=list, max_length=20)
    steps: list[str] = Field(min_length=1, max_length=50)
    estimated_cost_cents: int = Field(default=0, ge=0, le=100_000_000)


class ProtocolIn(Input):
    key: str = Slug
    title: str = Field(min_length=1, max_length=160)
    content: ProtocolContent
    change_note: str = Field(default="", max_length=2000)


class ProtocolOut(Output):
    id: uuid.UUID
    key: str
    version: int
    title: str
    content: dict
    change_note: str
    author_id: uuid.UUID
    created_at: datetime


class ProposalIn(Input):
    protocol_version_id: uuid.UUID
    title: str = Field(min_length=1, max_length=160)
    hypothesis: str = Field(min_length=10, max_length=4000)
    rationale: str = Field(default="", max_length=8000)
    evidence_claim_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    evidence_source_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    target_origin: Origin = "SIMULATED"


class PreflightCheckOut(Output):
    key: str
    passed: bool
    severity: Literal["blocker", "warning"]
    message: str


class ProposalOut(Output):
    id: uuid.UUID
    project_id: uuid.UUID
    protocol_version_id: uuid.UUID
    title: str
    hypothesis: str
    rationale: str
    evidence_claim_ids: list[str]
    evidence_source_ids: list[str]
    target_origin: Origin
    state: Literal["draft", "preflight_failed", "ready", "executing", "executed", "withdrawn"]
    preflight: dict | None
    run_id: uuid.UUID | None
    author_id: uuid.UUID
    author_kind: str
    created_at: datetime
    updated_at: datetime
