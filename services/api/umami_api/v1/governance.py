"""Research contracts for agents, policy explanation and the audit log (UA-007)."""
import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from umami_api.authz import authorize, check, record
from umami_api.db import utcnow
from umami_api.errors import invalid, not_found
from umami_api.models import AuditEvent, Membership, Principal, Project, ResearchContract
from umami_api.policy import ACTIONS
from umami_api.schemas import (
    AuditEventOut,
    PolicyDecisionOut,
    ResearchContractIn,
    ResearchContractOut,
)
from umami_api.security import AccessDep

router = APIRouter(tags=["governance"])


@router.get("/workspaces/{workspace_id}/policy/decisions", response_model=list[PolicyDecisionOut],
            operation_id="explain_policy")
def explain(access: AccessDep):
    """What the caller may do here, as evaluated by the policy engine (no side effects)."""
    return [PolicyDecisionOut(action=action, allowed=d.allowed, reason=d.reason)
            for action in sorted(ACTIONS) for d in [check(access, action)]]


@router.get("/workspaces/{workspace_id}/research-contracts",
            response_model=list[ResearchContractOut], operation_id="list_research_contracts")
def list_contracts(access: AccessDep):
    query = select(ResearchContract).where(ResearchContract.workspace_id == access.workspace.id)
    if access.principal.kind == "agent":
        query = query.where(ResearchContract.agent_id == access.principal.id)
    return access.session.scalars(query.order_by(ResearchContract.created_at.desc())).all()


@router.post("/workspaces/{workspace_id}/research-contracts", response_model=ResearchContractOut,
             status_code=201, operation_id="grant_research_contract")
def grant_contract(body: ResearchContractIn, access: AccessDep):
    authorize(access, "contract.manage")
    agent = access.session.execute(
        select(Principal).join(Membership, Membership.principal_id == Principal.id).where(
            Membership.workspace_id == access.workspace.id, Principal.id == body.agent_id,
            Principal.kind == "agent")
    ).scalar_one_or_none()
    if agent is None:
        raise invalid("Research contracts can only be granted to agent members of this workspace.")
    project_ids = None
    if body.project_ids is not None:
        found = set(access.session.scalars(select(Project.id).where(
            Project.workspace_id == access.workspace.id, Project.id.in_(body.project_ids))))
        if found != set(body.project_ids):
            raise invalid("Every project must belong to this workspace.")
        project_ids = sorted(str(p) for p in found)
    contract = ResearchContract(
        workspace_id=access.workspace.id, agent_id=agent.id, granted_by=access.principal.id,
        purpose=body.purpose, actions=sorted(set(body.actions)), project_ids=project_ids,
        expires_at=utcnow() + timedelta(days=body.ttl_days),
    )
    access.session.add(contract)
    access.session.flush()
    record(access, "contract.grant", ("research_contract", contract.id))
    return contract


@router.delete("/workspaces/{workspace_id}/research-contracts/{contract_id}",
               response_model=ResearchContractOut, operation_id="revoke_research_contract")
def revoke_contract(contract_id: uuid.UUID, access: AccessDep):
    authorize(access, "contract.manage", resource=("research_contract", contract_id))
    contract = access.session.scalar(select(ResearchContract).where(
        ResearchContract.id == contract_id, ResearchContract.workspace_id == access.workspace.id))
    if contract is None:
        raise not_found("research contract")
    if contract.revoked_at is None:
        contract.revoked_at = utcnow()
        contract.revoked_by = access.principal.id
    return contract


@router.get("/workspaces/{workspace_id}/audit", response_model=list[AuditEventOut],
            operation_id="list_audit_events")
def audit(access: AccessDep, limit: Annotated[int, Query(ge=1, le=500)] = 100):
    authorize(access, "audit.read")
    return access.session.scalars(
        select(AuditEvent).where(AuditEvent.workspace_id == access.workspace.id)
        .order_by(AuditEvent.occurred_at.desc()).limit(limit)
    ).all()
