"""Deny-by-default authorization policy (UA-007).

Decisions are made by this trusted code from structured facts (principal kind,
membership role, research contract, resource ownership). Model output, free text
and request bodies never grant authority.

Evaluation order:
1. Hard invariants (cannot be overridden by any role or contract).
2. Role grants for the caller's membership.
3. For agents: an active, unexpired research contract that lists the action
   (and, if project-restricted, the project).
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime

# Every action the platform authorizes. Unknown actions are denied.
ACTIONS = frozenset({
    "workspace.read", "workspace.manage_members", "audit.read", "contract.manage",
    "project.create", "project.update",
    "evidence.add", "claim.propose", "claim.review",
    "assay.define", "measurement.record_simulated", "measurement.record_physical",
    "budget.manage", "quote.record", "spend.reserve", "spend.approve",
    "experiment.draft", "experiment.submit_simulated", "experiment.approve_physical",
    "experiment.submit_physical", "job.manage", "agent.run",
})

READ_ONLY = frozenset({"workspace.read"})
_SCIENCE = {"project.create", "project.update", "evidence.add", "claim.propose",
            "assay.define", "measurement.record_simulated", "measurement.record_physical",
            "experiment.draft", "experiment.submit_simulated", "quote.record",
            "spend.reserve", "agent.run"}

ROLE_GRANTS: dict[str, frozenset[str]] = {
    "owner": ACTIONS,
    "admin": ACTIONS - {"spend.approve"},
    "scientist": frozenset(READ_ONLY | _SCIENCE | {"job.manage"}),
    "reviewer": frozenset(READ_ONLY | {"claim.review", "audit.read", "experiment.approve_physical",
                                       "evidence.add"}),
    "viewer": READ_ONLY,
    # Agents may only ever be granted these, and only through a research contract.
    "agent": frozenset(READ_ONLY | {"evidence.add", "claim.propose",
                                    "measurement.record_simulated", "experiment.draft",
                                    "experiment.submit_simulated", "quote.record",
                                    "agent.run"}),
}

# Actions that are never available to an agent principal, whatever a contract says.
AGENT_FORBIDDEN = frozenset({
    "workspace.manage_members", "contract.manage", "claim.review", "budget.manage",
    "spend.reserve", "spend.approve", "experiment.approve_physical", "experiment.submit_physical",
    "measurement.record_physical", "job.manage", "audit.read", "project.create",
    "project.update", "assay.define",
})

# Approval actions require that the approver did not author the subject.
SEPARATION_OF_DUTIES = frozenset({"claim.review", "spend.approve", "experiment.approve_physical"})


@dataclass(frozen=True)
class Contract:
    actions: frozenset[str]
    project_ids: frozenset[uuid.UUID] | None
    expires_at: datetime
    revoked: bool


@dataclass(frozen=True)
class Subject:
    """Facts about the resource being acted on."""
    project_id: uuid.UUID | None = None
    author_id: uuid.UUID | None = None


@dataclass(frozen=True)
class Context:
    principal_id: uuid.UUID
    principal_kind: str
    role: str
    now: datetime
    live_submission_enabled: bool = False
    contracts: tuple[Contract, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str

    def __bool__(self) -> bool:
        return self.allowed


def decide(context: Context, action: str, subject: Subject | None = None) -> Decision:
    subject = subject or Subject()
    if action not in ACTIONS:
        return Decision(False, "unknown_action")
    is_agent = context.principal_kind == "agent"
    if is_agent != (context.role == "agent"):
        return Decision(False, "kind_role_mismatch")
    if action == "experiment.submit_physical" and not context.live_submission_enabled:
        return Decision(False, "live_submission_disabled")
    if is_agent and action in AGENT_FORBIDDEN:
        return Decision(False, "agents_cannot_" + action.replace(".", "_"))
    if action in SEPARATION_OF_DUTIES and subject.author_id == context.principal_id:
        return Decision(False, "separation_of_duties")
    if action not in ROLE_GRANTS.get(context.role, frozenset()):
        return Decision(False, "role_not_permitted")
    if not is_agent or action in READ_ONLY:
        return Decision(True, "role_grant")
    for contract in context.contracts:
        if contract.revoked or contract.expires_at <= context.now:
            continue
        if action not in contract.actions:
            continue
        if contract.project_ids is not None and subject.project_id not in contract.project_ids:
            continue
        return Decision(True, "research_contract")
    return Decision(False, "no_active_research_contract")
