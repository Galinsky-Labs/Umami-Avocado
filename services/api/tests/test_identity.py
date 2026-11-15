import uuid

from conftest import BOOTSTRAP, auth, settings
from fastapi.testclient import TestClient
from sqlalchemy import select

from umami_api.main import create_app
from umami_api.models import ApiToken


def test_bootstrap_requires_secret_and_runs_once(client):
    body = {"display_name": "Owner", "email": "o@example.test", "workspace_name": "Lab",
            "workspace_slug": "lab"}
    assert client.post("/api/v1/bootstrap", json=body).status_code == 401
    wrong = client.post("/api/v1/bootstrap", headers={"X-Bootstrap-Token": "x" * 40}, json=body)
    assert wrong.status_code == 401
    first = client.post("/api/v1/bootstrap", headers={"X-Bootstrap-Token": BOOTSTRAP}, json=body)
    assert first.status_code == 201
    assert first.json()["issued"]["secret"].startswith("ua_")
    again = client.post("/api/v1/bootstrap", headers={"X-Bootstrap-Token": BOOTSTRAP}, json=body)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "conflict"


def test_bootstrap_disabled_without_configured_secret(database, database_url):
    app = create_app(settings(database_url, bootstrap_token=None), database=database)
    with TestClient(app) as client:
        response = client.post("/api/v1/bootstrap", headers={"X-Bootstrap-Token": ""}, json={
            "display_name": "O", "email": "o@example.test", "workspace_name": "L",
            "workspace_slug": "lab"})
    assert response.status_code == 401


def test_only_token_digest_is_stored_and_me_lists_memberships(client, owner, database):
    headers, workspace_id, principal_id = owner
    me = client.get("/api/v1/me", headers=headers).json()
    assert me["principal"]["id"] == principal_id
    assert me["memberships"][0]["role"] == "owner"
    assert me["memberships"][0]["workspace"]["id"] == workspace_id
    assert me["live_lab_orders_enabled"] is False
    secret = headers["Authorization"].split()[1]
    with database.session() as session:
        stored = session.scalars(select(ApiToken)).all()
    assert all(secret not in (t.token_hash, t.prefix) for t in stored)


def test_missing_invalid_and_revoked_tokens_are_rejected(client, owner):
    headers, _, _ = owner
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers=auth("ua_" + "x" * 43)).status_code == 401
    assert client.get("/api/v1/me", headers={"Authorization": "Basic abc"}).status_code == 401
    issued = client.post("/api/v1/tokens", headers=headers, json={"label": "cli"}).json()
    extra = auth(issued["secret"])
    assert client.get("/api/v1/me", headers=extra).status_code == 200
    revoked = client.delete(f"/api/v1/tokens/{issued['token']['id']}", headers=headers)
    assert revoked.json()["revoked_at"] is not None
    assert client.get("/api/v1/me", headers=extra).status_code == 401
    assert client.get("/api/v1/me", headers=headers).status_code == 200


def test_tokens_of_other_principals_cannot_be_revoked(client, owner, make_member):
    headers, _, _ = owner
    other, _ = make_member("viewer")
    token_id = client.get("/api/v1/tokens", headers=other).json()[0]["id"]
    assert client.delete(f"/api/v1/tokens/{token_id}", headers=headers).status_code == 404


def test_workspace_scoping_hides_foreign_workspaces(client, owner, make_member):
    headers, workspace_id, _ = owner
    outsider = client.post("/api/v1/workspaces", headers=headers,
                           json={"name": "Other", "slug": "other"}).json()
    viewer, _ = make_member("viewer")
    assert client.get(f"/api/v1/workspaces/{workspace_id}", headers=viewer).status_code == 200
    assert client.get(f"/api/v1/workspaces/{outsider['id']}", headers=viewer).status_code == 404
    missing = client.get(f"/api/v1/workspaces/{uuid.uuid4()}", headers=viewer)
    assert missing.status_code == 404
    assert client.get(f"/api/v1/workspaces/{outsider['id']}/projects",
                      headers=viewer).status_code == 404


def test_member_management_rules(client, owner, make_member):
    headers, workspace_id, _ = owner
    scientist, _ = make_member("scientist")
    url = f"/api/v1/workspaces/{workspace_id}/members"
    denied = client.post(url, headers=scientist, json={"kind": "human", "display_name": "x",
                                                        "role": "viewer"})
    assert denied.status_code == 403
    mismatch = client.post(url, headers=headers, json={"kind": "agent", "display_name": "bot",
                                                        "role": "scientist"})
    assert mismatch.status_code == 400
    admin, _ = make_member("admin")
    escalate = client.post(url, headers=admin, json={"kind": "human", "display_name": "x",
                                                      "role": "owner"})
    assert escalate.status_code == 403
    agent, _ = make_member("agent", kind="agent")
    assert client.post("/api/v1/workspaces", headers=agent,
                       json={"name": "A", "slug": "agent-space"}).status_code == 403
    roles = sorted(m["role"] for m in client.get(url, headers=headers).json())
    assert roles == ["admin", "agent", "owner", "scientist"]


def test_unknown_fields_are_rejected_without_echo(client, owner):
    headers, workspace_id, _ = owner
    response = client.post(f"/api/v1/workspaces/{workspace_id}/projects", headers=headers,
                           json={"name": "P", "slug": "p1", "program": "M1",
                                 "private-owner-fixture": True})
    assert response.status_code == 400
    assert "private-owner-fixture" not in response.text


def test_oversized_bodies_are_refused(client, owner):
    headers, workspace_id, _ = owner
    response = client.post(f"/api/v1/workspaces/{workspace_id}/projects", headers=headers,
                           content=b"{" + b" " * 300_000 + b"}")
    assert response.status_code == 413
