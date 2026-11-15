import pytest


@pytest.fixture
def world(client, owner, make_member):
    headers, workspace_id, _ = owner
    base = f"/api/v1/workspaces/{workspace_id}"
    reviewer, _ = make_member("reviewer")
    scientist, _ = make_member("scientist")
    agent, agent_id = make_member("agent", kind="agent")
    client.post(f"{base}/research-contracts", headers=headers, json={
        "agent_id": agent_id, "purpose": "literature", "ttl_days": 5,
        "actions": ["claim.propose", "evidence.add", "measurement.record_simulated"]})
    return {"base": base, "owner": headers, "reviewer": reviewer, "scientist": scientist,
            "agent": agent}


def source(client, w, who="agent", identifier="10.1000/example.1"):
    response = client.post(f"{w['base']}/sources", headers=w[who], json={
        "kind": "doi", "identifier": identifier,
        "citation": "Example et al. (2020) Yeast extract flavour. J. Example 1:1"})
    assert response.status_code == 201, response.text
    return response.json()


def claim(client, w, who="agent"):
    response = client.post(f"{w['base']}/claims", headers=w[who], json={
        "statement": "Autolysis at 50 C increases free glutamate in yeast extract.",
        "scope_conditions": "S. cerevisiae, 24 h autolysis"})
    assert response.status_code == 201, response.text
    return response.json()


def test_agent_proposed_claim_needs_verified_evidence_and_a_human_reviewer(client, world):
    w = world
    src = source(client, w)
    assert src["added_by_kind"] == "agent" and src["verified_at"] is None
    c = claim(client, w)
    url = f"{w['base']}/claims/{c['id']}"
    assert client.post(f"{url}/submit", headers=w["agent"]).status_code == 409  # no evidence
    linked = client.post(f"{url}/evidence", headers=w["agent"],
                         json={"source_id": src["id"], "stance": "supports"})
    assert linked.status_code == 201
    assert client.post(f"{url}/submit", headers=w["agent"]).json()["status"] == "under_review"
    review = {"decision": "accept", "rationale": "Consistent with cited measurements."}
    assert client.post(f"{url}/reviews", headers=w["agent"], json=review).status_code == 403
    assert client.post(f"{url}/reviews", headers=w["scientist"], json=review).status_code == 403
    unverified = client.post(f"{url}/reviews", headers=w["reviewer"], json=review)
    assert unverified.status_code == 409
    verified = client.post(f"{w['base']}/sources/{src['id']}/verify", headers=w["reviewer"])
    assert verified.json()["verified_at"] is not None
    accepted = client.post(f"{url}/reviews", headers=w["reviewer"], json=review)
    assert accepted.status_code == 201
    assert accepted.json()["to_status"] == "accepted"
    detail = client.get(url, headers=w["owner"]).json()
    assert detail["status"] == "accepted" and len(detail["reviews"]) == 1
    assert client.post(f"{url}/evidence", headers=w["agent"],
                       json={"source_id": src["id"], "stance": "context"}).status_code == 409
    retract = client.post(f"{url}/reviews", headers=w["reviewer"],
                          json={"decision": "retract", "rationale": "Source later corrected."})
    assert retract.json()["to_status"] == "retracted"


def test_authors_cannot_review_or_verify_their_own_work(client, world):
    w = world
    src = source(client, w, who="owner", identifier="10.1000/own")
    assert client.post(f"{w['base']}/sources/{src['id']}/verify",
                       headers=w["owner"]).status_code == 403
    c = claim(client, w, who="owner")
    url = f"{w['base']}/claims/{c['id']}"
    client.post(f"{url}/evidence", headers=w["owner"],
                json={"source_id": src["id"], "stance": "supports"})
    client.post(f"{url}/submit", headers=w["owner"])
    denied = client.post(f"{url}/reviews", headers=w["owner"],
                         json={"decision": "accept", "rationale": "I am sure it is right."})
    assert denied.status_code == 403
    assert denied.json()["error"]["message"].endswith("separation_of_duties.")


def test_simulated_measurements_alone_cannot_establish_a_claim(client, world):
    w = world
    project = client.post(f"{w['base']}/projects", headers=w["owner"],
                          json={"name": "M1", "slug": "m1", "program": "M1"}).json()
    assay = client.post(f"{w['base']}/assays", headers=w["owner"], json={
        "key": "glu", "name": "Glutamate", "quantity_kind": "glutamate_concentration",
        "unit": "g/L"}).json()
    m = client.post(f"{w['base']}/projects/{project['id']}/measurements", headers=w["agent"],
                    json={"assay_id": assay["id"], "origin": "SIMULATED", "sample_label": "A",
                          "biological_replicate": 1, "value": 3.2, "unit": "g/L",
                          "observed_at": "2026-11-01T00:00:00Z"}).json()
    c = claim(client, w)
    url = f"{w['base']}/claims/{c['id']}"
    client.post(f"{url}/evidence", headers=w["agent"],
                json={"measurement_id": m["id"], "stance": "supports"})
    both = client.post(f"{url}/evidence", headers=w["agent"], json={
        "measurement_id": m["id"], "source_id": m["id"], "stance": "supports"})
    assert both.status_code == 400
    client.post(f"{url}/submit", headers=w["agent"])
    response = client.post(f"{url}/reviews", headers=w["reviewer"],
                           json={"decision": "accept", "rationale": "Simulation looks fine."})
    assert response.status_code == 409
    changes = client.post(f"{url}/reviews", headers=w["reviewer"], json={
        "decision": "request_changes", "rationale": "Needs physical or literature support."})
    assert changes.json()["to_status"] == "draft"


def test_duplicate_sources_conflict_and_claims_filter_by_status(client, world):
    w = world
    source(client, w, identifier="10.1/dup")
    dup = client.post(f"{w['base']}/sources", headers=w["owner"], json={
        "kind": "doi", "identifier": "10.1/dup", "citation": "dup"})
    assert dup.status_code == 409
    claim(client, w)
    assert len(client.get(f"{w['base']}/claims", headers=w["owner"],
                          params={"status": "draft"}).json()) == 1
    assert client.get(f"{w['base']}/claims", headers=w["owner"],
                      params={"status": "accepted"}).json() == []
