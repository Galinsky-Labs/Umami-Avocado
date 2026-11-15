"""Evidence registry and human scientific claim review (UA-004).

Agents may propose claims and attach evidence under a research contract; only humans
with review rights, who did not author the claim, may accept, reject or retract it.
Acceptance needs at least one supporting link to a human-verified source or a
PHYSICAL measurement: simulated results alone never establish a claim.
"""
import uuid

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from umami_api.authz import authorize
from umami_api.db import utcnow
from umami_api.errors import conflict, invalid, not_found
from umami_api.models import (
    Claim,
    ClaimEvidence,
    ClaimReview,
    EvidenceSource,
    Measurement,
)
from umami_api.policy import Subject
from umami_api.schemas import (
    ClaimDetailOut,
    ClaimIn,
    ClaimOut,
    ClaimStatus,
    EvidenceIn,
    EvidenceOut,
    ReviewIn,
    ReviewOut,
    SourceIn,
    SourceOut,
)
from umami_api.security import AccessDep, WorkspaceAccess
from umami_api.v1.projects import get_project

router = APIRouter(tags=["evidence"])

TRANSITIONS = {
    ("under_review", "accept"): "accepted",
    ("under_review", "reject"): "rejected",
    ("under_review", "request_changes"): "draft",
    ("accepted", "retract"): "retracted",
}


def _source(access: WorkspaceAccess, source_id: uuid.UUID) -> EvidenceSource:
    source = access.session.scalar(select(EvidenceSource).where(
        EvidenceSource.id == source_id, EvidenceSource.workspace_id == access.workspace.id))
    if source is None:
        raise not_found("evidence source")
    return source


def _claim(access: WorkspaceAccess, claim_id: uuid.UUID, lock: bool = False) -> Claim:
    query = select(Claim).where(Claim.id == claim_id, Claim.workspace_id == access.workspace.id)
    claim = access.session.scalar(query.with_for_update() if lock else query)
    if claim is None:
        raise not_found("claim")
    return claim


@router.get("/workspaces/{workspace_id}/sources", response_model=list[SourceOut],
            operation_id="list_sources")
def list_sources(access: AccessDep):
    return access.session.scalars(select(EvidenceSource).where(
        EvidenceSource.workspace_id == access.workspace.id)
        .order_by(EvidenceSource.created_at.desc())).all()


@router.post("/workspaces/{workspace_id}/sources", response_model=SourceOut, status_code=201,
             operation_id="add_source")
def add_source(body: SourceIn, access: AccessDep):
    authorize(access, "evidence.add")
    source = EvidenceSource(workspace_id=access.workspace.id, added_by=access.principal.id,
                            added_by_kind=access.principal.kind, **body.model_dump())
    access.session.add(source)
    try:
        access.session.flush()
    except IntegrityError as error:
        raise conflict("A source with this identifier already exists.") from error
    return source


@router.post("/workspaces/{workspace_id}/sources/{source_id}/verify", response_model=SourceOut,
             operation_id="verify_source")
def verify_source(source_id: uuid.UUID, access: AccessDep):
    """A human reviewer confirms the source exists and says what is cited."""
    source = _source(access, source_id)
    authorize(access, "claim.review", Subject(author_id=source.added_by), ("source", source.id))
    if source.verified_at is None:
        source.verified_by, source.verified_at = access.principal.id, utcnow()
    return source


@router.get("/workspaces/{workspace_id}/claims", response_model=list[ClaimOut],
            operation_id="list_claims")
def list_claims(access: AccessDep, status: ClaimStatus | None = None,
                project_id: uuid.UUID | None = None):
    query = select(Claim).where(Claim.workspace_id == access.workspace.id)
    if status:
        query = query.where(Claim.status == status)
    if project_id:
        query = query.where(Claim.project_id == project_id)
    return access.session.scalars(query.order_by(Claim.updated_at.desc())).all()


@router.post("/workspaces/{workspace_id}/claims", response_model=ClaimOut, status_code=201,
             operation_id="propose_claim")
def propose_claim(body: ClaimIn, access: AccessDep):
    if body.project_id is not None:
        get_project(access, body.project_id)
    authorize(access, "claim.propose", Subject(project_id=body.project_id))
    claim = Claim(workspace_id=access.workspace.id, author_id=access.principal.id,
                  author_kind=access.principal.kind, **body.model_dump())
    access.session.add(claim)
    access.session.flush()
    return claim


@router.get("/workspaces/{workspace_id}/claims/{claim_id}", response_model=ClaimDetailOut,
            operation_id="get_claim")
def get_claim(claim_id: uuid.UUID, access: AccessDep):
    claim = _claim(access, claim_id)
    evidence = access.session.scalars(select(ClaimEvidence).where(
        ClaimEvidence.claim_id == claim.id).order_by(ClaimEvidence.created_at)).all()
    reviews = access.session.scalars(select(ClaimReview).where(
        ClaimReview.claim_id == claim.id).order_by(ClaimReview.created_at)).all()
    return ClaimDetailOut(**ClaimOut.model_validate(claim).model_dump(),
                          evidence=[EvidenceOut.model_validate(e) for e in evidence],
                          reviews=[ReviewOut.model_validate(r) for r in reviews])


@router.post("/workspaces/{workspace_id}/claims/{claim_id}/evidence", response_model=EvidenceOut,
             status_code=201, operation_id="link_evidence")
def link_evidence(claim_id: uuid.UUID, body: EvidenceIn, access: AccessDep):
    claim = _claim(access, claim_id, lock=True)
    authorize(access, "evidence.add", Subject(project_id=claim.project_id), ("claim", claim.id))
    if claim.status not in ("draft", "under_review"):
        raise conflict("Evidence can only be added to draft or under-review claims.")
    if (body.source_id is None) == (body.measurement_id is None):
        raise invalid("Link exactly one source or one measurement.")
    if body.source_id is not None:
        _source(access, body.source_id)
    else:
        measurement = access.session.get(Measurement, body.measurement_id)
        if measurement is None or measurement.workspace_id != access.workspace.id:
            raise not_found("measurement")
    link = ClaimEvidence(claim_id=claim.id, added_by=access.principal.id, **body.model_dump())
    access.session.add(link)
    claim.updated_at = utcnow()
    access.session.flush()
    return link


@router.post("/workspaces/{workspace_id}/claims/{claim_id}/submit", response_model=ClaimOut,
             operation_id="submit_claim")
def submit_claim(claim_id: uuid.UUID, access: AccessDep):
    claim = _claim(access, claim_id, lock=True)
    authorize(access, "claim.propose", Subject(project_id=claim.project_id), ("claim", claim.id))
    if claim.status != "draft":
        raise conflict("Only draft claims can be submitted for review.")
    if not access.session.scalar(select(ClaimEvidence.id).where(
            ClaimEvidence.claim_id == claim.id).limit(1)):
        raise conflict("Link at least one piece of evidence before review.")
    claim.status, claim.updated_at = "under_review", utcnow()
    return claim


def has_qualifying_support(access: WorkspaceAccess, claim: Claim) -> bool:
    links = access.session.scalars(select(ClaimEvidence).where(
        ClaimEvidence.claim_id == claim.id, ClaimEvidence.stance == "supports")).all()
    for link in links:
        if link.source_id is not None:
            if access.session.get(EvidenceSource, link.source_id).verified_at is not None:
                return True
        elif access.session.get(Measurement, link.measurement_id).origin == "PHYSICAL":
            return True
    return False


@router.post("/workspaces/{workspace_id}/claims/{claim_id}/reviews", response_model=ReviewOut,
             status_code=201, operation_id="review_claim")
def review_claim(claim_id: uuid.UUID, body: ReviewIn, access: AccessDep):
    claim = _claim(access, claim_id, lock=True)
    authorize(access, "claim.review", Subject(project_id=claim.project_id,
                                              author_id=claim.author_id), ("claim", claim.id))
    target = TRANSITIONS.get((claim.status, body.decision))
    if target is None:
        raise conflict("This decision is not valid for the claim's current status.")
    if target == "accepted" and not has_qualifying_support(access, claim):
        raise conflict("Acceptance needs supporting evidence from a verified source "
                       "or a PHYSICAL measurement.")
    review = ClaimReview(claim_id=claim.id, reviewer_id=access.principal.id,
                         decision=body.decision, rationale=body.rationale,
                         from_status=claim.status, to_status=target)
    claim.status, claim.updated_at = target, utcnow()
    access.session.add(review)
    access.session.flush()
    return review
