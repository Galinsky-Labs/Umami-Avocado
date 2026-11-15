"""Evidence-linked research agent planning with reviewable traces (UA-019)."""
import hashlib
import json
import uuid

from fastapi import APIRouter
from sqlalchemy import func, select

from umami_api.agents.providers import (
    Evidence,
    PlanningContext,
    PriorRun,
    ProviderError,
    get_provider,
)
from umami_api.authz import authorize
from umami_api.models import (
    AgentTrace,
    Claim,
    EvidenceSource,
    ExperimentProposal,
    ExperimentRun,
    ProtocolVersion,
)
from umami_api.policy import Subject
from umami_api.schemas import AgentTraceOut
from umami_api.security import AccessDep, WorkspaceAccess
from umami_api.v1.projects import get_project
from umami_api.v1.studio import evaluate

router = APIRouter(tags=["agents"])
PROVIDER_FACTORY = get_provider  # replaced in tests


def build_context(access: WorkspaceAccess, project) -> PlanningContext:
    claims = access.session.scalars(select(Claim).where(
        Claim.workspace_id == access.workspace.id, Claim.status != "retracted",
        (Claim.project_id == project.id) | Claim.project_id.is_(None))
        .order_by(Claim.created_at).limit(20)).all()
    sources = access.session.scalars(select(EvidenceSource).where(
        EvidenceSource.workspace_id == access.workspace.id)
        .order_by(EvidenceSource.created_at).limit(20)).all()
    evidence = tuple(
        [Evidence(id=f"claim:{c.id}", kind="claim", text=f"[{c.status}] {c.statement}"[:600])
         for c in claims]
        + [Evidence(id=f"source:{s.id}", kind="source",
                    text=f"[{'verified' if s.verified_at else 'unverified'}] {s.citation}"[:600])
           for s in sources])
    runs = access.session.scalars(select(ExperimentRun).where(
        ExperimentRun.project_id == project.id, ExperimentRun.state == "completed",
        ExperimentRun.origin == "SIMULATED").order_by(ExperimentRun.created_at).limit(50)).all()
    prior = tuple(PriorRun(temperature_c=float(r.design["temperature_c"]),
                           ph=float(r.design["ph"]),
                           initial_glucose_g_l=float(r.design["initial_glucose_g_l"]),
                           final_biomass_g_l=float(r.summary["biomass_concentration"]))
                  for r in runs if r.summary)
    return PlanningContext(project_name=project.name, program=project.program,
                           objective=project.objective, evidence=evidence, prior_runs=prior)


@router.post("/workspaces/{workspace_id}/projects/{project_id}/agent/plan",
             response_model=AgentTraceOut, status_code=201, operation_id="plan_next_experiment")
def plan(project_id: uuid.UUID, access: AccessDep):
    """Ask the configured planning provider for the next SIMULATED experiment.

    The draft becomes an immutable protocol version and a SIMULATED proposal only if every
    citation refers to supplied evidence; preflight then runs. Execution stays a separate,
    separately authorized step."""
    project = get_project(access, project_id)
    subject = Subject(project_id=project.id)
    authorize(access, "agent.run", subject, ("project", project.id))
    authorize(access, "experiment.draft", subject, ("project", project.id))
    context = build_context(access, project)
    payload = json.loads(context.as_json())
    provider = PROVIDER_FACTORY()
    trace = AgentTrace(workspace_id=access.workspace.id, project_id=project.id,
                       provider=provider.name, model=provider.model,
                       input_sha256=hashlib.sha256(context.as_json().encode()).hexdigest(),
                       input=payload, requested_by=access.principal.id, errors=[])
    try:
        draft = provider.plan(context)
    except ProviderError as error:
        trace.outcome, trace.errors = "provider_error", [str(error)]
        access.session.add(trace)
        access.session.flush()
        return trace
    trace.output = draft.model_dump()
    known = {e.id for e in context.evidence}
    unknown = [c for c in draft.cited_evidence_ids if c not in known]
    if not context.evidence:
        trace.errors = ["No evidence is linked to this workspace; add sources or claims first."]
    elif unknown:
        trace.errors = ["Draft cited evidence that was not supplied: " + ", ".join(unknown)[:300]]
    if trace.errors:
        trace.outcome = "rejected"
        access.session.add(trace)
        access.session.flush()
        return trace
    key = f"agent-plan-{project.slug}"[:64]
    version = (access.session.scalar(select(func.max(ProtocolVersion.version)).where(
        ProtocolVersion.workspace_id == access.workspace.id, ProtocolVersion.key == key)) or 0) + 1
    protocol = ProtocolVersion(
        workspace_id=access.workspace.id, key=key, version=version, title=draft.title,
        author_id=access.principal.id,
        change_note=f"Drafted by planning provider {provider.name}/{provider.model}.",
        content={"organism": "Saccharomyces cerevisiae", "biosafety_level": 1,
                 "medium": "Defined glucose medium (simulated)",
                 "temperature_c": draft.temperature_c, "ph": draft.ph,
                 "initial_glucose_g_l": draft.initial_glucose_g_l, "initial_biomass_g_l": 0.1,
                 "duration_h": draft.duration_h, "sample_interval_h": 2.0,
                 "biological_replicates": 3, "technical_replicates": 1,
                 "assay_keys": ["sim-dcw", "sim-glucose", "sim-glutamate"],
                 "steps": ["Simulated inoculation", "Simulated incubation", "Simulated sampling"],
                 "estimated_cost_cents": 0})
    access.session.add(protocol)
    access.session.flush()
    claim_ids = [c.split(":", 1)[1] for c in draft.cited_evidence_ids if c.startswith("claim:")]
    source_ids = [c.split(":", 1)[1] for c in draft.cited_evidence_ids if c.startswith("source:")]
    proposal = ExperimentProposal(
        workspace_id=access.workspace.id, project_id=project.id,
        protocol_version_id=protocol.id, title=draft.title, hypothesis=draft.hypothesis,
        rationale=f"[{provider.name}/{provider.model}] {draft.rationale}"[:8000],
        evidence_claim_ids=claim_ids, evidence_source_ids=source_ids, target_origin="SIMULATED",
        author_id=access.principal.id, author_kind=access.principal.kind)
    access.session.add(proposal)
    access.session.flush()
    result = evaluate(access, proposal)
    proposal.preflight = result
    proposal.state = "ready" if result["passed"] else "preflight_failed"
    trace.outcome, trace.proposal_id = "proposal_created", proposal.id
    access.session.add(trace)
    access.session.flush()
    return trace


@router.get("/workspaces/{workspace_id}/projects/{project_id}/agent/traces",
            response_model=list[AgentTraceOut], operation_id="list_agent_traces")
def traces(project_id: uuid.UUID, access: AccessDep):
    project = get_project(access, project_id)
    return access.session.scalars(select(AgentTrace).where(AgentTrace.project_id == project.id)
                                  .order_by(AgentTrace.created_at.desc()).limit(100)).all()


@router.get("/workspaces/{workspace_id}/agent/traces", response_model=list[AgentTraceOut],
            operation_id="list_workspace_agent_traces")
def workspace_traces(access: AccessDep, outcome: str | None = None):
    """All planning traces in the workspace, newest first (review queue for UA-021)."""
    query = select(AgentTrace).where(AgentTrace.workspace_id == access.workspace.id)
    if outcome:
        query = query.where(AgentTrace.outcome == outcome)
    return access.session.scalars(query.order_by(AgentTrace.created_at.desc()).limit(200)).all()
