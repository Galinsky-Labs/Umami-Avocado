"""Measurement ontology, assays and immutable, provenance-labelled measurements (UA-005)."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from umami_api.authz import authorize
from umami_api.errors import conflict, invalid, not_found
from umami_api.models import Assay, Measurement
from umami_api.policy import Subject
from umami_api.schemas import (
    AssayIn,
    AssayOut,
    ConvertIn,
    ConvertOut,
    MeasurementIn,
    MeasurementOut,
    OntologyOut,
    Origin,
    QuantityKindOut,
    SampleSummaryOut,
    UnitOut,
)
from umami_api.science.units import (
    DIMENSIONS,
    QUANTITY_KINDS,
    UNITS,
    Observation,
    UnitError,
    check_admissible,
    convert,
    summarize,
)
from umami_api.security import AccessDep
from umami_api.v1.projects import get_project

router = APIRouter(tags=["measurements"])
REPLICATES = ("Technical replicates (repeat measurements of one sample) are averaged first; "
              "mean and sample SD are then computed across biological replicates "
              "(independent cultures). SIMULATED and PHYSICAL results are never pooled.")


@router.get("/ontology", response_model=OntologyOut, operation_id="get_ontology")
def ontology():
    return OntologyOut(
        units=[UnitOut(symbol=u.symbol, name=u.name, convertible=u.convertible,
                       dimension={d: e for d, e in zip(DIMENSIONS, u.dimension, strict=True) if e})
               for u in UNITS.values()],
        quantity_kinds=[QuantityKindOut(key=q.key, label=q.label, canonical_unit=q.canonical_unit,
                                        admissible_units=list(q.admissible_units))
                        for q in QUANTITY_KINDS.values()],
        replicate_semantics=REPLICATES,
    )


@router.post("/ontology/convert", response_model=ConvertOut, operation_id="convert_units")
def convert_units(body: ConvertIn):
    try:
        return ConvertOut(value=convert(body.value, body.from_unit, body.to_unit),
                          unit=body.to_unit)
    except UnitError as error:
        raise invalid(str(error)) from None


@router.get("/workspaces/{workspace_id}/assays", response_model=list[AssayOut],
            operation_id="list_assays")
def list_assays(access: AccessDep):
    return access.session.scalars(select(Assay).where(Assay.workspace_id == access.workspace.id)
                                  .order_by(Assay.key, Assay.version)).all()


@router.post("/workspaces/{workspace_id}/assays", response_model=AssayOut, status_code=201,
             operation_id="define_assay")
def define_assay(body: AssayIn, access: AccessDep):
    """Defining an existing key creates the next version; earlier versions stay referenced."""
    authorize(access, "assay.define")
    try:
        check_admissible(body.quantity_kind, body.unit)
    except UnitError as error:
        raise invalid(str(error)) from None
    latest = access.session.scalar(select(func.max(Assay.version)).where(
        Assay.workspace_id == access.workspace.id, Assay.key == body.key)) or 0
    assay = Assay(workspace_id=access.workspace.id, version=latest + 1,
                  created_by=access.principal.id, **body.model_dump())
    access.session.add(assay)
    access.session.flush()
    return assay


def _assay(access, assay_id: uuid.UUID) -> Assay:
    assay = access.session.scalar(select(Assay).where(
        Assay.id == assay_id, Assay.workspace_id == access.workspace.id))
    if assay is None:
        raise not_found("assay")
    return assay


def record_measurement(access, project_id: uuid.UUID, body: MeasurementIn,
                       run_id: uuid.UUID | None = None) -> Measurement:
    """Shared by the API and the simulator. Authorization depends on origin."""
    project = get_project(access, project_id)
    action = ("measurement.record_physical" if body.origin == "PHYSICAL"
              else "measurement.record_simulated")
    authorize(access, action, Subject(project_id=project.id), ("project", project.id))
    if body.origin == "PHYSICAL" and len(body.provenance.strip()) < 10:
        raise invalid("PHYSICAL measurements require a provenance description.")
    assay = _assay(access, body.assay_id)
    try:
        check_admissible(assay.quantity_kind, body.unit)
        canonical = convert(body.value, body.unit, assay.unit)
    except UnitError as error:
        raise invalid(str(error)) from None
    if body.supersedes_id is not None:
        previous = access.session.get(Measurement, body.supersedes_id)
        if previous is None or previous.project_id != project.id:
            raise not_found("superseded measurement")
        if previous.origin != body.origin or previous.assay_id != assay.id:
            raise conflict("A correction must keep the original origin and assay.")
    measurement = Measurement(
        workspace_id=access.workspace.id, project_id=project.id, run_id=run_id,
        recorded_by=access.principal.id, value_canonical=canonical, **body.model_dump(),
    )
    access.session.add(measurement)
    access.session.flush()
    return measurement


@router.post("/workspaces/{workspace_id}/projects/{project_id}/measurements",
             response_model=MeasurementOut, status_code=201, operation_id="record_measurement")
def create_measurement(project_id: uuid.UUID, body: MeasurementIn, access: AccessDep):
    return record_measurement(access, project_id, body)


@router.get("/workspaces/{workspace_id}/projects/{project_id}/measurements",
            response_model=list[MeasurementOut], operation_id="list_measurements")
def list_measurements(project_id: uuid.UUID, access: AccessDep,
                      origin: Origin | None = None, assay_id: uuid.UUID | None = None,
                      limit: Annotated[int, Query(ge=1, le=1000)] = 200):
    project = get_project(access, project_id)
    query = select(Measurement).where(Measurement.project_id == project.id)
    if origin:
        query = query.where(Measurement.origin == origin)
    if assay_id:
        query = query.where(Measurement.assay_id == assay_id)
    return access.session.scalars(query.order_by(Measurement.observed_at).limit(limit)).all()


@router.get("/workspaces/{workspace_id}/projects/{project_id}/measurements/summary",
            response_model=list[SampleSummaryOut], operation_id="summarize_measurements")
def summary(project_id: uuid.UUID, assay_id: uuid.UUID, origin: Origin, access: AccessDep):
    """Origin is required: summaries never pool SIMULATED with PHYSICAL results.
    Superseded measurements are excluded."""
    project = get_project(access, project_id)
    assay = _assay(access, assay_id)
    rows = access.session.scalars(select(Measurement).where(
        Measurement.project_id == project.id, Measurement.assay_id == assay.id,
        Measurement.origin == origin)).all()
    superseded = {m.supersedes_id for m in rows if m.supersedes_id}
    samples: dict[str, list[Observation]] = {}
    for m in rows:
        if m.id in superseded:
            continue
        samples.setdefault(m.sample_label, []).append(
            Observation(m.value_canonical, m.biological_replicate, m.technical_replicate))
    out = []
    for label, observations in sorted(samples.items()):
        s = summarize(observations)
        out.append(SampleSummaryOut(sample_label=label, origin=origin, unit=assay.unit,
                                    mean=s.mean, sd=s.sd, n_biological=s.n_biological,
                                    n_technical=s.n_technical))
    return out
