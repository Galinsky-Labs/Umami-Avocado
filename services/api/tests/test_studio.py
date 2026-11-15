import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from umami_api.orchestration import run_one
from umami_api.science.preflight import run_preflight

CONTENT = {"organism": "Saccharomyces cerevisiae", "medium": "YPD, 20 g/L glucose",
           "temperature_c": 30, "ph": 5, "initial_glucose_g_l": 20, "duration_h": 12,
           "sample_interval_h": 4, "biological_replicates": 3, "technical_replicates": 1,
           "assay_keys": ["sim-dcw"], "steps": ["Inoculate", "Incubate shaking", "Sample"]}


@pytest.fixture
def studio(client, owner, make_member):
    headers, workspace_id, _ = owner
    base = f"/api/v1/workspaces/{workspace_id}"
    project = client.post(f"{base}/projects", headers=headers,
                          json={"name": "M1", "slug": "m1", "program": "M1"}).json()
    source = client.post(f"{base}/sources", headers=headers, json={
        "kind": "doi", "identifier": "10.1/yeast", "citation": "Yeast growth review"}).json()
    agent, agent_id = make_member("agent", kind="agent")
    client.post(f"{base}/research-contracts", headers=headers, json={
        "agent_id": agent_id, "purpose": "design", "ttl_days": 1, "project_ids": [project["id"]],
        "actions": ["experiment.draft", "experiment.submit_simulated"]})
    return {"base": base, "owner": headers, "agent": agent, "project": project["id"],
            "source": source["id"]}


def protocol(client, s, content=None, who="owner"):
    response = client.post(f"{s['base']}/protocols", headers=s[who], json={
        "key": "batch-growth", "title": "Batch growth", "content": content or CONTENT})
    assert response.status_code == 201, response.text
    return response.json()


def proposal(client, s, protocol_id, who="owner", **extra):
    body = {"protocol_version_id": protocol_id, "title": "Temperature probe",
            "hypothesis": "Growth at 30 C exhausts glucose within 12 h.",
            "evidence_source_ids": [s["source"]], **extra}
    response = client.post(f"{s['base']}/projects/{s['project']}/proposals", headers=s[who],
                           json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_protocols_are_versioned_immutable_and_scope_limited(client, studio, database):
    v1 = protocol(client, studio)
    v2 = protocol(client, studio, {**CONTENT, "temperature_c": 25})
    assert (v1["version"], v2["version"]) == (1, 2)
    bad = client.post(f"{studio['base']}/protocols", headers=studio["owner"], json={
        "key": "x1", "title": "x", "content": {**CONTENT, "organism": "Escherichia coli"}})
    assert bad.status_code == 400
    with pytest.raises(DBAPIError), database.engine.begin() as connection:
        connection.execute(text("UPDATE protocol_versions SET title = 'edited'"))


def test_agent_designed_simulated_proposal_runs_end_to_end(client, studio, database):
    s = studio
    # Protocol authoring is workspace-level; the project-scoped contract cannot cover it.
    assert client.post(f"{s['base']}/protocols", headers=s["agent"], json={
        "key": "agent-proto", "title": "x", "content": CONTENT}).status_code == 403
    p = proposal(client, s, protocol(client, s)["id"], who="agent")
    url = f"{s['base']}/projects/{s['project']}/proposals/{p['id']}"
    assert client.post(f"{url}/execute", headers=s["agent"]).status_code == 409
    checked = client.post(f"{url}/preflight", headers=s["agent"]).json()
    assert checked["state"] == "ready", checked["preflight"]
    executing = client.post(f"{url}/execute", headers=s["agent"]).json()
    assert executing["state"] == "executing" and executing["run_id"]
    assert run_one(database) == "succeeded"
    assert client.get(url, headers=s["owner"]).json()["state"] == "executed"


def test_preflight_blockers(client, studio):
    s = studio
    risky = protocol(client, s, {**CONTENT, "steps": ["Introduce a toxin gene"],
                                 "assay_keys": ["missing-assay"], "biological_replicates": 1})
    p = proposal(client, s, risky["id"], evidence_source_ids=[], evidence_claim_ids=[])
    url = f"{s['base']}/projects/{s['project']}/proposals/{p['id']}"
    result = client.post(f"{url}/preflight", headers=s["owner"]).json()
    assert result["state"] == "preflight_failed"
    failed = {c["key"] for c in result["preflight"]["checks"] if not c["passed"]}
    assert failed == {"evidence_linked", "assays_defined", "scope_screen", "replication"}


def test_physical_proposals_can_never_execute(client, studio):
    s = studio
    p = proposal(client, s, protocol(client, s)["id"], target_origin="PHYSICAL")
    url = f"{s['base']}/projects/{s['project']}/proposals/{p['id']}"
    result = client.post(f"{url}/preflight", headers=s["owner"]).json()
    assert result["state"] == "preflight_failed"
    blocker = next(c for c in result["preflight"]["checks"]
                   if c["key"] == "physical_execution_available")
    assert blocker["passed"] is False
    denied = client.post(f"{url}/execute", headers=s["owner"])
    assert denied.status_code == 403
    assert "live_submission_disabled" in denied.json()["error"]["message"]


def test_pure_preflight_physical_gate():
    result = run_preflight(content=CONTENT, target_origin="PHYSICAL", evidence_ok=True,
                           missing_assays=[], live_submission_enabled=False)
    assert result["passed"] is False
