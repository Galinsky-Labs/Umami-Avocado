import math

import pytest

from umami_api.orchestration import run_one
from umami_api.science.simulator import (
    Design,
    ph_factor,
    simulate,
    summarize_final,
    temperature_factor,
)

DESIGN = Design(temperature_c=30, ph=5.0, initial_glucose_g_l=20, initial_biomass_g_l=0.1,
                duration_h=24, sample_interval_h=4, biological_replicates=3,
                technical_replicates=2, seed=7)


def test_simulation_is_deterministic_and_seed_sensitive():
    assert simulate(DESIGN) == simulate(DESIGN)
    assert simulate(DESIGN) != simulate(Design(**{**DESIGN.__dict__, "seed": 8}))


def test_mass_balance_and_physiological_shape():
    final = summarize_final(simulate(DESIGN))
    # Biomass cannot exceed initial biomass + yield * glucose consumed.
    assert final["biomass_concentration"] <= 0.1 + 0.48 * 20 * 1.1
    assert final["substrate_concentration"] < 1.0  # glucose exhausted within 24 h at optimum
    assert final["glutamate_concentration"] > 0
    cold = summarize_final(simulate(Design(**{**DESIGN.__dict__, "temperature_c": 12})))
    assert cold["biomass_concentration"] < final["biomass_concentration"]
    assert temperature_factor(30) == pytest.approx(1.0)
    assert temperature_factor(45) == 0 and temperature_factor(4) == 0
    assert ph_factor(5.0) == 1.0 and ph_factor(3.0) < 0.1


def test_sample_counts_follow_replicate_design():
    samples = simulate(DESIGN)
    points = 24 // 4 + 1
    assert len(samples) == points * 3 * 2 * 3
    assert all(math.isfinite(s.value) and s.value >= 0 for s in samples)


@pytest.fixture
def project(client, owner):
    headers, workspace_id, _ = owner
    base = f"/api/v1/workspaces/{workspace_id}"
    project = client.post(f"{base}/projects", headers=headers,
                          json={"name": "M1", "slug": "m1", "program": "M1"}).json()
    return headers, base, project["id"]


DESIGN_BODY = {"label": "R1", "temperature_c": 30, "ph": 5, "initial_glucose_g_l": 20,
               "duration_h": 12, "sample_interval_h": 4, "biological_replicates": 2,
               "technical_replicates": 1, "seed": 3}


def test_digital_milestone_end_to_end(client, project, database, make_member):
    headers, base, project_id = project
    reviewer, _ = make_member("reviewer")
    agent, agent_id = make_member("agent", kind="agent")
    client.post(f"{base}/research-contracts", headers=headers, json={
        "agent_id": agent_id, "purpose": "digital loop", "ttl_days": 1,
        "project_ids": [project_id],
        "actions": ["experiment.submit_simulated", "claim.propose", "evidence.add"]})
    milestone = f"{base}/projects/{project_id}/digital-milestone"
    assert client.get(milestone, headers=headers).json()["achieved"] is False

    submitted = client.post(f"{base}/projects/{project_id}/simulated-runs", headers=agent,
                            json=DESIGN_BODY)
    assert submitted.status_code == 202, submitted.text
    run = submitted.json()
    assert run["origin"] == "SIMULATED" and run["state"] == "queued"
    assert run_one(database) == "succeeded"
    done = client.get(f"{base}/projects/{project_id}/runs/{run['id']}", headers=headers).json()
    assert done["state"] == "completed" and done["summary"]["origin"] == "SIMULATED"

    measurements = client.get(f"{base}/projects/{project_id}/measurements", headers=headers,
                              params={"limit": 1000}).json()
    assert len(measurements) == done["summary"]["samples"] == 4 * 2 * 3
    assert {m["origin"] for m in measurements} == {"SIMULATED"}
    assert all(m["provenance"].startswith("simulator:") for m in measurements)

    claim = client.post(f"{base}/claims", headers=agent, json={
        "statement": "In simulation, 30 C and pH 5 exhaust 20 g/L glucose within 12 h.",
        "project_id": project_id}).json()
    client.post(f"{base}/claims/{claim['id']}/evidence", headers=agent,
                json={"measurement_id": measurements[-1]["id"], "stance": "supports"})
    client.post(f"{base}/claims/{claim['id']}/submit", headers=agent)
    body = client.get(milestone, headers=headers).json()
    assert body["achieved"] is True and body["physical_results_exist"] is False
    accept = client.post(f"{base}/claims/{claim['id']}/reviews", headers=reviewer,
                         json={"decision": "accept", "rationale": "Simulation only, though."})
    assert accept.status_code == 409  # simulated output cannot establish a claim


def test_simulated_runs_are_idempotent_and_policy_checked(client, project, make_member, database):
    headers, base, project_id = project
    url = f"{base}/projects/{project_id}/simulated-runs"
    first = client.post(url, headers={**headers, "Idempotency-Key": "k1"}, json=DESIGN_BODY)
    again = client.post(url, headers={**headers, "Idempotency-Key": "k1"}, json=DESIGN_BODY)
    assert first.json()["id"] == again.json()["id"]
    viewer, _ = make_member("viewer")
    assert client.post(url, headers=viewer, json=DESIGN_BODY).status_code == 403
    agent, _ = make_member("agent", kind="agent")  # no contract
    assert client.post(url, headers=agent, json=DESIGN_BODY).status_code == 403
    bad = client.post(url, headers=headers, json={**DESIGN_BODY, "temperature_c": 90})
    assert bad.status_code == 400
    assert run_one(database) == "succeeded"
    # Redelivery of a completed run is a no-op rather than duplicate measurements.
    from umami_api.models import Job
    with database.session() as session:
        job = session.query(Job).one()
        job.state, job.run_after = "queued", job.created_at
    count = len(client.get(f"{base}/projects/{project_id}/measurements", headers=headers,
                           params={"limit": 1000}).json())
    assert run_one(database) == "succeeded"
    assert len(client.get(f"{base}/projects/{project_id}/measurements", headers=headers,
                          params={"limit": 1000}).json()) == count
