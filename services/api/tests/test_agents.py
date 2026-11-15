from types import SimpleNamespace

import pytest

from umami_api.agents import providers
from umami_api.agents.providers import (
    SIMULATED_LABEL,
    ClaudePlanner,
    Evidence,
    PlanDraft,
    PlanningContext,
    PriorRun,
    ProviderError,
    SimulatedPlanner,
)
from umami_api.orchestration import run_one
from umami_api.v1 import agents as agents_router

CONTEXT = PlanningContext(project_name="M1", program="M1", objective="biomass",
                          evidence=(Evidence("source:abc", "source", "Yeast review"),))


def test_simulated_planner_is_deterministic_labelled_and_explores():
    first = SimulatedPlanner().plan(CONTEXT)
    assert first == SimulatedPlanner().plan(CONTEXT)
    assert (first.temperature_c, first.ph) == (30.0, 5.0)
    assert first.rationale.startswith(SIMULATED_LABEL)
    after = SimulatedPlanner().plan(PlanningContext(**{**CONTEXT.__dict__, "prior_runs": (
        PriorRun(30.0, 5.0, 20.0, 9.0), PriorRun(27.0, 5.0, 20.0, 9.5))}))
    assert (after.temperature_c, after.ph) not in {(30.0, 5.0), (27.0, 5.0)}
    assert abs(after.temperature_c - 27.0) <= 3


def test_provider_selection(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert providers.get_provider().name == "simulated"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_PROVIDER", "simulated")
    assert providers.get_provider().name == "simulated"


class FakeMessages:
    def __init__(self, response):
        self.response, self.calls = response, []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def fake_client(response):
    return SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(response)))


def test_claude_planner_uses_structured_output_and_handles_refusal():
    draft = SimulatedPlanner().plan(CONTEXT)
    client = fake_client(SimpleNamespace(stop_reason="end_turn", parsed_output=draft))
    assert ClaudePlanner(client).plan(CONTEXT) == draft
    call = client.beta.messages.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["output_format"] is PlanDraft
    assert call["fallbacks"] == "default"
    assert "source:abc" in call["messages"][0]["content"]
    refused = fake_client(SimpleNamespace(stop_reason="refusal", parsed_output=None))
    with pytest.raises(ProviderError):
        ClaudePlanner(refused).plan(CONTEXT)
    truncated = fake_client(SimpleNamespace(stop_reason="max_tokens", parsed_output=None))
    with pytest.raises(ProviderError):
        ClaudePlanner(truncated).plan(CONTEXT)


@pytest.fixture
def lab(client, owner, make_member):
    headers, workspace_id, _ = owner
    base = f"/api/v1/workspaces/{workspace_id}"
    project = client.post(f"{base}/projects", headers=headers, json={
        "name": "M1", "slug": "m1", "program": "M1", "objective": "Maximise biomass"}).json()
    agent, agent_id = make_member("agent", kind="agent")
    client.post(f"{base}/research-contracts", headers=headers, json={
        "agent_id": agent_id, "purpose": "planning", "ttl_days": 1, "project_ids": [project["id"]],
        "actions": ["agent.run", "experiment.draft", "experiment.submit_simulated"]})
    return {"base": base, "owner": headers, "agent": agent, "project": project["id"]}


def test_agent_plans_from_evidence_and_the_loop_closes(client, lab, database, monkeypatch):
    monkeypatch.setattr(agents_router, "PROVIDER_FACTORY", SimulatedPlanner)
    url = f"{lab['base']}/projects/{lab['project']}/agent/plan"
    empty = client.post(url, headers=lab["agent"]).json()
    assert empty["outcome"] == "rejected" and "No evidence" in empty["errors"][0]
    client.post(f"{lab['base']}/sources", headers=lab["owner"], json={
        "kind": "doi", "identifier": "10.1/yeast", "citation": "Yeast growth review"})
    trace = client.post(url, headers=lab["agent"]).json()
    assert trace["outcome"] == "proposal_created", trace
    assert trace["provider"] == "simulated" and len(trace["input_sha256"]) == 64
    proposal = client.get(f"{lab['base']}/projects/{lab['project']}/proposals/"
                          f"{trace['proposal_id']}", headers=lab["owner"]).json()
    assert proposal["state"] == "ready" and proposal["target_origin"] == "SIMULATED"
    assert proposal["rationale"].startswith("[simulated/")
    executed = client.post(f"{lab['base']}/projects/{lab['project']}/proposals/"
                           f"{proposal['id']}/execute", headers=lab["agent"])
    assert executed.status_code == 200
    assert run_one(database) == "succeeded"
    second = client.post(url, headers=lab["agent"]).json()
    assert second["input"]["prior_simulated_runs"]  # learned from the completed run
    assert second["output"]["title"] != trace["output"]["title"]
    assert len(client.get(f"{lab['base']}/projects/{lab['project']}/agent/traces",
                          headers=lab["owner"]).json()) == 3


def test_hallucinated_citations_and_provider_errors_are_recorded_not_trusted(client, lab,
                                                                          monkeypatch):
    client.post(f"{lab['base']}/sources", headers=lab["owner"], json={
        "kind": "doi", "identifier": "10.1/yeast", "citation": "Yeast growth review"})

    class Inventing:
        name, model = "fake", "fake-1"

        def plan(self, context):
            return SimulatedPlanner().plan(context).model_copy(
                update={"cited_evidence_ids": ["source:00000000-0000-0000-0000-000000000000"]})

    class Failing:
        name, model = "fake", "fake-1"

        def plan(self, context):
            raise ProviderError("The model declined to produce a plan.")

    url = f"{lab['base']}/projects/{lab['project']}/agent/plan"
    monkeypatch.setattr(agents_router, "PROVIDER_FACTORY", Inventing)
    rejected = client.post(url, headers=lab["owner"]).json()
    assert rejected["outcome"] == "rejected" and rejected["proposal_id"] is None
    monkeypatch.setattr(agents_router, "PROVIDER_FACTORY", Failing)
    failed = client.post(url, headers=lab["owner"]).json()
    assert failed["outcome"] == "provider_error"
    assert client.get(f"{lab['base']}/projects/{lab['project']}/proposals",
                      headers=lab["owner"]).json() == []


def test_agents_without_contract_cannot_plan(client, lab, make_member):
    stranger, _ = make_member("agent", kind="agent")
    url = f"{lab['base']}/projects/{lab['project']}/agent/plan"
    assert client.post(url, headers=stranger).status_code == 403


def test_workspace_trace_queue_filters_by_outcome(client, lab, monkeypatch):
    monkeypatch.setattr(agents_router, "PROVIDER_FACTORY", SimulatedPlanner)
    client.post(f"{lab['base']}/projects/{lab['project']}/agent/plan", headers=lab["owner"])
    url = f"{lab['base']}/agent/traces"
    assert len(client.get(url, headers=lab["owner"]).json()) == 1
    assert client.get(url, headers=lab["owner"], params={"outcome": "proposal_created"}).json() == []
