import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


@pytest.fixture
def lab(client, owner, make_member):
    headers, workspace_id, _ = owner
    base = f"/api/v1/workspaces/{workspace_id}"
    scientist, _ = make_member("scientist")
    return {"base": base, "owner": headers, "scientist": scientist}


def material(client, lab, label, origin="PHYSICAL", who="scientist", kind="strain"):
    response = client.post(f"{lab['base']}/materials", headers=lab[who], json={
        "kind": kind, "label": label, "organism": "Saccharomyces cerevisiae", "origin": origin,
        "custodian": "Freezer A", "location": "-80C rack 2"})
    assert response.status_code == 201, response.text
    return response.json()


def test_lineage_graph_and_origin_separation(client, lab):
    strain = material(client, lab, "S288C")
    url = f"{lab['base']}/materials/derive"
    culture = client.post(url, headers=lab["scientist"], json={
        "parent_ids": [strain["id"]], "relation": "subcultured_from",
        "child": {"kind": "culture", "label": "C1", "origin": "PHYSICAL",
                  "custodian": "Bench 1"}}).json()
    sample = client.post(url, headers=lab["scientist"], json={
        "parent_ids": [culture["id"]], "relation": "split_from",
        "child": {"kind": "sample", "label": "C1-t12", "origin": "PHYSICAL",
                  "custodian": "Bench 1"}}).json()
    mixed = client.post(url, headers=lab["scientist"], json={
        "parent_ids": [culture["id"]], "relation": "derived_from",
        "child": {"kind": "sample", "label": "fake", "origin": "SIMULATED", "custodian": "x"}})
    assert mixed.status_code == 409
    graph = client.get(f"{lab['base']}/materials/{sample['id']}/lineage",
                       headers=lab["owner"]).json()
    assert {m["label"] for m in graph["materials"]} == {"S288C", "C1", "C1-t12"}
    assert len(graph["edges"]) == 2
    dup = client.post(f"{lab['base']}/materials", headers=lab["scientist"], json={
        "kind": "strain", "label": "S288C", "origin": "PHYSICAL", "custodian": "x"})
    assert dup.status_code == 409


def test_custody_chain_and_shipping_gate(client, lab, database):
    strain = material(client, lab, "CBS 621")
    url = f"{lab['base']}/materials/{strain['id']}/custody"
    moved = client.post(url, headers=lab["scientist"],
                        json={"event": "transferred", "to_party": "Bench 2"})
    assert moved.json()["from_party"] == "Freezer A"
    assert client.post(url, headers=lab["scientist"],
                       json={"event": "transferred"}).status_code == 400
    ship = client.post(url, headers=lab["owner"], json={"event": "shipped", "to_party": "CRO"})
    assert ship.status_code == 403
    assert "live_submission_disabled" in ship.json()["error"]["message"]
    client.post(url, headers=lab["scientist"], json={"event": "disposed"})
    assert client.post(url, headers=lab["scientist"],
                       json={"event": "stored"}).status_code == 409
    events = [e["event"] for e in client.get(url, headers=lab["owner"]).json()]
    assert events == ["registered", "transferred", "disposed"]
    with pytest.raises(DBAPIError), database.engine.begin() as connection:
        connection.execute(text("DELETE FROM custody_events"))


def test_agents_register_only_simulated_material(client, lab, make_member):
    agent, agent_id = make_member("agent", kind="agent")
    client.post(f"{lab['base']}/research-contracts", headers=lab["owner"], json={
        "agent_id": agent_id, "purpose": "sim samples", "ttl_days": 1,
        "actions": ["material.register"]})
    lab["agent"] = agent
    assert material(client, lab, "sim-1", origin="SIMULATED", who="agent")["origin"] == \
        "SIMULATED"
    physical = client.post(f"{lab['base']}/materials", headers=agent, json={
        "kind": "strain", "label": "p", "origin": "PHYSICAL", "custodian": "x"})
    assert physical.status_code == 403
