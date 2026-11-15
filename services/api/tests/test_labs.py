import csv
import io

import pytest

from umami_api.labs.builtin import ManualCROAdapter, SimulatedLabAdapter
from umami_api.labs.sdk import (
    Capability,
    LiveSubmissionDisabled,
    SubmissionState,
    WorkOrder,
    dispatch_guard,
)

ORDER = WorkOrder("o1", "batch_fermentation", "Saccharomyces cerevisiae",
                  {"temperature_c": 30, "ph": 5, "duration_h": 8}, replicates=2)


def test_simulated_adapter_round_trip_is_labelled_and_idempotent():
    adapter = SimulatedLabAdapter()
    assert adapter.quote(ORDER).amount_cents == 0
    first = adapter.submit(ORDER)
    assert adapter.submit(ORDER).external_id == first.external_id
    files = adapter.fetch_results(first.external_id)
    rows = list(csv.DictReader(io.StringIO(files[0].content.decode())))
    assert {r["origin"] for r in rows} == {"SIMULATED"} and files[0].origin == "SIMULATED"
    assert len(files[0].sha256) == 64
    assert adapter.status(first.external_id) == SubmissionState.COMPLETED
    other = SimulatedLabAdapter()
    assert other.fetch_results(other.submit(ORDER).external_id)[0].content == files[0].content
    with pytest.raises(ValueError):
        adapter.submit(WorkOrder("o2", "batch_fermentation", "Escherichia coli", {}))


def test_physical_adapters_cannot_dispatch_while_live_submission_is_disabled():
    cro = ManualCROAdapter([Capability("batch_fermentation", ("Saccharomyces cerevisiae",))])
    with pytest.raises(LiveSubmissionDisabled):
        cro.submit(ORDER)
    with pytest.raises(LiveSubmissionDisabled):
        dispatch_guard(cro, False)
    dispatch_guard(SimulatedLabAdapter(), False)
    assert cro.supports("batch_fermentation", "Saccharomyces cerevisiae")


CAP = {"code": "batch_fermentation", "organisms": ["Saccharomyces cerevisiae"],
       "assay_keys": ["dcw"], "unit_price_cents": 50000}


def test_lab_registry_contracts_and_matching(client, owner, make_member):
    headers, workspace_id, _ = owner
    base = f"/api/v1/workspaces/{workspace_id}"
    adapters = {a["key"]: a for a in client.get("/api/v1/lab-adapters").json()}
    assert adapters["manual_cro"]["dispatch_enabled"] is False
    scientist, _ = make_member("scientist")
    assert client.post(f"{base}/laboratories", headers=scientist, json={
        "name": "X", "adapter_key": "manual_cro"}).status_code == 403
    cro = client.post(f"{base}/laboratories", headers=headers, json={
        "name": "Example CRO", "adapter_key": "manual_cro", "capabilities": [CAP]}).json()
    sim = client.post(f"{base}/laboratories", headers=headers, json={
        "name": "Simulator", "adapter_key": "simulator",
        "capabilities": [{**CAP, "unit_price_cents": 0}]}).json()
    url = f"{base}/laboratories/{cro['id']}"
    assert client.patch(url, headers=headers, json={"status": "contracted"}).status_code == 409
    client.post(f"{url}/contracts", headers=headers, json={
        "title": "MSA", "scope": "Batch fermentation of food yeasts", "status": "signed"})
    assert client.patch(url, headers=headers,
                        json={"status": "contracted"}).json()["status"] == "contracted"
    matches = client.get(f"{base}/laboratories/match", headers=headers, params={
        "capability": "batch_fermentation", "organism": "Saccharomyces cerevisiae"}).json()
    assert [m["laboratory"]["id"] for m in matches] == [cro["id"], sim["id"]]
    assert matches[0]["has_signed_contract"] is True
    bad = client.post(f"{base}/laboratories", headers=headers, json={
        "name": "Bad", "adapter_key": "manual_cro",
        "capabilities": [{**CAP, "organisms": ["Escherichia coli"]}]})
    assert bad.status_code == 400
