def test_project_lifecycle_and_roles(client, owner, make_member):
    headers, workspace_id, _ = owner
    url = f"/api/v1/workspaces/{workspace_id}/projects"
    created = client.post(url, headers=headers, json={
        "name": "Savory yeast biomass", "slug": "m1-biomass", "program": "M1",
        "objective": "Maximise umami-relevant biomass yield."})
    assert created.status_code == 201
    project = created.json()
    assert project["status"] == "planning"
    duplicate = client.post(url, headers=headers, json={"name": "x", "slug": "m1-biomass",
                                                         "program": "M1"})
    assert duplicate.status_code == 409
    viewer, _ = make_member("viewer")
    assert client.get(url, headers=viewer).json()[0]["id"] == project["id"]
    assert client.post(url, headers=viewer, json={"name": "x", "slug": "x2",
                                                   "program": "M1"}).status_code == 403
    patched = client.patch(f"{url}/{project['id']}", headers=headers, json={"status": "active"})
    assert patched.json()["status"] == "active"
    invalid = client.patch(f"{url}/{project['id']}", headers=headers, json={"status": "done"})
    assert invalid.status_code == 400


def test_projects_are_not_reachable_through_another_workspace(client, owner):
    headers, workspace_id, _ = owner
    other = client.post("/api/v1/workspaces", headers=headers,
                        json={"name": "Other", "slug": "other"}).json()
    project = client.post(f"/api/v1/workspaces/{workspace_id}/projects", headers=headers,
                          json={"name": "P", "slug": "pa", "program": "A1"}).json()
    response = client.get(f"/api/v1/workspaces/{other['id']}/projects/{project['id']}",
                          headers=headers)
    assert response.status_code == 404


def test_readiness_reports_connected_database(client):
    body = client.get("/api/readiness").json()
    assert body["status"] == "ready"
    assert body["database_connected"] is True
    assert body["live_lab_orders_enabled"] is False
