import pytest

from umami_api.orchestration import run_one
from umami_api.science.qc import Point, biomass_yield, evaluate, reproducibility, robust_z


def test_qc_checks_flag_without_altering_data():
    points = [Point(str(i), "S1", bio, 1, v) for i, (bio, v) in
              enumerate([(1, 10.0), (2, 10.5), (3, 9.8)])]
    assert evaluate(points, "biomass_concentration")["status"] == "pass"
    noisy = points + [Point("x", "S2", 1, 1, 5.0), Point("y", "S2", 2, 1, 15.0)]
    result = evaluate(noisy, "biomass_concentration")
    checks = {f["check"] for f in result["flags"]}
    assert {"replicate_cv", "replication"} <= checks and result["status"] == "warn"
    bad = evaluate([Point("z", "S3", 1, 1, 999.0)], "biomass_concentration")
    assert bad["status"] == "fail"
    assert max(abs(z) for z in robust_z([1, 1.1, 0.9, 1.0, 9.0])) > 3.5


def test_yield_and_reproducibility_helpers():
    assert biomass_yield(0.1, 9.7, 20.0, 0.0) == pytest.approx(0.48)
    assert biomass_yield(0.1, 0.1, 20.0, 20.0) is None
    assert reproducibility([9.6, 9.7, 9.65])["reproducible"] is True
    assert reproducibility([1.0])["cv"] is None


DESIGN = {"label": "R", "temperature_c": 30, "ph": 5, "initial_glucose_g_l": 20,
          "duration_h": 24, "sample_interval_h": 4, "biological_replicates": 3,
          "technical_replicates": 2}


def test_qc_workflow_on_simulated_runs(client, owner, make_member, database):
    headers, workspace_id, _ = owner
    base = f"/api/v1/workspaces/{workspace_id}"
    project = client.post(f"{base}/projects", headers=headers,
                          json={"name": "M1", "slug": "m1", "program": "M1"}).json()
    pbase = f"{base}/projects/{project['id']}"
    runs = [client.post(f"{pbase}/simulated-runs", headers=headers,
                        json={**DESIGN, "seed": seed}).json() for seed in (1, 2)]
    assert run_one(database) == run_one(database) == "succeeded"
    norm = client.get(f"{pbase}/runs/{runs[0]['id']}/normalization", headers=headers).json()
    assert 0.3 < norm["biomass_yield_g_g"] < 0.55
    assert 0.1 < norm["specific_growth_rate_per_h"] < 0.6
    repro = client.get(f"{pbase}/reproducibility", headers=headers).json()
    assert repro[0]["runs"] == 2 and repro[0]["reproducible"] is True
    assay = next(a for a in client.get(f"{base}/assays", headers=headers).json()
                 if a["key"] == "sim-dcw")
    report = client.post(f"{pbase}/qc-reports", headers=headers, json={
        "assay_id": assay["id"], "origin": "SIMULATED", "run_id": runs[0]["id"]}).json()
    assert report["status"] in ("pass", "warn") and report["metrics"]["samples"] == 7
    url = f"{pbase}/qc-reports/{report['id']}/disposition"
    decision = {"decision": "accepted", "rationale": "Replicates consistent with model noise."}
    assert client.post(url, headers=headers, json=decision).status_code == 403  # own report
    reviewer, _ = make_member("reviewer")
    accepted = client.post(url, headers=reviewer, json=decision).json()
    assert accepted["disposition"]["decision"] == "accepted"
    assert client.post(url, headers=reviewer, json=decision).status_code == 409
    none = client.post(f"{pbase}/qc-reports", headers=headers, json={
        "assay_id": assay["id"], "origin": "PHYSICAL"})
    assert none.status_code == 409
