"""Durable job orchestration with a transactional outbox (UA-009).

* Jobs are rows; enqueueing happens in the caller's transaction together with an
  outbox event, so a committed state change always has its announcement.
* Workers claim with ``FOR UPDATE SKIP LOCKED`` and a time-bounded lease. A crashed
  worker's lease expires and the job is reclaimed (at-least-once execution), so
  handlers must be idempotent.
* Failures retry with exponential backoff up to ``max_attempts``, then go ``dead``.
* Handlers come from a closed, reviewed registry. No handler contacts a laboratory;
  any job kind containing "physical" is refused at registration and enqueue time.
"""
import logging
import socket
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from umami_api.db import Database, utcnow
from umami_api.models import Job, OutboxEvent

logger = logging.getLogger("umami.orchestration")
LEASE = timedelta(minutes=5)


class PermanentJobError(Exception):
    """Raised by handlers for failures that retrying cannot fix."""


@dataclass
class JobContext:
    session: Session
    job: Job

    def emit(self, topic: str, payload: dict) -> None:
        emit(self.session, self.job.workspace_id, topic, payload)


Handler = Callable[[JobContext], dict]
HANDLERS: dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    if "physical" in kind or not kind.replace(".", "").replace("_", "").isalnum():
        raise ValueError("Job kinds may not perform physical laboratory work.")

    def register(function: Handler) -> Handler:
        HANDLERS[kind] = function
        return function
    return register


@handler("diagnostic.echo")
def _echo(context: JobContext) -> dict:
    """Round-trips its payload; used to verify the pipeline end to end."""
    if context.job.payload.get("fail_times", 0) >= context.job.attempts:
        raise RuntimeError("requested diagnostic failure")
    return {"echo": context.job.payload.get("message", "")}


def emit(session: Session, workspace_id: uuid.UUID, topic: str, payload: dict) -> OutboxEvent:
    event = OutboxEvent(workspace_id=workspace_id, topic=topic, payload=payload)
    session.add(event)
    return event


def enqueue(session: Session, *, workspace_id: uuid.UUID, kind: str, payload: dict,
            created_by: uuid.UUID, project_id: uuid.UUID | None = None,
            idempotency_key: str | None = None, max_attempts: int = 3) -> tuple[Job, bool]:
    """Returns (job, created). An existing job with the same idempotency key is reused."""
    if kind not in HANDLERS:
        raise ValueError("Unknown job kind.")
    if idempotency_key:
        existing = session.scalar(select(Job).where(Job.workspace_id == workspace_id,
                                                    Job.idempotency_key == idempotency_key))
        if existing is not None:
            return existing, False
    job = Job(workspace_id=workspace_id, project_id=project_id, kind=kind, payload=payload,
              created_by=created_by, idempotency_key=idempotency_key, max_attempts=max_attempts)
    session.add(job)
    session.flush()
    emit(session, workspace_id, "job.queued", {"job_id": str(job.id), "kind": kind})
    return job, True


def backoff(attempt: int) -> timedelta:
    return timedelta(seconds=min(300, 2 ** attempt))


def claim(session: Session, worker_id: str) -> Job | None:
    now = utcnow()
    job = session.scalar(
        select(Job).where(or_(
            (Job.state == "queued") & (Job.run_after <= now),
            (Job.state == "running") & (Job.locked_until < now),
        )).order_by(Job.run_after).limit(1).with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.state, job.locked_by, job.locked_until = "running", worker_id, now + LEASE
    job.attempts += 1
    return job


def run_one(database: Database, worker_id: str | None = None) -> str:
    """Claim and execute one job. Returns 'idle', or the job's resulting state."""
    worker_id = worker_id or f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"
    with database.session() as session:
        job = claim(session, worker_id)
        if job is None:
            return "idle"
        job_id = job.id
    with database.session() as session:
        job = session.get(Job, job_id, with_for_update=True)
        if job.state != "running" or job.locked_by != worker_id:
            return "lost_lease"
        handle = HANDLERS.get(job.kind)
        try:
            if handle is None:
                raise PermanentJobError("No handler is registered for this job kind.")
            with session.begin_nested():
                result = handle(JobContext(session=session, job=job))
        except Exception as error:  # noqa: BLE001 - every failure is recorded
            permanent = isinstance(error, PermanentJobError)
            job.last_error = (type(error).__name__ + ": " + str(error))[:500]
            job.locked_by = job.locked_until = None
            if permanent or job.attempts >= job.max_attempts:
                job.state, job.finished_at = "dead", utcnow()
                emit(session, job.workspace_id, "job.dead",
                     {"job_id": str(job.id), "kind": job.kind})
            else:
                job.state, job.run_after = "queued", utcnow() + backoff(job.attempts)
            logger.warning("job %s attempt %s failed", job.id, job.attempts)
            return job.state
        job.state, job.result, job.finished_at = "succeeded", result, utcnow()
        job.locked_by = job.locked_until = None
        emit(session, job.workspace_id, "job.succeeded", {"job_id": str(job.id),
                                                          "kind": job.kind})
        return job.state


Publisher = Callable[[OutboxEvent], None]


def log_publisher(event: OutboxEvent) -> None:
    logger.info("outbox %s %s", event.topic, event.id)


def dispatch_outbox(database: Database, publish: Publisher = log_publisher,
                    batch: int = 50) -> int:
    """Deliver pending outbox events at least once, in creation order."""
    with database.session() as session:
        events = session.scalars(
            select(OutboxEvent).where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at).limit(batch).with_for_update(skip_locked=True)
        ).all()
        delivered = 0
        for event in events:
            event.attempts += 1
            try:
                publish(event)
            except Exception:  # noqa: BLE001 - retried next round
                logger.warning("outbox delivery failed for %s", event.id)
                continue
            event.published_at = utcnow()
            delivered += 1
        return delivered
