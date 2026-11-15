import uuid
from datetime import UTC, datetime, timedelta

import pytest

from umami_api.policy import (
    ACTIONS,
    AGENT_FORBIDDEN,
    ROLE_GRANTS,
    Context,
    Contract,
    Subject,
    decide,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
ME = uuid.uuid4()
PROJECT = uuid.uuid4()


def ctx(role="scientist", kind=None, contracts=(), live=False):
    return Context(principal_id=ME, principal_kind=kind or ("agent" if role == "agent" else "human"),
                   role=role, now=NOW, live_submission_enabled=live, contracts=tuple(contracts))


def contract(actions, projects=None, expires=NOW + timedelta(days=1), revoked=False):
    return Contract(actions=frozenset(actions), project_ids=projects, expires_at=expires,
                    revoked=revoked)


def test_unknown_actions_and_kind_role_mismatches_are_denied():
    assert decide(ctx("owner"), "lab.launch_anything").reason == "unknown_action"
    assert not decide(ctx("owner", kind="agent"), "workspace.read")
    assert not decide(ctx("agent", kind="human"), "workspace.read")


@pytest.mark.parametrize("role", list(ROLE_GRANTS))
def test_physical_submission_is_denied_to_everyone_while_live_submission_is_disabled(role):
    decision = decide(ctx(role), "experiment.submit_physical")
    assert not decision and decision.reason == "live_submission_disabled"


@pytest.mark.parametrize("action", sorted(AGENT_FORBIDDEN))
def test_agents_can_never_perform_forbidden_actions_even_with_a_contract(action):
    assert not decide(ctx("agent", contracts=[contract(ACTIONS)]), action)


def test_agents_need_an_active_matching_contract():
    assert decide(ctx("agent"), "workspace.read")
    assert decide(ctx("agent"), "claim.propose").reason == "no_active_research_contract"
    good = contract({"claim.propose"})
    assert decide(ctx("agent", contracts=[good]), "claim.propose").reason == "research_contract"
    assert not decide(ctx("agent", contracts=[good]), "evidence.add")
    assert not decide(ctx("agent", contracts=[contract({"claim.propose"}, revoked=True)]),
                      "claim.propose")
    assert not decide(ctx("agent", contracts=[contract({"claim.propose"}, expires=NOW)]),
                      "claim.propose")


def test_project_restricted_contracts_only_cover_listed_projects():
    scoped = contract({"experiment.draft"}, projects=frozenset({PROJECT}))
    assert decide(ctx("agent", contracts=[scoped]), "experiment.draft", Subject(project_id=PROJECT))
    assert not decide(ctx("agent", contracts=[scoped]), "experiment.draft",
                      Subject(project_id=uuid.uuid4()))
    assert not decide(ctx("agent", contracts=[scoped]), "experiment.draft")


@pytest.mark.parametrize("action", ["claim.review", "experiment.approve_physical"])
def test_separation_of_duties_blocks_self_approval(action):
    assert decide(ctx("owner"), action, Subject(author_id=uuid.uuid4()))
    decision = decide(ctx("owner"), action, Subject(author_id=ME))
    assert not decision and decision.reason == "separation_of_duties"


def test_role_matrix_highlights():
    assert not decide(ctx("viewer"), "claim.propose")
    assert decide(ctx("reviewer"), "claim.review", Subject(author_id=uuid.uuid4()))
    assert not decide(ctx("reviewer"), "project.create")
    assert not decide(ctx("scientist"), "claim.review", Subject(author_id=uuid.uuid4()))
    assert not decide(ctx("admin"), "spend.approve", Subject(author_id=uuid.uuid4()))
    assert decide(ctx("owner"), "spend.approve", Subject(author_id=uuid.uuid4()))
    assert ROLE_GRANTS["agent"].isdisjoint(AGENT_FORBIDDEN)
