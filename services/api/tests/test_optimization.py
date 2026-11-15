import pytest

from umami_api.orchestration import run_one
from umami_api.science.optimization import Observation, suggest, validate_bounds

BOX = {"temperature_c": (20, 40), "ph": (3.5, 7), "initial_glucose_g_l": (10, 40)}


def test_suggestions_respect_bounds_spacing_and_are_deterministic():
    first = suggest([], BOX, 3)
    assert first == suggest([], BOX, 3)
    assert first[0].x == {"temperature_c": 30.0, "ph": 5.25, "initial_glucose_g_l": 25.0}
    for s in first:
        for dim, (lo, hi) in BOX.items():
            assert lo <= s.x[dim] <= hi
    with pytest.raises(ValueError):
        validate_bounds({"temperature_c": (0, 90)})
    with pytest.raises(ValueError):
        suggest([], BOX, 7)


def test_gp_ucb_moves_towards_better_regions():
    obs = [Observation({"temperature_c": t, "ph": 5.0, "initial_glucose_g_l": 20.0},
                       10 - abs(t - 30) / 2) for t in (20, 25, 35, 40)]
    picks = suggest(obs, BOX, 2)
    assert picks[0].predicted_mean is not None and picks[0].reason.startswith("GP-UCB")
    assert 25 <= picks[0].x["temperature_c"] <= 35


def test_rounds_queue_bounded_simulated_runs(client, owner, database, make_member):
    headers, workspace_id, _ = owner
    base = f"/api/v1/workspaces/{workspace_id}"
    project = client.post(f"{base}/projects", headers=headers,
                          json={"name": "M1", "slug": "m1", "program": "M1"}).json()
    url = f"{base}/projects/{project['id']}/optimization/rounds"
    first = client.post(url, headers=headers, json={"batch_size": 3, "duration_h": 12,
                                                    "queue_simulated_runs": True})
    assert first.status_code == 201, first.text
    assert len(first.json()["queued_run_ids"]) == 3
    for _ in range(3):
        assert run_one(database) == "succeeded"
    second = client.post(url, headers=headers, json={"batch_size": 2}).json()
    assert len(second["observations"]) == 3 and second["strategy"].startswith("GP-UCB")
    assert second["queued_run_ids"] == []
    viewer, _ = make_member("viewer")
    assert client.post(url, headers=viewer, json={}).status_code == 403
    too_wide = client.post(url, headers=headers,
                           json={"bounds": {"temperature_c": [0, 60]}})
    assert too_wide.status_code == 400
    for _ in range(3):
        client.post(url, headers=headers, json={"batch_size": 6, "queue_simulated_runs": True})
    quota = client.post(url, headers=headers, json={"batch_size": 6,
                                                    "queue_simulated_runs": True})
    assert quota.status_code == 409 and quota.json()["error"]["code"] == "limit_exceeded"
    assert len(client.get(url, headers=headers).json()) >= 5
