from umami_api.orchestration import run_one


def test_timeline_and_exception_center(client, owner, make_member, database):
    headers, workspace_id, _ = owner
    base = f"/api/v1/workspaces/{workspace_id}"
    project = client.post(f"{base}/projects", headers=headers,
                          json={"name": "M1", "slug": "m1", "program": "M1"}).json()
    pbase = f"{base}/projects/{project['id']}"
    run = client.post(f"{pbase}/simulated-runs", headers=headers, json={
        "label": "R1", "temperature_c": 30, "ph": 5, "initial_glucose_g_l": 20,
        "duration_h": 8, "biological_replicates": 1}).json()
    assert run_one(database) == "succeeded"
    timeline = client.get(f"{pbase}/runs/{run['id']}/timeline", headers=headers).json()
    kinds = [e["kind"] for e in timeline["events"]]
    assert kinds[0] == "run.created" and "run.completed" in kinds and "job.succeeded" in kinds
    assert client.get(f"{base}/exceptions", headers=headers).json() == []
    failing = client.post(f"{base}/jobs", headers=headers, json={
        "kind": "diagnostic.echo", "payload": {"fail_times": 9}, "max_attempts": 1}).json()
    run_one(database)
    agent, agent_id = make_member("agent", kind="agent")
    client.post(f"{base}/research-contracts", headers=headers, json={
        "agent_id": agent_id, "purpose": "lit", "ttl_days": 1, "actions": ["evidence.add"]})
    client.post(f"{base}/sources", headers=agent, json={
        "kind": "url", "identifier": "https://example.org/x", "citation": "Blog"})
    items = client.get(f"{base}/exceptions", headers=headers).json()
    assert {i["kind"] for i in items} == {"job.dead", "source.unverified"}
    assert items[0]["severity"] == "error" and items[0]["ref"] == failing["id"]
