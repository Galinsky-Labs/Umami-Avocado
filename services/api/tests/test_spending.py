import pytest
from conftest import settings
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from umami_api.main import create_app


@pytest.fixture
def world(client, owner, make_member):
    headers, workspace_id, _ = owner
    base = f"/api/v1/workspaces/{workspace_id}"
    project = client.post(f"{base}/projects", headers=headers,
                          json={"name": "M1", "slug": "m1", "program": "M1"}).json()
    scientist, _ = make_member("scientist")
    admin, _ = make_member("admin")
    return {"base": base, "owner": headers, "scientist": scientist, "admin": admin,
            "project": project["id"]}


def reserve(client, w, amount=5000, who="scientist", **extra):
    return client.post(f"{w['base']}/reservations", headers=w[who], json={
        "project_id": w["project"], "amount_cents": amount, "purpose": "Media and assays",
        **extra})


def test_default_platform_cap_of_zero_blocks_every_approval(client, world):
    w = world
    budget = client.put(f"{w['base']}/projects/{w['project']}/budget", headers=w["owner"],
                        json={"cap_cents": 100000}).json()
    assert budget["available_cents"] == 100000 and budget["platform_cap_cents"] == 0
    reservation = reserve(client, w).json()
    denied = client.post(f"{w['base']}/reservations/{reservation['id']}/approve",
                         headers=w["owner"])
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "limit_exceeded"


@pytest.fixture
def funded(database, database_url, world):
    """Same database, but an app whose platform cap is $500."""
    app = create_app(settings(database_url, max_authorized_spend_cents=50000), database=database)
    with TestClient(app) as client:
        client.put(f"{world['base']}/projects/{world['project']}/budget",
                   headers=world["owner"], json={"cap_cents": 30000})
        yield client, world


def test_double_entry_reservation_lifecycle(funded, database):
    client, w = funded
    r = reserve(client, w, 20000).json()
    assert r["status"] == "requested"
    approve = f"{w['base']}/reservations/{r['id']}/approve"
    assert client.post(approve, headers=w["admin"]).status_code == 403  # admins cannot approve
    assert client.post(approve, headers=w["owner"]).json()["status"] == "approved"
    balances = client.get(f"{w['base']}/projects/{w['project']}/budget", headers=w["owner"]).json()
    assert (balances["available_cents"], balances["reserved_cents"]) == (10000, 20000)
    over = reserve(client, w, 15000).json()
    response = client.post(f"{w['base']}/reservations/{over['id']}/approve", headers=w["owner"])
    assert response.json()["error"]["code"] == "limit_exceeded"
    lowered = client.put(f"{w['base']}/projects/{w['project']}/budget", headers=w["owner"],
                         json={"cap_cents": 10000})
    assert lowered.status_code == 409
    released = client.post(f"{w['base']}/reservations/{r['id']}/release", headers=w["owner"])
    assert released.json()["status"] == "released"
    ledger = client.get(f"{w['base']}/projects/{w['project']}/ledger", headers=w["owner"]).json()
    assert sum(e["amount_cents"] for e in ledger) == 0
    totals = {}
    for entry in ledger:
        totals[entry["account"]] = totals.get(entry["account"], 0) + entry["amount_cents"]
    assert totals == {"funding": -30000, "available": 30000, "reserved": 0}
    with pytest.raises(DBAPIError), database.engine.begin() as connection:
        connection.execute(text("UPDATE ledger_entries SET amount_cents = 0"))


def test_self_approval_agents_and_simulated_quotes(funded, make_member):
    client, w = funded
    own = reserve(client, w, 1000, who="owner").json()
    selfie = client.post(f"{w['base']}/reservations/{own['id']}/approve", headers=w["owner"])
    assert selfie.status_code == 403
    agent, agent_id = make_member("agent", kind="agent")
    client.post(f"{w['base']}/research-contracts", headers=w["owner"], json={
        "agent_id": agent_id, "purpose": "quotes", "ttl_days": 1, "actions": ["quote.record"]})
    assert reserve(client, {**w, "agent": agent}, who="agent").status_code == 403
    quote = {"project_id": w["project"], "vendor": "Simulated CRO", "description": "10 L run",
             "amount_cents": 4200}
    assert client.post(f"{w['base']}/quotes", headers=agent,
                       json={**quote, "origin": "PHYSICAL"}).status_code == 403
    simulated = client.post(f"{w['base']}/quotes", headers=agent,
                            json={**quote, "origin": "SIMULATED"}).json()
    backed = reserve(client, w, 4200, quote_id=simulated["id"])
    assert backed.status_code == 409


def test_unbalanced_postings_are_rejected_by_the_database(database, world):
    import uuid
    with pytest.raises(DBAPIError), database.engine.begin() as connection:
        principal = connection.execute(text("SELECT id FROM principals LIMIT 1")).scalar()
        ws = connection.execute(text("SELECT workspace_id FROM projects LIMIT 1")).scalar()
        connection.execute(text(
            "INSERT INTO ledger_entries (id, workspace_id, project_id, posting_id, account, "
            "amount_cents, memo, posted_by, posted_at) VALUES (:id, :ws, :p, :post, 'spent', 5, "
            "'x', :who, now())"),
            {"id": uuid.uuid4(), "ws": ws, "p": world["project"], "post": uuid.uuid4(),
             "who": principal})
