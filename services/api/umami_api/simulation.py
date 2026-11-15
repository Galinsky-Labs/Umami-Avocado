"""Simulator job handler: turns a queued SIMULATED run into labelled measurements (UA-010)."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from umami_api.db import utcnow
from umami_api.models import Assay, ExperimentRun, Measurement
from umami_api.orchestration import JobContext, PermanentJobError, handler
from umami_api.science.simulator import MODEL_VERSION, Design, simulate, summarize_final

SIMULATED_ASSAYS = {
    "biomass_concentration": ("sim-dcw", "Simulated dry cell weight"),
    "substrate_concentration": ("sim-glucose", "Simulated residual glucose"),
    "glutamate_concentration": ("sim-glutamate", "Simulated free glutamate"),
}
METHOD = (f"Deterministic simulator {MODEL_VERSION}. SIMULATED output of a Monod batch model; "
          "not a laboratory measurement.")


def simulator_assays(session: Session, workspace_id, created_by) -> dict[str, Assay]:
    assays = {}
    for quantity, (key, name) in SIMULATED_ASSAYS.items():
        assay = session.scalar(select(Assay).where(Assay.workspace_id == workspace_id,
                                                   Assay.key == key, Assay.version == 1))
        if assay is None:
            assay = Assay(workspace_id=workspace_id, key=key, version=1, name=name,
                          quantity_kind=quantity, unit="g/L", method=METHOD,
                          created_by=created_by)
            session.add(assay)
            session.flush()
        assays[quantity] = assay
    return assays


@handler("simulator.run")
def run_simulation(context: JobContext) -> dict:
    session, job = context.session, context.job
    run = session.get(ExperimentRun, job.payload["run_id"], with_for_update=True)
    if run is None or run.origin != "SIMULATED":
        raise PermanentJobError("Only SIMULATED runs can be executed by the simulator.")
    if run.state == "completed":  # idempotent on redelivery
        return {"run_id": str(run.id), "measurements": 0, "already_completed": True}
    if run.state == "cancelled":
        return {"run_id": str(run.id), "cancelled": True}
    run.state, run.started_at = "running", utcnow()
    design = Design(**{k: v for k, v in run.design.items() if k != "label"})
    samples = simulate(design)
    assays = simulator_assays(session, run.workspace_id, run.created_by)
    start = run.created_at
    for sample in samples:
        assay = assays[sample.quantity]
        session.add(Measurement(
            workspace_id=run.workspace_id, project_id=run.project_id, assay_id=assay.id,
            origin="SIMULATED", sample_label=f"{run.label} t={sample.time_h:g}h",
            biological_replicate=sample.biological_replicate,
            technical_replicate=sample.technical_replicate, value=sample.value,
            unit=sample.unit, value_canonical=sample.value,
            observed_at=start + timedelta(hours=sample.time_h), run_id=run.id,
            provenance=f"simulator:{MODEL_VERSION}:seed={design.seed}",
            recorded_by=run.created_by))
    run.summary = {**summarize_final(samples), "samples": len(samples), "origin": "SIMULATED"}
    run.state, run.completed_at = "completed", utcnow()
    context.emit("run.completed", {"run_id": str(run.id), "origin": "SIMULATED"})
    return {"run_id": str(run.id), "measurements": len(samples)}
