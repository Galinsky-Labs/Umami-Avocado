"""Glue between HTTP requests, the pure policy engine and the append-only audit log."""
import uuid

from sqlalchemy import select

from umami_api.db import utcnow
from umami_api.errors import ApiError
from umami_api.models import AuditEvent, ResearchContract
from umami_api.policy import READ_ONLY, Context, Contract, Decision, Subject, decide
from umami_api.security import WorkspaceAccess


def policy_context(access: WorkspaceAccess) -> Context:
    contracts: tuple[Contract, ...] = ()
    if access.principal.kind == "agent":
        rows = access.session.scalars(select(ResearchContract).where(
            ResearchContract.workspace_id == access.workspace.id,
            ResearchContract.agent_id == access.principal.id,
            ResearchContract.revoked_at.is_(None),
        )).all()
        contracts = tuple(
            Contract(actions=frozenset(row.actions),
                     project_ids=None if row.project_ids is None
                     else frozenset(uuid.UUID(p) for p in row.project_ids),
                     expires_at=row.expires_at, revoked=row.revoked_at is not None)
            for row in rows
        )
    return Context(principal_id=access.principal.id, principal_kind=access.principal.kind,
                   role=access.role, now=utcnow(),
                   live_submission_enabled=access.caller.settings.lab_live_submission_enabled,
                   contracts=contracts)


def _event(access: WorkspaceAccess, action: str, decision: Decision,
           resource: tuple[str, object] | None) -> AuditEvent:
    return AuditEvent(
        workspace_id=access.workspace.id, actor_id=access.principal.id,
        actor_kind=access.principal.kind, action=action,
        resource_type=resource[0] if resource else None,
        resource_id=str(resource[1]) if resource and resource[1] is not None else None,
        decision="allow" if decision.allowed else "deny", reason=decision.reason,
    )


def check(access: WorkspaceAccess, action: str, subject: Subject | None = None) -> Decision:
    return decide(policy_context(access), action, subject)


def authorize(access: WorkspaceAccess, action: str, subject: Subject | None = None,
              resource: tuple[str, object] | None = None) -> None:
    """Allow or raise 403 policy_denied. Mutating allows and every denial are audited.

    Denials are written in an independent transaction so the rollback of the
    failed request cannot erase them."""
    decision = check(access, action, subject)
    if decision.allowed:
        if action not in READ_ONLY:
            access.session.add(_event(access, action, decision, resource))
        return
    with access.caller.database.session() as audit:
        audit.add(_event(access, action, decision, resource))
    raise ApiError(403, "policy_denied", f"Denied by policy: {decision.reason}.")


def record(access: WorkspaceAccess, action: str, resource: tuple[str, object]) -> None:
    """Audit a state change that follows an earlier authorization (e.g. ids known later)."""
    access.session.add(_event(access, action, Decision(True, "recorded"), resource))
