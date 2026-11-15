"""QC reports, human QC disposition, run normalization and reproducibility (UA-016)."""
import hashlib
import json
import math
import uuid
from itertools import pairwise

from fastapi import APIRouter
from sqlalchemy import select

from umami_api.authz import authorize
from umami_api.errors import conflict, not_found
from umami_api.models import Assay, ExperimentRun, Measurement, QcDisposition, QcReport
from umami_api.policy import Subject
from umami_api.schemas import (
    Origin,
    QcDispositionIn,
    QcDispositionOut,
    QcReportOut,
    QcRequestIn,
    ReproducibilityOut,
    RunNormalizationOut,
)
from umami_api.science.qc import Point, biomass_yield, evaluate, reproducibility
from umami_api.security import AccessDep, WorkspaceAccess
from umami_api.v1.projects import get_project

router = APIRouter(tags=["qc"])


def _out(access: WorkspaceAccess, report: QcReport) -> QcReportOut:
    disposition = access.session.scalar(select(QcDisposition).where(
        QcDisposition.report_id == report.id))
    out = QcReportOut.model_validate(report)
    out.disposition = QcDispositionOut.model_validate(disposition) if disposition else None
    return out


def _superseded(rows) -> set:
    return {m.supersedes_id for m in rows if m.supersedes_id}


@router.post("/workspaces/{workspace_id}/projects/{project_id}/qc-reports",
             response_model=QcReportOut, status_code=201, operation_id="generate_qc_report")
def generate(project_id: uuid.UUID, body: QcRequestIn, access: AccessDep):
    project = get_project(access, project_id)
    authorize(access, "experiment.draft", Subject(project_id=project.id), ("project", project.id))
    assay = access.session.scalar(select(Assay).where(
        Assay.id == body.assay_id, Assay.workspace_id == access.workspace.id))
    if assay is None:
        raise not_found("assay")
    query = select(Measurement).where(Measurement.project_id == project.id,
                                      Measurement.assay_id == assay.id,
                                      Measurement.origin == body.origin)
    if body.run_id:
        query = query.where(Measurement.run_id == body.run_id)
    rows = access.session.scalars(query.order_by(Measurement.id)).all()
    dropped = _superseded(rows)
    rows = [m for m in rows if m.id not in dropped]
    if not rows:
        raise conflict("No measurements match this assay, origin and run.")
    result = evaluate([Point(str(m.id), m.sample_label, m.biological_replicate,
                             m.technical_replicate, m.value_canonical) for m in rows],
                      assay.quantity_kind)
    report = QcReport(workspace_id=access.workspace.id, project_id=project.id,
                      run_id=body.run_id, assay_id=assay.id, origin=body.origin,
                      status=result["status"], metrics=result["metrics"], flags=result["flags"],
                      measurement_ids_sha256=hashlib.sha256(
                          ",".join(str(m.id) for m in rows).encode()).hexdigest(),
                      generated_by=access.principal.id)
    access.session.add(report)
    access.session.flush()
    return _out(access, report)


@router.get("/workspaces/{workspace_id}/projects/{project_id}/qc-reports",
            response_model=list[QcReportOut], operation_id="list_qc_reports")
def list_reports(project_id: uuid.UUID, access: AccessDep):
    project = get_project(access, project_id)
    reports = access.session.scalars(select(QcReport).where(QcReport.project_id == project.id)
                                     .order_by(QcReport.created_at.desc()).limit(200)).all()
    return [_out(access, r) for r in reports]


@router.post("/workspaces/{workspace_id}/projects/{project_id}/qc-reports/{report_id}/disposition",
             response_model=QcReportOut, operation_id="disposition_qc_report")
def disposition(project_id: uuid.UUID, report_id: uuid.UUID, body: QcDispositionIn,
                access: AccessDep):
    project = get_project(access, project_id)
    report = access.session.scalar(select(QcReport).where(
        QcReport.id == report_id, QcReport.project_id == project.id).with_for_update())
    if report is None:
        raise not_found("QC report")
    authorize(access, "qc.review", Subject(project_id=project.id, author_id=report.generated_by),
              ("qc_report", report.id))
    if access.session.scalar(select(QcDisposition.id).where(QcDisposition.report_id == report.id)):
        raise conflict("This QC report already has a disposition.")
    if body.decision == "accepted" and report.status == "fail":
        raise conflict("Reports with errors cannot be accepted; correct the data first.")
    access.session.add(QcDisposition(workspace_id=access.workspace.id, report_id=report.id,
                                     decision=body.decision, rationale=body.rationale,
                                     decided_by=access.principal.id))
    access.session.flush()
    return _out(access, report)


def _series(access, run_id, kind):
    rows = access.session.execute(select(Measurement, Assay.quantity_kind).join(
        Assay, Assay.id == Measurement.assay_id).where(
        Measurement.run_id == run_id, Assay.quantity_kind == kind)).all()
    dropped = _superseded([m for m, _ in rows])
    by_time: dict[float, list[float]] = {}
    for m, _ in rows:
        if m.id in dropped:
            continue
        t = float(m.sample_label.rsplit("t=", 1)[-1].rstrip("h")) \
            if "t=" in m.sample_label else None
        if t is not None:
            by_time.setdefault(t, []).append(m.value_canonical)
    return {t: sum(v) / len(v) for t, v in sorted(by_time.items())}


@router.get("/workspaces/{workspace_id}/projects/{project_id}/runs/{run_id}/normalization",
            response_model=RunNormalizationOut, operation_id="normalize_run")
def normalize(project_id: uuid.UUID, run_id: uuid.UUID, access: AccessDep):
    """Endpoint values, apparent biomass yield and maximum specific growth rate."""
    project = get_project(access, project_id)
    run = access.session.scalar(select(ExperimentRun).where(
        ExperimentRun.id == run_id, ExperimentRun.project_id == project.id))
    if run is None:
        raise not_found("run")
    x = _series(access, run.id, "biomass_concentration")
    s = _series(access, run.id, "substrate_concentration")
    times = sorted(x)
    mu = None
    for a, b in pairwise(times):
        if x[a] > 0 and x[b] > 0 and b > a:
            rate = math.log(x[b] / x[a]) / (b - a)
            mu = rate if mu is None else max(mu, rate)
    x0, xf = (x[times[0]], x[times[-1]]) if times else (None, None)
    st = sorted(s)
    s0, sf = (s[st[0]], s[st[-1]]) if st else (None, None)
    y = biomass_yield(x0, xf, s0, sf) if None not in (x0, xf, s0, sf) else None
    return RunNormalizationOut(
        run_id=run.id, origin=run.origin, final_time_h=times[-1] if times else None,
        biomass_initial_g_l=x0, biomass_final_g_l=xf, substrate_initial_g_l=s0,
        substrate_final_g_l=sf, biomass_yield_g_g=round(y, 6) if y is not None else None,
        specific_growth_rate_per_h=round(mu, 6) if mu is not None else None)


@router.get("/workspaces/{workspace_id}/projects/{project_id}/reproducibility",
            response_model=list[ReproducibilityOut], operation_id="get_reproducibility")
def reproducibility_report(project_id: uuid.UUID, access: AccessDep, origin: Origin = "SIMULATED"):
    """Groups completed runs by design (ignoring seed and label) and compares final biomass."""
    project = get_project(access, project_id)
    runs = access.session.scalars(select(ExperimentRun).where(
        ExperimentRun.project_id == project.id, ExperimentRun.state == "completed",
        ExperimentRun.origin == origin)).all()
    groups: dict[str, list[float]] = {}
    for run in runs:
        if not run.summary:
            continue
        design = {k: v for k, v in run.design.items() if k not in ("seed", "label")}
        key = hashlib.sha256(json.dumps(design, sort_keys=True).encode()).hexdigest()[:16]
        groups.setdefault(key, []).append(float(run.summary["biomass_concentration"]))
    return [ReproducibilityOut(protocol_fingerprint=k, origin=origin, **reproducibility(v))
            for k, v in sorted(groups.items())]
