"""Run timelines and the workspace exception center (UA-017)."""
import uuid

from fastapi import APIRouter
from sqlalchemy import select

from umami_api.errors import not_found
from umami_api.models import (
    Artifact,
    EvidenceSource,
    ExperimentProposal,
    ExperimentRun,
    Job,
    OutboxEvent,
    QcDisposition,
    QcReport,
    WorkOrder,
)
from umami_api.schemas import ExceptionOut, RunOut, RunTimelineOut, TimelineEventOut
from umami_api.security import AccessDep
from umami_api.v1.projects import get_project

router = APIRouter(tags=["operations"])


@router.get("/workspaces/{workspace_id}/projects/{project_id}/runs/{run_id}/timeline",
            response_model=RunTimelineOut, operation_id="get_run_timeline")
def timeline(project_id: uuid.UUID, run_id: uuid.UUID, access: AccessDep):
    project = get_project(access, project_id)
    run = access.session.scalar(select(ExperimentRun).where(
        ExperimentRun.id == run_id, ExperimentRun.project_id == project.id))
    if run is None:
        raise not_found("run")
    events = [TimelineEventOut(at=run.created_at, kind="run.created",
                               title=f"{run.origin} run queued", ref=str(run.id))]
    if run.started_at:
        events.append(TimelineEventOut(at=run.started_at, kind="run.started", title="Run started"))
    if run.job_id:
        job = access.session.get(Job, run.job_id)
        if job is not None:
            if job.attempts > 1 or job.last_error:
                events.append(TimelineEventOut(
                    at=job.finished_at or job.run_after, kind="job.retry",
                    title=f"Job attempts: {job.attempts}", detail=job.last_error or "",
                    severity="error" if job.state == "dead" else "warning", ref=str(job.id)))
            for event in access.session.scalars(select(OutboxEvent).where(
                    OutboxEvent.workspace_id == access.workspace.id,
                    OutboxEvent.payload["job_id"].as_string() == str(job.id))):
                events.append(TimelineEventOut(at=event.created_at, kind=event.topic,
                                               title=event.topic.replace(".", " "),
                                               ref=str(event.id)))
    for artifact in access.session.scalars(select(Artifact).where(Artifact.run_id == run.id)):
        events.append(TimelineEventOut(at=artifact.created_at, kind="artifact",
                                       title=f"Artifact {artifact.name}",
                                       detail=artifact.sha256, ref=str(artifact.id)))
    for report in access.session.scalars(select(QcReport).where(QcReport.run_id == run.id)):
        events.append(TimelineEventOut(
            at=report.created_at, kind="qc", title=f"QC {report.status}",
            severity={"pass": "info", "warn": "warning", "fail": "error"}[report.status],
            ref=str(report.id)))
    if run.completed_at:
        events.append(TimelineEventOut(at=run.completed_at, kind="run.completed",
                                       title="Run completed"))
    return RunTimelineOut(run=RunOut.model_validate(run),
                          events=sorted(events, key=lambda e: e.at))


@router.get("/workspaces/{workspace_id}/exceptions", response_model=list[ExceptionOut],
            operation_id="list_exceptions")
def exceptions(access: AccessDep):
    """Everything in the workspace that needs a human: failures, unreviewed QC, blocked
    proposals, work orders awaiting approval and unverified agent-added sources."""
    ws = access.workspace.id
    s = access.session
    out: list[ExceptionOut] = []
    for job in s.scalars(select(Job).where(Job.workspace_id == ws, Job.state == "dead")
                         .limit(100)):
        out.append(ExceptionOut(kind="job.dead", severity="error", title=f"Job {job.kind} failed",
                                detail=job.last_error or "", project_id=job.project_id,
                                ref=str(job.id), at=job.finished_at or job.created_at))
    for run in s.scalars(select(ExperimentRun).where(ExperimentRun.workspace_id == ws,
                                                     ExperimentRun.state == "failed").limit(100)):
        out.append(ExceptionOut(kind="run.failed", severity="error", title=f"Run {run.label}",
                                detail="", project_id=run.project_id, ref=str(run.id),
                                at=run.created_at))
    decided = select(QcDisposition.report_id)
    for report in s.scalars(select(QcReport).where(
            QcReport.workspace_id == ws, QcReport.status != "pass",
            QcReport.id.not_in(decided)).limit(100)):
        out.append(ExceptionOut(kind="qc.unreviewed", severity="error" if report.status == "fail"
                                else "warning", title=f"QC {report.status} awaiting review",
                                detail=f"{report.metrics.get('errors', 0)} errors, "
                                f"{report.metrics.get('warnings', 0)} warnings",
                                project_id=report.project_id, ref=str(report.id),
                                at=report.created_at))
    for proposal in s.scalars(select(ExperimentProposal).where(
            ExperimentProposal.workspace_id == ws,
            ExperimentProposal.state == "preflight_failed").limit(100)):
        failing = [c["key"] for c in (proposal.preflight or {}).get("checks", [])
                   if not c["passed"] and c["severity"] == "blocker"]
        out.append(ExceptionOut(kind="proposal.blocked", severity="warning",
                                title=f"Proposal '{proposal.title}' blocked",
                                detail=", ".join(failing), project_id=proposal.project_id,
                                ref=str(proposal.id), at=proposal.updated_at))
    for order in s.scalars(select(WorkOrder).where(WorkOrder.workspace_id == ws,
                                                   WorkOrder.state == "draft").limit(100)):
        out.append(ExceptionOut(kind="work_order.awaiting_approval", severity="warning",
                                title=f"Work order '{order.title}' awaiting approval",
                                detail="Dispatch stays disabled even after approval.",
                                project_id=order.project_id, ref=str(order.id),
                                at=order.created_at))
    for source in s.scalars(select(EvidenceSource).where(
            EvidenceSource.workspace_id == ws, EvidenceSource.added_by_kind == "agent",
            EvidenceSource.verified_at.is_(None)).limit(100)):
        out.append(ExceptionOut(kind="source.unverified", severity="warning",
                                title="Agent-added source needs verification",
                                detail=source.citation[:200], project_id=None,
                                ref=str(source.id), at=source.created_at))
    return sorted(out, key=lambda e: (e.severity != "error", e.at), reverse=False)
