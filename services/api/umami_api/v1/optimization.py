"""Bounded optimization and next-experiment selection (UA-020)."""
import uuid
from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from umami_api.authz import authorize
from umami_api.db import utcnow
from umami_api.errors import ApiError, invalid
from umami_api.models import ExperimentRun, OptimizationRound
from umami_api.policy import Subject
from umami_api.schemas import OptimizationIn, OptimizationOut
from umami_api.science.optimization import Observation, suggest
from umami_api.security import AccessDep
from umami_api.v1.projects import get_project
from umami_api.v1.simulator import create_simulated_run

router = APIRouter(tags=["optimization"])
DAILY_SIMULATED_RUN_QUOTA = 24


def objective_value(run: ExperimentRun, objective: str) -> float | None:
    s = run.summary or {}
    if objective == "final_biomass":
        return s.get("biomass_concentration")
    if objective == "final_glutamate":
        return s.get("glutamate_concentration")
    x0 = float(run.design.get("initial_biomass_g_l", 0.1))
    consumed = float(run.design["initial_glucose_g_l"]) - float(s.get("substrate_concentration", 0))
    return (s["biomass_concentration"] - x0) / consumed if consumed > 1e-9 else None


@router.post("/workspaces/{workspace_id}/projects/{project_id}/optimization/rounds",
             response_model=OptimizationOut, status_code=201, operation_id="suggest_next_round")
def suggest_round(project_id: uuid.UUID, body: OptimizationIn, access: AccessDep):
    project = get_project(access, project_id)
    subject = Subject(project_id=project.id)
    authorize(access, "agent.run", subject, ("project", project.id))
    runs = access.session.scalars(select(ExperimentRun).where(
        ExperimentRun.project_id == project.id, ExperimentRun.state == "completed",
        ExperimentRun.origin == body.origin).order_by(ExperimentRun.created_at)).all()
    observations = []
    for run in runs:
        y = objective_value(run, body.objective)
        if y is not None:
            observations.append(Observation({k: float(run.design[k]) for k in
                                             ("temperature_c", "ph", "initial_glucose_g_l")}, y))
    try:
        picks = suggest(observations, body.bounds.model_dump(), body.batch_size)
    except ValueError as error:
        raise invalid(str(error)) from None
    record_id = uuid.uuid4()
    queued: list[str] = []
    if body.queue_simulated_runs:
        authorize(access, "experiment.submit_simulated", subject, ("project", project.id))
        recent = access.session.scalar(select(func.count()).select_from(ExperimentRun).where(
            ExperimentRun.project_id == project.id, ExperimentRun.origin == "SIMULATED",
            ExperimentRun.created_at > utcnow() - timedelta(days=1))) or 0
        if recent + len(picks) > DAILY_SIMULATED_RUN_QUOTA:
            raise ApiError(409, "limit_exceeded",
                           f"Daily simulated-run quota ({DAILY_SIMULATED_RUN_QUOTA}) reached.")
        for i, pick in enumerate(picks):
            design = {**pick.x, "initial_biomass_g_l": 0.1, "duration_h": body.duration_h,
                      "sample_interval_h": 2.0, "biological_replicates": 3,
                      "technical_replicates": 1, "seed": i + 1}
            run = create_simulated_run(
                access, project, design,
                f"opt {pick.x['temperature_c']:g}C pH{pick.x['ph']:g} "
                f"{pick.x['initial_glucose_g_l']:g}g/L",
                idempotency_key=f"opt:{record_id}:{i}")
            queued.append(str(run.id))
    record = OptimizationRound(
        id=record_id, workspace_id=access.workspace.id, project_id=project.id,
        objective=body.objective,
        origin=body.origin, bounds=body.bounds.model_dump(), strategy=picks[0].reason,
        observations=[{"x": o.x, "y": o.y} for o in observations][-200:],
        suggestions=[{"x": p.x, "predicted_mean": p.predicted_mean,
                      "predicted_sd": p.predicted_sd, "acquisition": p.acquisition}
                     for p in picks],
        requested_by=access.principal.id, queued_run_ids=queued)
    access.session.add(record)
    access.session.flush()
    return record


@router.get("/workspaces/{workspace_id}/projects/{project_id}/optimization/rounds",
            response_model=list[OptimizationOut], operation_id="list_optimization_rounds")
def list_rounds(project_id: uuid.UUID, access: AccessDep):
    project = get_project(access, project_id)
    return access.session.scalars(select(OptimizationRound).where(
        OptimizationRound.project_id == project.id)
        .order_by(OptimizationRound.created_at.desc()).limit(50)).all()
