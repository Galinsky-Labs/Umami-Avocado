"""Experiment studio: versioned protocols, evidence-linked proposals and preflight (UA-011)."""
import uuid

from fastapi import APIRouter
from sqlalchemy import func, select

from umami_api.authz import authorize
from umami_api.db import utcnow
from umami_api.errors import conflict, invalid, not_found
from umami_api.models import Assay, Claim, EvidenceSource, ExperimentProposal, ProtocolVersion
from umami_api.policy import Subject
from umami_api.schemas import ProposalIn, ProposalOut, ProtocolIn, ProtocolOut
from umami_api.science.preflight import run_preflight
from umami_api.security import AccessDep, WorkspaceAccess
from umami_api.simulation import SIMULATED_ASSAYS
from umami_api.v1.projects import get_project
from umami_api.v1.simulator import create_simulated_run

router = APIRouter(tags=["studio"])
SIMULATOR_FIELDS = ("temperature_c", "ph", "initial_glucose_g_l", "initial_biomass_g_l",
                    "duration_h", "sample_interval_h", "biological_replicates",
                    "technical_replicates")


@router.get("/workspaces/{workspace_id}/protocols", response_model=list[ProtocolOut],
            operation_id="list_protocols")
def list_protocols(access: AccessDep):
    return access.session.scalars(select(ProtocolVersion).where(
        ProtocolVersion.workspace_id == access.workspace.id)
        .order_by(ProtocolVersion.key, ProtocolVersion.version)).all()


@router.post("/workspaces/{workspace_id}/protocols", response_model=ProtocolOut, status_code=201,
             operation_id="create_protocol_version")
def create_protocol(body: ProtocolIn, access: AccessDep):
    """Protocol versions are immutable; posting an existing key creates the next version."""
    authorize(access, "experiment.draft")
    latest = access.session.scalar(select(func.max(ProtocolVersion.version)).where(
        ProtocolVersion.workspace_id == access.workspace.id,
        ProtocolVersion.key == body.key)) or 0
    protocol = ProtocolVersion(workspace_id=access.workspace.id, key=body.key,
                               version=latest + 1, title=body.title,
                               content=body.content.model_dump(), change_note=body.change_note,
                               author_id=access.principal.id)
    access.session.add(protocol)
    access.session.flush()
    return protocol


def _protocol(access: WorkspaceAccess, protocol_id: uuid.UUID) -> ProtocolVersion:
    protocol = access.session.scalar(select(ProtocolVersion).where(
        ProtocolVersion.id == protocol_id, ProtocolVersion.workspace_id == access.workspace.id))
    if protocol is None:
        raise not_found("protocol version")
    return protocol


def _proposal(access: WorkspaceAccess, project_id: uuid.UUID,
              proposal_id: uuid.UUID) -> ExperimentProposal:
    proposal = access.session.scalar(select(ExperimentProposal).where(
        ExperimentProposal.id == proposal_id, ExperimentProposal.project_id == project_id,
        ExperimentProposal.workspace_id == access.workspace.id).with_for_update())
    if proposal is None:
        raise not_found("proposal")
    return proposal


@router.get("/workspaces/{workspace_id}/projects/{project_id}/proposals",
            response_model=list[ProposalOut], operation_id="list_proposals")
def list_proposals(project_id: uuid.UUID, access: AccessDep):
    project = get_project(access, project_id)
    return access.session.scalars(select(ExperimentProposal).where(
        ExperimentProposal.project_id == project.id)
        .order_by(ExperimentProposal.created_at.desc())).all()


@router.post("/workspaces/{workspace_id}/projects/{project_id}/proposals",
             response_model=ProposalOut, status_code=201, operation_id="create_proposal")
def create_proposal(project_id: uuid.UUID, body: ProposalIn, access: AccessDep):
    project = get_project(access, project_id)
    authorize(access, "experiment.draft", Subject(project_id=project.id), ("project", project.id))
    _protocol(access, body.protocol_version_id)
    proposal = ExperimentProposal(
        workspace_id=access.workspace.id, project_id=project.id,
        protocol_version_id=body.protocol_version_id, title=body.title,
        hypothesis=body.hypothesis, rationale=body.rationale,
        evidence_claim_ids=[str(c) for c in body.evidence_claim_ids],
        evidence_source_ids=[str(s) for s in body.evidence_source_ids],
        target_origin=body.target_origin, author_id=access.principal.id,
        author_kind=access.principal.kind)
    access.session.add(proposal)
    access.session.flush()
    return proposal


@router.get("/workspaces/{workspace_id}/projects/{project_id}/proposals/{proposal_id}",
            response_model=ProposalOut, operation_id="get_proposal")
def get_proposal(project_id: uuid.UUID, proposal_id: uuid.UUID, access: AccessDep):
    return _proposal(access, get_project(access, project_id).id, proposal_id)


def evaluate(access: WorkspaceAccess, proposal: ExperimentProposal) -> dict:
    protocol = _protocol(access, proposal.protocol_version_id)
    claim_ids = [uuid.UUID(c) for c in proposal.evidence_claim_ids]
    source_ids = [uuid.UUID(s) for s in proposal.evidence_source_ids]
    found_claims = access.session.scalar(select(func.count()).select_from(Claim).where(
        Claim.workspace_id == access.workspace.id, Claim.id.in_(claim_ids),
        Claim.status != "retracted")) if claim_ids else 0
    found_sources = access.session.scalar(select(func.count()).select_from(EvidenceSource).where(
        EvidenceSource.workspace_id == access.workspace.id,
        EvidenceSource.id.in_(source_ids))) if source_ids else 0
    evidence_ok = (found_claims + found_sources) > 0 and found_claims == len(claim_ids) and \
        found_sources == len(source_ids)
    keys = set(protocol.content.get("assay_keys", []))
    defined = set(access.session.scalars(select(Assay.key).where(
        Assay.workspace_id == access.workspace.id, Assay.key.in_(keys)))) if keys else set()
    simulated = {key for key, _ in SIMULATED_ASSAYS.values()}
    missing = sorted(keys - defined - simulated)
    return run_preflight(content=protocol.content, target_origin=proposal.target_origin,
                         evidence_ok=evidence_ok, missing_assays=missing,
                         live_submission_enabled=access.caller.settings.lab_live_submission_enabled)


@router.post("/workspaces/{workspace_id}/projects/{project_id}/proposals/{proposal_id}/preflight",
             response_model=ProposalOut, operation_id="preflight_proposal")
def preflight(project_id: uuid.UUID, proposal_id: uuid.UUID, access: AccessDep):
    proposal = _proposal(access, get_project(access, project_id).id, proposal_id)
    authorize(access, "experiment.draft", Subject(project_id=proposal.project_id),
              ("proposal", proposal.id))
    if proposal.state not in ("draft", "preflight_failed", "ready"):
        raise conflict("Only unexecuted proposals can be preflighted.")
    result = evaluate(access, proposal)
    result["evaluated_at"] = utcnow().isoformat()
    proposal.preflight = result
    proposal.state = "ready" if result["passed"] else "preflight_failed"
    proposal.updated_at = utcnow()
    return proposal


@router.post("/workspaces/{workspace_id}/projects/{project_id}/proposals/{proposal_id}/execute",
             response_model=ProposalOut, operation_id="execute_proposal")
def execute(project_id: uuid.UUID, proposal_id: uuid.UUID, access: AccessDep):
    """Execute a ready SIMULATED proposal. Preflight is re-evaluated at execution time."""
    project = get_project(access, project_id)
    proposal = _proposal(access, project.id, proposal_id)
    action = ("experiment.submit_physical" if proposal.target_origin == "PHYSICAL"
              else "experiment.submit_simulated")
    authorize(access, action, Subject(project_id=project.id), ("proposal", proposal.id))
    if proposal.state != "ready":
        raise conflict("Only proposals that passed preflight can be executed.")
    if not evaluate(access, proposal)["passed"]:
        raise conflict("Preflight no longer passes; re-run preflight.")
    protocol = _protocol(access, proposal.protocol_version_id)
    design = {field: protocol.content[field] for field in SIMULATOR_FIELDS}
    design["seed"] = int(proposal.id.int % (2**31 - 1))
    run = create_simulated_run(access, project, design, proposal.title[:120],
                               idempotency_key=f"proposal:{proposal.id}")
    proposal.run_id, proposal.state, proposal.updated_at = run.id, "executing", utcnow()
    return proposal


@router.post("/workspaces/{workspace_id}/projects/{project_id}/proposals/{proposal_id}/withdraw",
             response_model=ProposalOut, operation_id="withdraw_proposal")
def withdraw(project_id: uuid.UUID, proposal_id: uuid.UUID, access: AccessDep):
    proposal = _proposal(access, get_project(access, project_id).id, proposal_id)
    authorize(access, "experiment.draft", Subject(project_id=proposal.project_id),
              ("proposal", proposal.id))
    if proposal.state in ("executing", "executed"):
        raise invalid("Executed proposals cannot be withdrawn.")
    proposal.state, proposal.updated_at = "withdrawn", utcnow()
    return proposal
