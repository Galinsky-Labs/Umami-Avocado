"""Simulated experiment runs and the digital milestone (UA-010)."""
import uuid

from fastapi import APIRouter
from sqlalchemy import func, select

from umami_api import simulation  # noqa: F401 - registers the simulator job handler
from umami_api.authz import authorize
from umami_api.errors import not_found
from umami_api.models import Claim, ClaimEvidence, ExperimentRun, Job, Measurement
from umami_api.orchestration import enqueue
from umami_api.policy import Subject
from umami_api.schemas import (
    DigitalMilestoneOut,
    MilestoneCheckOut,
    RunOut,
    SimulationDesignIn,
)
from umami_api.science.simulator import MODEL_VERSION
from umami_api.security import AccessDep
from umami_api.v1.jobs import IdempotencyKey
from umami_api.v1.projects import get_project

router = APIRouter(tags=["simulator"])


@router.post("/workspaces/{workspace_id}/projects/{project_id}/simulated-runs",
             response_model=RunOut, status_code=202, operation_id="submit_simulated_run")
def submit(project_id: uuid.UUID, body: SimulationDesignIn, access: AccessDep,
           idempotency_key: IdempotencyKey = None):
    project = get_project(access, project_id)
    authorize(access, "experiment.submit_simulated", Subject(project_id=project.id),
              ("project", project.id))
    if idempotency_key:
        existing = access.session.scalar(select(ExperimentRun).join(
            Job, Job.id == ExperimentRun.job_id).where(
            Job.workspace_id == access.workspace.id, Job.idempotency_key == idempotency_key))
        if existing is not None:
            return existing
    design = body.model_dump()
    label = design.pop("label")
    run = ExperimentRun(workspace_id=access.workspace.id, project_id=project.id,
                        origin="SIMULATED", label=label, model_version=MODEL_VERSION,
                        design=design, created_by=access.principal.id)
    access.session.add(run)
    access.session.flush()
    job, _ = enqueue(access.session, workspace_id=access.workspace.id, kind="simulator.run",
                     payload={"run_id": str(run.id)}, created_by=access.principal.id,
                     project_id=project.id, idempotency_key=idempotency_key)
    run.job_id = job.id
    return run


@router.get("/workspaces/{workspace_id}/projects/{project_id}/runs", response_model=list[RunOut],
            operation_id="list_runs")
def list_runs(project_id: uuid.UUID, access: AccessDep):
    project = get_project(access, project_id)
    return access.session.scalars(select(ExperimentRun).where(
        ExperimentRun.project_id == project.id).order_by(ExperimentRun.created_at.desc())).all()


@router.get("/workspaces/{workspace_id}/projects/{project_id}/runs/{run_id}",
            response_model=RunOut, operation_id="get_run")
def get_run(project_id: uuid.UUID, run_id: uuid.UUID, access: AccessDep):
    project = get_project(access, project_id)
    run = access.session.scalar(select(ExperimentRun).where(
        ExperimentRun.id == run_id, ExperimentRun.project_id == project.id))
    if run is None:
        raise not_found("run")
    return run


@router.get("/workspaces/{workspace_id}/projects/{project_id}/digital-milestone",
            response_model=DigitalMilestoneOut, operation_id="get_digital_milestone")
def milestone(project_id: uuid.UUID, access: AccessDep):
    """The digital loop: design → durable job → simulated measurements → evidence-linked claim
    under human review. Achieving it says nothing about physical science."""
    project = get_project(access, project_id)
    session = access.session
    completed = session.scalar(select(func.count()).select_from(ExperimentRun).where(
        ExperimentRun.project_id == project.id, ExperimentRun.state == "completed")) or 0
    simulated = session.scalar(select(func.count()).select_from(Measurement).where(
        Measurement.project_id == project.id, Measurement.origin == "SIMULATED",
        Measurement.run_id.is_not(None))) or 0
    linked = session.scalar(select(func.count()).select_from(ClaimEvidence).join(
        Claim, Claim.id == ClaimEvidence.claim_id).join(
        Measurement, Measurement.id == ClaimEvidence.measurement_id).where(
        Claim.project_id == project.id, Measurement.run_id.is_not(None))) or 0
    submitted = session.scalar(select(func.count()).select_from(Claim).where(
        Claim.project_id == project.id, Claim.status != "draft",
        Claim.id.in_(select(ClaimEvidence.claim_id).join(
            Measurement, Measurement.id == ClaimEvidence.measurement_id)
            .where(Measurement.run_id.is_not(None))))) or 0
    physical = session.scalar(select(func.count()).select_from(Measurement).where(
        Measurement.project_id == project.id, Measurement.origin == "PHYSICAL")) or 0
    checks = [
        MilestoneCheckOut(key="simulated_run_completed", met=completed > 0,
                          description="A simulated experiment completed through a durable job."),
        MilestoneCheckOut(key="simulated_measurements_recorded", met=simulated > 0,
                          description="Run output stored as immutable SIMULATED measurements."),
        MilestoneCheckOut(key="claim_linked_to_simulation", met=linked > 0,
                          description="A claim cites simulated run measurements as evidence."),
        MilestoneCheckOut(key="claim_submitted_for_human_review", met=submitted > 0,
                          description="That claim entered human review."),
    ]
    return DigitalMilestoneOut(
        project_id=project.id, achieved=all(c.met for c in checks), checks=checks,
        physical_results_exist=physical > 0,
        note="Digital milestone only: simulated output cannot establish a scientific claim.")
