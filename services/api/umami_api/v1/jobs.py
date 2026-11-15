"""Durable jobs and the outbox feed (UA-009)."""
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query
from sqlalchemy import select

from umami_api.authz import authorize
from umami_api.db import utcnow
from umami_api.errors import conflict, invalid, not_found
from umami_api.models import Job, OutboxEvent
from umami_api.orchestration import emit, enqueue
from umami_api.policy import Subject
from umami_api.schemas import JobIn, JobOut, OutboxEventOut
from umami_api.security import AccessDep
from umami_api.v1.projects import get_project

router = APIRouter(tags=["jobs"])
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key", max_length=80,
                                              pattern=r"^[A-Za-z0-9_.:-]+$")]


@router.post("/workspaces/{workspace_id}/jobs", response_model=JobOut, status_code=201,
             operation_id="enqueue_job")
def create_job(body: JobIn, access: AccessDep, idempotency_key: IdempotencyKey = None):
    if body.project_id is not None:
        get_project(access, body.project_id)
    authorize(access, "job.manage", Subject(project_id=body.project_id))
    if len(json.dumps(body.payload)) > 16_000:
        raise invalid("Job payloads are limited to 16 kB.")
    job, _created = enqueue(access.session, workspace_id=access.workspace.id, kind=body.kind,
                            payload=body.payload, created_by=access.principal.id,
                            project_id=body.project_id, idempotency_key=idempotency_key,
                            max_attempts=body.max_attempts)
    return job


@router.get("/workspaces/{workspace_id}/jobs", response_model=list[JobOut],
            operation_id="list_jobs")
def list_jobs(access: AccessDep, limit: Annotated[int, Query(ge=1, le=200)] = 50):
    return access.session.scalars(select(Job).where(Job.workspace_id == access.workspace.id)
                                  .order_by(Job.created_at.desc()).limit(limit)).all()


@router.get("/workspaces/{workspace_id}/jobs/{job_id}", response_model=JobOut,
            operation_id="get_job")
def get_job(job_id: uuid.UUID, access: AccessDep):
    job = access.session.scalar(select(Job).where(Job.id == job_id,
                                                  Job.workspace_id == access.workspace.id))
    if job is None:
        raise not_found("job")
    return job


@router.post("/workspaces/{workspace_id}/jobs/{job_id}/cancel", response_model=JobOut,
             operation_id="cancel_job")
def cancel_job(job_id: uuid.UUID, access: AccessDep):
    job = access.session.scalar(select(Job).where(
        Job.id == job_id, Job.workspace_id == access.workspace.id).with_for_update())
    if job is None:
        raise not_found("job")
    authorize(access, "job.manage", Subject(project_id=job.project_id), ("job", job.id))
    if job.state != "queued":
        raise conflict("Only queued jobs can be cancelled.")
    job.state, job.finished_at = "cancelled", utcnow()
    emit(access.session, job.workspace_id, "job.cancelled", {"job_id": str(job.id)})
    return job


@router.get("/workspaces/{workspace_id}/events", response_model=list[OutboxEventOut],
            operation_id="list_events")
def list_events(access: AccessDep, limit: Annotated[int, Query(ge=1, le=200)] = 50):
    return access.session.scalars(select(OutboxEvent).where(
        OutboxEvent.workspace_id == access.workspace.id)
        .order_by(OutboxEvent.created_at.desc()).limit(limit)).all()
