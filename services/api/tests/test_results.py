import csv
import hashlib
import io

from umami_api.orchestration import run_one

DESIGN = {"temperature_c": 30, "ph": 5, "initial_glucose_g_l": 20, "duration_h": 12,
          "sample_interval_h": 4, "biological_replicates": 3}


def test_series_comparison_and_exports(client, owner, database):
    headers, workspace_id, _ = owner
    base = f"/api/v1/workspaces/{workspace_id}"
    project = client.post(f"{base}/projects", headers=headers,
                          json={"name": "M1", "slug": "m1", "program": "M1"}).json()
    pbase = f"{base}/projects/{project['id']}"
    warm = client.post(f"{pbase}/simulated-runs", headers=headers,
                       json={**DESIGN, "label": "30C"}).json()
    cold = client.post(f"{pbase}/simulated-runs", headers=headers,
                       json={**DESIGN, "label": "20C", "temperature_c": 20}).json()
    run_one(database)
    run_one(database)
    series = client.get(f"{pbase}/results/series", headers=headers, params={
        "quantity_kind": "biomass_concentration", "run_ids": [warm["id"], cold["id"]]}).json()
    assert [s["label"] for s in series] == ["30C", "20C"]
    assert [p["time_h"] for p in series[0]["points"]] == [0, 4, 8, 12]
    assert series[0]["points"][-1]["mean"] > series[1]["points"][-1]["mean"]
    assert series[0]["points"][-1]["n_biological"] == 3
    compare = client.get(f"{pbase}/results/compare", headers=headers,
                         params={"run_ids": [warm["id"], cold["id"]]}).json()
    assert compare[0]["normalization"]["specific_growth_rate_per_h"] > \
        compare[1]["normalization"]["specific_growth_rate_per_h"]
    exported = client.get(f"{pbase}/exports/measurements.csv", headers=headers,
                          params={"origin": "SIMULATED"})
    assert exported.headers["x-content-sha256"] == hashlib.sha256(exported.content).hexdigest()
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert len(rows) == 2 * 4 * 3 * 3 and {r["origin"] for r in rows} == {"SIMULATED"}
    dataset = client.get(f"{pbase}/exports/dataset.json", headers=headers).json()
    assert dataset["format"] == "umami-avocado-dataset/1" and len(dataset["runs"]) == 2
    assert "SIMULATED" in dataset["notice"]
    bad = client.get(f"{pbase}/results/series", headers=headers,
                     params={"quantity_kind": "nonsense", "run_ids": [warm["id"]]})
    assert bad.status_code == 400
