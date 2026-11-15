"""Shared fixtures. Database tests need TEST_DATABASE_URL (a disposable PostgreSQL)."""
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from umami_api.config import Settings, normalize_database_url
from umami_api.db import Database
from umami_api.main import create_app
from umami_api.migrate import upgrade
from umami_api.models import Base

BOOTSTRAP = "b" * 40


def settings(url: str | None = None, **overrides) -> Settings:
    values = {"environment": "test", "database_url": url, "migration_database_url": url,
              "bootstrap_token": BOOTSTRAP, "cors_origins": (),
              "lab_live_submission_enabled": False, "max_authorized_spend_cents": 0}
    values.update(overrides)
    return Settings(**values)


@pytest.fixture(scope="session")
def database_url():
    raw = os.getenv("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("TEST_DATABASE_URL is not set; PostgreSQL integration tests skipped.")
    url = normalize_database_url(raw)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    upgrade(url)
    return url


@pytest.fixture
def database(database_url):
    database = Database(database_url)
    yield database
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with database.engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} CASCADE"))
    database.dispose()


@pytest.fixture
def app(database, database_url):
    return create_app(settings(database_url), database=database)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def auth(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


@pytest.fixture
def owner(client):
    """Bootstrap the first owner; returns (headers, workspace_id, principal_id)."""
    response = client.post("/api/v1/bootstrap", headers={"X-Bootstrap-Token": BOOTSTRAP}, json={
        "display_name": "Owner", "email": "owner@example.test",
        "workspace_name": "Lab", "workspace_slug": "lab",
    })
    assert response.status_code == 201, response.text
    body = response.json()
    return auth(body["issued"]["secret"]), body["workspace"]["id"], body["principal"]["id"]


@pytest.fixture
def make_member(client, owner):
    headers, workspace_id, _ = owner

    def create(role: str, kind: str = "human", workspace: str | None = None,
               as_headers: dict | None = None):
        response = client.post(
            f"/api/v1/workspaces/{workspace or workspace_id}/members",
            headers=as_headers or headers,
            json={"kind": kind, "display_name": f"{role}-{uuid.uuid4().hex[:6]}", "role": role},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        return auth(body["issued"]["secret"]), body["member"]["principal"]["id"]

    return create
