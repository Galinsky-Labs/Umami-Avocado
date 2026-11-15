import threading
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from umami_api.db import utcnow
from umami_api.models import Job, OutboxEvent
from umami_api.orchestration import claim, dispatch_outbox, handler, run_one
from umami_api.worker_loop import start_embedded, tick


@pytest.fixture
def jobs_url(client, owner):
    headers, workspace_id, _ = owner
    return headers, f"/api/v1/workspaces/{workspace_id}"


def enqueue(client, headers, base, payload=None, key=None, max_attempts=3):
    extra = {"Idempotency-Key": key} if key else {}
    response = client.post(f"{base}/jobs", headers={**headers, **extra}, json={
        "kind": "diagnostic.echo", "payload": payload or {"message": "hi"},
        "max_attempts": max_attempts})
    assert response.status_code == 201, response.text
    return response.json()


def test_enqueue_execute_and_outbox_delivery(client, jobs_url, database):
    headers, base = jobs_url
    job = enqueue(client, headers, base)
    assert job["state"] == "queued"
    assert run_one(database) == "succeeded"
    assert run_one(database) == "idle"
    done = client.get(f"{base}/jobs/{job['id']}", headers=headers).json()
    assert done["result"] == {"echo": "hi"} and done["attempts"] == 1
    published = []
    assert dispatch_outbox(database, published.append) == 2
    assert [e.topic for e in published] == ["job.queued", "job.succeeded"]
    assert dispatch_outbox(database, published.append) == 0
    events = client.get(f"{base}/events", headers=headers).json()
    assert all(e["published_at"] for e in events)


def test_idempotency_key_returns_the_same_job(client, jobs_url):
    headers, base = jobs_url
    first = enqueue(client, headers, base, key="run-1")
    second = enqueue(client, headers, base, key="run-1")
    assert first["id"] == second["id"]
    assert len(client.get(f"{base}/jobs", headers=headers).json()) == 1


def test_failures_back_off_retry_then_go_dead(client, jobs_url, database):
    headers, base = jobs_url
    flaky = enqueue(client, headers, base, payload={"fail_times": 1})
    assert run_one(database) == "queued"
    with database.session() as session:
        job = session.get(Job, flaky["id"])
        assert job.run_after > utcnow() and "requested diagnostic failure" in job.last_error
        job.run_after = utcnow()
    assert run_one(database) == "succeeded"
    doomed = enqueue(client, headers, base, payload={"fail_times": 99}, max_attempts=2)
    run_one(database)
    with database.session() as session:
        session.execute(update(Job).where(Job.id == doomed["id"]).values(run_after=utcnow()))
    assert run_one(database) == "dead"
    with database.session() as session:
        topics = session.scalars(select(OutboxEvent.topic)).all()
    assert "job.dead" in topics


def test_expired_leases_are_reclaimed_and_live_leases_are_skipped(client, jobs_url, database):
    headers, base = jobs_url
    job = enqueue(client, headers, base)
    with database.session() as session:
        assert claim(session, "crashed-worker").id.hex == job["id"].replace("-", "")
    with database.session() as session:
        assert claim(session, "other") is None  # lease still valid
        session.execute(update(Job).values(locked_until=utcnow() - timedelta(seconds=1)))
    assert run_one(database, "rescuer") == "succeeded"


def test_cancel_and_permissions(client, jobs_url, make_member):
    headers, base = jobs_url
    job = enqueue(client, headers, base)
    viewer, _ = make_member("viewer")
    assert client.post(f"{base}/jobs/{job['id']}/cancel", headers=viewer).status_code == 403
    assert client.post(f"{base}/jobs/{job['id']}/cancel",
                       headers=headers).json()["state"] == "cancelled"
    assert client.post(f"{base}/jobs/{job['id']}/cancel", headers=headers).status_code == 409
    unknown = client.post(f"{base}/jobs", headers=headers, json={"kind": "lab.order"})
    assert unknown.status_code == 400


def test_physical_job_kinds_cannot_be_registered():
    with pytest.raises(ValueError):
        handler("submit_physical_order")


def test_embedded_worker_thread_processes_jobs(client, jobs_url, database):
    headers, base = jobs_url
    job = enqueue(client, headers, base)
    thread, stop = start_embedded(database, poll_seconds=0.05)
    try:
        for _ in range(100):
            if client.get(f"{base}/jobs/{job['id']}", headers=headers).json()["state"] == \
                    "succeeded":
                break
            threading.Event().wait(0.05)
        else:
            pytest.fail("embedded worker did not process the job")
    finally:
        stop.set()
        thread.join(timeout=5)
    assert tick() == "idle"
