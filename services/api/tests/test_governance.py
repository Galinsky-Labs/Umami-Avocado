import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


@pytest.fixture
def agent_setup(client, owner, make_member):
    headers, workspace_id, _ = owner
    agent_headers, agent_id = make_member("agent", kind="agent")
    project = client.post(f"/api/v1/workspaces/{workspace_id}/projects", headers=headers,
                          json={"name": "M1", "slug": "m1", "program": "M1"}).json()
    return headers, workspace_id, agent_headers, agent_id, project


def test_agent_capabilities_come_only_from_contracts(client, agent_setup):
    headers, workspace_id, agent_headers, agent_id, project = agent_setup
    base = f"/api/v1/workspaces/{workspace_id}"
    before = {d["action"]: d for d in client.get(f"{base}/policy/decisions",
                                                 headers=agent_headers).json()}
    assert before["claim.propose"]["allowed"] is False
    assert before["claim.propose"]["reason"] == "no_active_research_contract"
    granted = client.post(f"{base}/research-contracts", headers=headers, json={
        "agent_id": agent_id, "purpose": "Literature triage for M1", "ttl_days": 7,
        "actions": ["claim.propose", "evidence.add"], "project_ids": [project["id"]]})
    assert granted.status_code == 201, granted.text
    contract = granted.json()
    assert contract["project_ids"] == [project["id"]]
    after = {d["action"]: d for d in client.get(f"{base}/policy/decisions",
                                                headers=agent_headers).json()}
    # Project-scoped contract: an unscoped check still denies.
    assert after["claim.propose"]["allowed"] is False
    assert after["experiment.submit_physical"]["reason"] == "live_submission_disabled"
    revoked = client.delete(f"{base}/research-contracts/{contract['id']}", headers=headers)
    assert revoked.json()["revoked_at"] is not None
    assert len(client.get(f"{base}/research-contracts", headers=agent_headers).json()) == 1


def test_contracts_cannot_grant_forbidden_actions_or_target_humans(client, agent_setup,
                                                                   make_member):
    headers, workspace_id, agent_headers, agent_id, _ = agent_setup
    url = f"/api/v1/workspaces/{workspace_id}/research-contracts"
    forbidden = client.post(url, headers=headers, json={
        "agent_id": agent_id, "purpose": "x", "ttl_days": 1, "actions": ["spend.approve"]})
    assert forbidden.status_code == 400
    _, human_id = make_member("scientist")
    human = client.post(url, headers=headers, json={
        "agent_id": human_id, "purpose": "x", "ttl_days": 1, "actions": ["claim.propose"]})
    assert human.status_code == 400
    self_grant = client.post(url, headers=agent_headers, json={
        "agent_id": agent_id, "purpose": "x", "ttl_days": 1, "actions": ["claim.propose"]})
    assert self_grant.status_code == 403
    assert self_grant.json()["error"]["code"] == "policy_denied"


def test_denials_are_audited_and_audit_is_append_only(client, agent_setup, database):
    headers, workspace_id, agent_headers, agent_id, _ = agent_setup
    base = f"/api/v1/workspaces/{workspace_id}"
    assert client.post(f"{base}/projects", headers=agent_headers,
                       json={"name": "x", "slug": "xx", "program": "M1"}).status_code == 403
    assert client.get(f"{base}/audit", headers=agent_headers).status_code == 403
    events = client.get(f"{base}/audit", headers=headers).json()
    denials = [e for e in events if e["decision"] == "deny"]
    assert {e["action"] for e in denials} >= {"project.create", "audit.read"}
    assert all(e["actor_id"] == agent_id for e in denials)
    assert any(e["action"] == "project.create" and e["decision"] == "allow" for e in events)
    with pytest.raises(DBAPIError), database.engine.begin() as connection:
        connection.execute(text("UPDATE audit_events SET decision = 'allow'"))
    with pytest.raises(DBAPIError), database.engine.begin() as connection:
        connection.execute(text("DELETE FROM audit_events"))
