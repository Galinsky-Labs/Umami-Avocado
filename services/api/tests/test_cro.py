import pytest

CONTENT = {"organism": "Saccharomyces cerevisiae", "medium": "YPD", "temperature_c": 30, "ph": 5,
           "initial_glucose_g_l": 20, "duration_h": 24, "biological_replicates": 3,
           "steps": ["Inoculate", "Incubate", "Sample"]}


@pytest.fixture
def cro(client, owner, make_member):
    headers, workspace_id, _ = owner
    base = f"/api/v1/workspaces/{workspace_id}"
    project = client.post(f"{base}/projects", headers=headers,
                          json={"name": "M1", "slug": "m1", "program": "M1"}).json()
    lab = client.post(f"{base}/laboratories", headers=headers, json={
        "name": "Example CRO", "adapter_key": "manual_cro"}).json()
    sim = client.post(f"{base}/laboratories", headers=headers, json={
        "name": "Sim", "adapter_key": "simulator"}).json()
    source = client.post(f"{base}/sources", headers=headers, json={
        "kind": "doi", "identifier": "10.1/x", "citation": "Review"}).json()
    scientist, _ = make_member("scientist")
    reviewer, _ = make_member("reviewer")
    pbase = f"{base}/projects/{project['id']}"

    def proposal(content=CONTENT, target="PHYSICAL"):
        protocol = client.post(f"{base}/protocols", headers=scientist, json={
            "key": "batch", "title": "Batch", "content": content}).json()
        return client.post(f"{pbase}/proposals", headers=scientist, json={
            "protocol_version_id": protocol["id"], "title": "Pilot",
            "hypothesis": "Biomass reaches 8 g/L in 24 h.", "evidence_source_ids": [source["id"]],
            "target_origin": target}).json()

    return {"pbase": pbase, "owner": headers, "scientist": scientist, "reviewer": reviewer,
            "lab": lab["id"], "sim": sim["id"], "proposal": proposal}


def order(client, c, proposal_id, lab=None):
    return client.post(f"{c['pbase']}/work-orders", headers=c["scientist"], json={
        "laboratory_id": lab or c["lab"], "proposal_id": proposal_id, "title": "Pilot run"})


def test_package_is_frozen_approved_by_another_human_and_dispatch_is_blocked(client, cro):
    response = order(client, cro, cro["proposal"]()["id"])
    assert response.status_code == 201, response.text
    wo = response.json()
    assert len(wo["package_sha256"]) == 64
    url = f"{cro['pbase']}/work-orders/{wo['id']}"
    package = client.get(f"{cro['pbase']}/artifacts/{wo['package_artifact_id']}/content",
                         headers=cro["owner"])
    assert b"Not authorised for execution" in package.content
    assert client.post(f"{url}/approve", headers=cro["scientist"]).status_code == 403
    approved = client.post(f"{url}/approve", headers=cro["reviewer"])
    assert approved.status_code == 200, approved.text
    assert approved.json()["state"] == "approved"
    dispatch = client.post(f"{url}/dispatch", headers=cro["owner"])
    assert dispatch.status_code == 403
    assert "live_submission_disabled" in dispatch.json()["error"]["message"]
    files = client.post(f"{url}/files", headers={**cro["owner"], "Content-Type": "text/csv"},
                        content=b"a,b\n", params={"name": "r.csv"})
    assert files.status_code == 409
    client.post(f"{url}/notes", headers=cro["scientist"], json={"note": "Emailed CRO for quote"})
    log = client.get(f"{url}/exchange", headers=cro["owner"]).json()
    assert [i["direction"] for i in log] == ["note", "note", "note"]
    assert "sha256=" in log[1]["note"]


def test_work_order_preconditions(client, cro):
    sim_target = cro["proposal"](target="SIMULATED")
    assert order(client, cro, sim_target["id"]).status_code == 409
    assert order(client, cro, cro["proposal"]()["id"], lab=cro["sim"]).status_code == 400
    costly = cro["proposal"]({**CONTENT, "estimated_cost_cents": 90000})
    wo = order(client, cro, costly["id"]).json()
    blocked = client.post(f"{cro['pbase']}/work-orders/{wo['id']}/approve",
                          headers=cro["reviewer"])
    assert blocked.status_code == 409 and "reservation" in blocked.json()["error"]["message"]
    risky = cro["proposal"]({**CONTENT, "steps": ["Handle pathogen culture"]})
    wo = order(client, cro, risky["id"]).json()
    blocked = client.post(f"{cro['pbase']}/work-orders/{wo['id']}/approve",
                          headers=cro["reviewer"])
    assert blocked.status_code == 409 and "scope_screen" in blocked.json()["error"]["message"]
    cancelled = client.post(f"{cro['pbase']}/work-orders/{wo['id']}/cancel",
                            headers=cro["scientist"])
    assert cancelled.json()["state"] == "cancelled"
