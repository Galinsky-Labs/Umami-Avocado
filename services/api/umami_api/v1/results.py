"""Results explorer, run comparisons and science exports (UA-018).

Exports always carry the origin column; SIMULATED and PHYSICAL rows are never merged into
one value, and every export response carries its SHA-256."""
import csv
import hashlib
import io
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import select

from umami_api.errors import invalid, not_found
from umami_api.models import Assay, ExperimentRun, Measurement, QcReport
from umami_api.schemas import (
    Origin,
    RunComparisonOut,
    RunOut,
    RunSeriesOut,
    SeriesPointOut,
)
from umami_api.science.units import QUANTITY_KINDS, Observation, summarize
from umami_api.security import AccessDep
from umami_api.v1.projects import get_project
from umami_api.v1.qc import normalize

router = APIRouter(tags=["results"])
RunIds = Annotated[list[uuid.UUID], Query(min_length=1, max_length=12)]


def _runs(access, project_id, run_ids):
    runs = access.session.scalars(select(ExperimentRun).where(
        ExperimentRun.project_id == project_id, ExperimentRun.id.in_(run_ids))).all()
    if len(runs) != len(set(run_ids)):
        raise not_found("run")
    return sorted(runs, key=lambda r: r.created_at)


def _time(label: str) -> float | None:
    if "t=" not in label:
        return None
    try:
        return float(label.rsplit("t=", 1)[-1].rstrip("h"))
    except ValueError:
        return None


@router.get("/workspaces/{workspace_id}/projects/{project_id}/results/series",
            response_model=list[RunSeriesOut], operation_id="get_result_series")
def series(project_id: uuid.UUID, quantity_kind: str, run_ids: RunIds, access: AccessDep):
    project = get_project(access, project_id)
    kind = QUANTITY_KINDS.get(quantity_kind)
    if kind is None:
        raise invalid("Unknown quantity kind.")
    out = []
    for run in _runs(access, project.id, run_ids):
        rows = access.session.execute(select(Measurement, Assay.unit).join(
            Assay, Assay.id == Measurement.assay_id).where(
            Measurement.run_id == run.id, Assay.quantity_kind == quantity_kind)).all()
        superseded = {m.supersedes_id for m, _ in rows if m.supersedes_id}
        by_time: dict[float, list[Observation]] = {}
        unit = kind.canonical_unit
        for m, assay_unit in rows:
            t = _time(m.sample_label)
            if m.id in superseded or t is None:
                continue
            unit = assay_unit
            by_time.setdefault(t, []).append(
                Observation(m.value_canonical, m.biological_replicate, m.technical_replicate))
        points = []
        for t, observations in sorted(by_time.items()):
            s = summarize(observations)
            points.append(SeriesPointOut(time_h=t, mean=s.mean, sd=s.sd,
                                         n_biological=s.n_biological))
        out.append(RunSeriesOut(run_id=run.id, label=run.label, origin=run.origin, unit=unit,
                                points=points))
    return out


@router.get("/workspaces/{workspace_id}/projects/{project_id}/results/compare",
            response_model=list[RunComparisonOut], operation_id="compare_runs")
def compare(project_id: uuid.UUID, run_ids: RunIds, access: AccessDep):
    project = get_project(access, project_id)
    return [RunComparisonOut(run=RunOut.model_validate(run),
                             normalization=normalize(project.id, run.id, access))
            for run in _runs(access, project.id, run_ids)]


def _export(content: bytes, media_type: str, filename: str, origin: str | None) -> Response:
    return Response(content, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Content-SHA256": hashlib.sha256(content).hexdigest(),
        "X-Result-Origin": origin or "MIXED-LABELLED"})


@router.get("/workspaces/{workspace_id}/projects/{project_id}/exports/measurements.csv",
            operation_id="export_measurements_csv", response_class=Response)
def export_csv(project_id: uuid.UUID, access: AccessDep, origin: Origin | None = None,
               run_id: uuid.UUID | None = None):
    project = get_project(access, project_id)
    query = select(Measurement, Assay).join(Assay, Assay.id == Measurement.assay_id).where(
        Measurement.project_id == project.id)
    if origin:
        query = query.where(Measurement.origin == origin)
    if run_id:
        query = query.where(Measurement.run_id == run_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["measurement_id", "origin", "run_id", "assay_key", "assay_version",
                     "quantity_kind", "sample_label", "biological_replicate",
                     "technical_replicate", "value", "unit", "value_canonical",
                     "canonical_unit", "observed_at", "provenance", "supersedes_id"])
    for m, a in session_rows(access, query):
        writer.writerow([m.id, m.origin, m.run_id or "", a.key, a.version, a.quantity_kind,
                         m.sample_label, m.biological_replicate, m.technical_replicate, m.value,
                         m.unit, m.value_canonical, a.unit, m.observed_at.isoformat(),
                         m.provenance, m.supersedes_id or ""])
    return _export(buffer.getvalue().encode(), "text/csv",
                   f"{project.slug}-measurements.csv", origin)


def session_rows(access, query):
    return access.session.execute(query.order_by(Measurement.observed_at, Measurement.id)
                                  .limit(200_000)).all()


@router.get("/workspaces/{workspace_id}/projects/{project_id}/exports/dataset.json",
            operation_id="export_dataset_json", response_class=Response)
def export_json(project_id: uuid.UUID, access: AccessDep):
    """Self-describing dataset: project, assays, runs, QC reports and measurements."""
    project = get_project(access, project_id)
    s = access.session
    measurements = s.scalars(select(Measurement).where(Measurement.project_id == project.id)
                             .order_by(Measurement.observed_at, Measurement.id)).all()
    assay_ids = {m.assay_id for m in measurements}
    document = {
        "format": "umami-avocado-dataset/1",
        "notice": "Rows labelled SIMULATED are model output, not laboratory measurements.",
        "project": {"id": str(project.id), "name": project.name, "program": project.program},
        "assays": [{"id": str(a.id), "key": a.key, "version": a.version,
                    "quantity_kind": a.quantity_kind, "unit": a.unit, "method": a.method}
                   for a in s.scalars(select(Assay).where(Assay.id.in_(assay_ids)))],
        "runs": [{"id": str(r.id), "label": r.label, "origin": r.origin, "state": r.state,
                  "model_version": r.model_version, "design": r.design, "summary": r.summary}
                 for r in s.scalars(select(ExperimentRun).where(
                     ExperimentRun.project_id == project.id))],
        "qc_reports": [{"id": str(q.id), "assay_id": str(q.assay_id), "origin": q.origin,
                        "status": q.status, "metrics": q.metrics}
                       for q in s.scalars(select(QcReport).where(
                           QcReport.project_id == project.id))],
        "measurements": [{"id": str(m.id), "origin": m.origin, "assay_id": str(m.assay_id),
                          "run_id": str(m.run_id) if m.run_id else None,
                          "sample_label": m.sample_label, "bio": m.biological_replicate,
                          "tech": m.technical_replicate, "value_canonical": m.value_canonical,
                          "observed_at": m.observed_at.isoformat(), "provenance": m.provenance,
                          "supersedes_id": str(m.supersedes_id) if m.supersedes_id else None}
                         for m in measurements],
    }
    content = json.dumps(document, sort_keys=True, indent=1).encode()
    return _export(content, "application/json", f"{project.slug}-dataset.json", None)
