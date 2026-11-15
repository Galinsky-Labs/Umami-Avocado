import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

OBSERVED = "2026-11-01T12:00:00Z"


@pytest.fixture
def setup(client, owner):
    headers, workspace_id, _ = owner
    base = f"/api/v1/workspaces/{workspace_id}"
    project = client.post(f"{base}/projects", headers=headers,
                          json={"name": "M1", "slug": "m1", "program": "M1"}).json()
    assay = client.post(f"{base}/assays", headers=headers, json={
        "key": "dcw", "name": "Dry cell weight", "quantity_kind": "biomass_concentration",
        "unit": "g/L", "method": "Gravimetric, 105 C overnight"}).json()
    return headers, base, project, assay


def measurement(assay, origin="SIMULATED", value=10.0, unit="g/L", bio=1, tech=1, **extra):
    return {"assay_id": assay["id"], "origin": origin, "sample_label": "S1",
            "biological_replicate": bio, "technical_replicate": tech, "value": value,
            "unit": unit, "observed_at": OBSERVED, **extra}


def test_ontology_and_conversion_endpoints(client):
    body = client.get("/api/v1/ontology").json()
    assert any(u["symbol"] == "OD600" and not u["convertible"] for u in body["units"])
    assert "biological" in body["replicate_semantics"]
    ok = client.post("/api/v1/ontology/convert",
                     json={"value": 1, "from_unit": "g/L", "to_unit": "mg/L"})
    assert ok.json() == {"value": 1000.0, "unit": "mg/L"}
    bad = client.post("/api/v1/ontology/convert",
                      json={"value": 1, "from_unit": "OD600", "to_unit": "g/L"})
    assert bad.status_code == 400


def test_assays_are_versioned_and_unit_checked(client, setup):
    headers, base, _, assay = setup
    assert assay["version"] == 1
    again = client.post(f"{base}/assays", headers=headers, json={
        "key": "dcw", "name": "DCW v2", "quantity_kind": "biomass_concentration", "unit": "mg/L"})
    assert again.json()["version"] == 2
    wrong = client.post(f"{base}/assays", headers=headers, json={
        "key": "od", "name": "OD", "quantity_kind": "biomass_concentration", "unit": "OD600"})
    assert wrong.status_code == 400


def test_measurements_are_canonicalised_summarised_and_never_pooled(client, setup):
    headers, base, project, assay = setup
    url = f"{base}/projects/{project['id']}/measurements"
    for bio, tech, value, unit in [(1, 1, 10, "g/L"), (1, 2, 12000, "mg/L"), (2, 1, 14, "g/L")]:
        created = client.post(url, headers=headers, json=measurement(assay, value=value,
                                                                     unit=unit, bio=bio, tech=tech))
        assert created.status_code == 201, created.text
    physical = client.post(url, headers=headers, json=measurement(
        assay, origin="PHYSICAL", value=99, provenance="Manual balance reading, lab notebook p.4"))
    assert physical.status_code == 201
    summary = client.get(f"{url}/summary", headers=headers,
                         params={"assay_id": assay["id"], "origin": "SIMULATED"}).json()
    assert summary == [{"sample_label": "S1", "origin": "SIMULATED", "unit": "g/L", "mean": 12.5,
                        "sd": pytest.approx(2.1213203435596424), "n_biological": 2,
                        "n_technical": 3}]
    assert client.get(f"{url}/summary", headers=headers,
                      params={"assay_id": assay["id"]}).status_code == 400
    assert len(client.get(url, headers=headers, params={"origin": "PHYSICAL"}).json()) == 1


def test_physical_measurements_need_provenance_and_humans(client, setup, make_member):
    headers, base, project, assay = setup
    url = f"{base}/projects/{project['id']}/measurements"
    assert client.post(url, headers=headers,
                       json=measurement(assay, origin="PHYSICAL")).status_code == 400
    agent, agent_id = make_member("agent", kind="agent")
    client.post(f"{base}/research-contracts", headers=headers, json={
        "agent_id": agent_id, "purpose": "sim", "ttl_days": 1,
        "actions": ["measurement.record_simulated"]})
    assert client.post(url, headers=agent, json=measurement(assay)).status_code == 201
    denied = client.post(url, headers=agent, json=measurement(
        assay, origin="PHYSICAL", provenance="claimed instrument output from agent"))
    assert denied.status_code == 403


def test_measurements_are_immutable_and_corrections_keep_origin(client, setup, database):
    headers, base, project, assay = setup
    url = f"{base}/projects/{project['id']}/measurements"
    first = client.post(url, headers=headers, json=measurement(assay, value=10)).json()
    switch = client.post(url, headers=headers, json=measurement(
        assay, origin="PHYSICAL", value=11, supersedes_id=first["id"],
        provenance="attempt to relabel simulated as physical"))
    assert switch.status_code == 409
    fixed = client.post(url, headers=headers, json=measurement(assay, value=11,
                                                                supersedes_id=first["id"]))
    assert fixed.status_code == 201
    summary = client.get(f"{url}/summary", headers=headers,
                         params={"assay_id": assay["id"], "origin": "SIMULATED"}).json()
    assert summary[0]["mean"] == 11
    with pytest.raises(DBAPIError), database.engine.begin() as connection:
        connection.execute(text("UPDATE measurements SET origin = 'PHYSICAL'"))
