"""Artifact creation and CSV result ingestion shared by API routes and adapters."""
import csv
import io
import uuid
from datetime import timedelta

from sqlalchemy import select

from umami_api.db import utcnow
from umami_api.errors import conflict, invalid, not_found
from umami_api.models import Artifact, ArtifactIngestion, Assay, Measurement
from umami_api.science.units import UnitError, check_admissible, convert
from umami_api.storage import get_store

MEDIA_TYPES = {"text/csv", "application/json", "text/plain", "application/pdf", "image/png",
               "image/jpeg", "application/octet-stream"}
REQUIRED_COLUMNS = {"quantity", "unit", "time_h", "biological_replicate", "value"}


def create_artifact(access, *, project_id: uuid.UUID, name: str, media_type: str, content: bytes,
                    origin: str, source: str, provenance: dict, run_id: uuid.UUID | None = None,
                    material_id: uuid.UUID | None = None) -> Artifact:
    if media_type not in MEDIA_TYPES:
        raise invalid("Unsupported artifact media type.")
    if not content:
        raise invalid("Artifacts cannot be empty.")
    store = get_store(access.caller.settings.artifact_store)
    sha = store.put(access.session, content)
    artifact = Artifact(workspace_id=access.workspace.id, project_id=project_id, run_id=run_id,
                        material_id=material_id, name=name, media_type=media_type,
                        size=len(content), sha256=sha, store=store.name, origin=origin,
                        source=source, created_by=access.principal.id,
                        provenance={**provenance, "received_at": utcnow().isoformat(),
                                    "recorded_by": str(access.principal.id),
                                    "recorded_by_kind": access.principal.kind})
    access.session.add(artifact)
    access.session.flush()
    return artifact


def read_content(access, artifact: Artifact) -> bytes:
    return get_store(artifact.store).get(access.session, artifact.sha256)


def ingest_csv(access, artifact: Artifact, assay_map: dict[str, uuid.UUID],
               sample_prefix: str = "") -> ArtifactIngestion:
    """Parse a results CSV into immutable measurements carrying the artifact's origin.

    Columns: quantity, unit, time_h, biological_replicate, [technical_replicate], value,
    [origin]. A row whose origin column disagrees with the artifact is rejected: labels in
    files can never relabel provenance."""
    if access.session.scalar(select(ArtifactIngestion.id).where(
            ArtifactIngestion.artifact_id == artifact.id)):
        raise conflict("This artifact has already been ingested.")
    if artifact.media_type != "text/csv":
        raise invalid("Only text/csv artifacts can be ingested.")
    assays = {}
    for quantity, assay_id in assay_map.items():
        assay = access.session.scalar(select(Assay).where(
            Assay.id == assay_id, Assay.workspace_id == access.workspace.id))
        if assay is None:
            raise not_found("assay")
        assays[quantity] = assay
    try:
        reader = csv.DictReader(io.StringIO(read_content(access, artifact).decode("utf-8")))
        if not REQUIRED_COLUMNS <= set(reader.fieldnames or []):
            raise invalid("CSV must include quantity, unit, time_h, biological_replicate, value.")
        rows = list(reader)
    except UnicodeDecodeError:
        raise invalid("CSV must be UTF-8.") from None
    if len(rows) > 20000:
        raise invalid("CSV exceeds 20,000 rows.")
    start = artifact.created_at
    count = 0
    for number, row in enumerate(rows, start=2):
        if row.get("origin") and row["origin"] != artifact.origin:
            raise conflict(f"Row {number} origin differs from the artifact's origin.")
        assay = assays.get(row["quantity"])
        if assay is None:
            continue
        try:
            value = float(row["value"])
            time_h = float(row["time_h"])
            bio = int(row["biological_replicate"])
            tech = int(row.get("technical_replicate") or 1)
            check_admissible(assay.quantity_kind, row["unit"])
            canonical = convert(value, row["unit"], assay.unit)
        except (ValueError, UnitError):
            raise invalid(f"Row {number} has an invalid value, unit or replicate.") from None
        if bio < 1 or tech < 1:
            raise invalid(f"Row {number} has an invalid replicate index.")
        access.session.add(Measurement(
            workspace_id=access.workspace.id, project_id=artifact.project_id, assay_id=assay.id,
            origin=artifact.origin, sample_label=f"{sample_prefix}t={time_h:g}h",
            biological_replicate=bio, technical_replicate=tech, value=value, unit=row["unit"],
            value_canonical=canonical, observed_at=start + timedelta(hours=time_h),
            run_id=artifact.run_id, provenance=f"artifact:{artifact.id}:row={number}",
            recorded_by=access.principal.id))
        count += 1
    if count == 0:
        raise invalid("No rows matched the assay map.")
    ingestion = ArtifactIngestion(workspace_id=access.workspace.id, artifact_id=artifact.id,
                                  parser="results-csv-v1",
                                  assay_map={k: str(v) for k, v in assay_map.items()},
                                  measurement_count=count, ingested_by=access.principal.id)
    access.session.add(ingestion)
    access.session.flush()
    return ingestion
