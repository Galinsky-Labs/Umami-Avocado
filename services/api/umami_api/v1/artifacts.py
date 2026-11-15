"""Immutable artifact upload, download, provenance and ingestion (UA-015)."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import select

from umami_api.artifacts import create_artifact, ingest_csv, read_content
from umami_api.authz import authorize
from umami_api.errors import ApiError, invalid, not_found
from umami_api.models import Artifact, ExperimentRun, Material
from umami_api.policy import Subject
from umami_api.schemas import ArtifactOut, IngestIn, IngestionOut, Origin
from umami_api.security import AccessDep, WorkspaceAccess
from umami_api.storage import IntegrityFailure
from umami_api.v1.projects import get_project

router = APIRouter(tags=["artifacts"])


def get_artifact(access: WorkspaceAccess, project_id: uuid.UUID,
                 artifact_id: uuid.UUID) -> Artifact:
    artifact = access.session.scalar(select(Artifact).where(
        Artifact.id == artifact_id, Artifact.project_id == project_id,
        Artifact.workspace_id == access.workspace.id))
    if artifact is None:
        raise not_found("artifact")
    return artifact


@router.post("/workspaces/{workspace_id}/projects/{project_id}/artifacts",
             response_model=ArtifactOut, status_code=201, operation_id="upload_artifact")
async def upload(project_id: uuid.UUID, request: Request, access: AccessDep,
                 name: Annotated[str, Query(min_length=1, max_length=200,
                                            pattern=r"^[\w .()-]+$")],
                 origin: Origin, description: Annotated[str, Query(max_length=1000)] = "",
                 run_id: uuid.UUID | None = None, material_id: uuid.UUID | None = None):
    """Raw request body is the file; Content-Type is its media type (max 10 MB)."""
    project = get_project(access, project_id)
    authorize(access, "artifact.upload", Subject(project_id=project.id), ("project", project.id))
    if origin == "PHYSICAL":
        authorize(access, "measurement.record_physical", Subject(project_id=project.id))
        if len(description.strip()) < 10:
            raise invalid("PHYSICAL artifacts need a description of where they came from.")
    if run_id is not None:
        run = access.session.get(ExperimentRun, run_id)
        if run is None or run.project_id != project.id:
            raise not_found("run")
        if run.origin != origin:
            raise ApiError(409, "conflict", "Artifact origin must match the run's origin.")
    if material_id is not None:
        material = access.session.get(Material, material_id)
        if material is None or material.workspace_id != access.workspace.id:
            raise not_found("material")
        if material.origin != origin:
            raise ApiError(409, "conflict", "Artifact origin must match the material's origin.")
    content = await request.body()
    media_type = request.headers.get("content-type", "application/octet-stream").split(";")[0]
    return create_artifact(access, project_id=project.id, name=name, media_type=media_type,
                           content=content, origin=origin, source="upload",
                           provenance={"description": description}, run_id=run_id,
                           material_id=material_id)


@router.get("/workspaces/{workspace_id}/projects/{project_id}/artifacts",
            response_model=list[ArtifactOut], operation_id="list_artifacts")
def list_artifacts(project_id: uuid.UUID, access: AccessDep, run_id: uuid.UUID | None = None):
    project = get_project(access, project_id)
    query = select(Artifact).where(Artifact.project_id == project.id)
    if run_id:
        query = query.where(Artifact.run_id == run_id)
    return access.session.scalars(query.order_by(Artifact.created_at.desc()).limit(500)).all()


@router.get("/workspaces/{workspace_id}/projects/{project_id}/artifacts/{artifact_id}",
            response_model=ArtifactOut, operation_id="get_artifact")
def artifact_metadata(project_id: uuid.UUID, artifact_id: uuid.UUID, access: AccessDep):
    return get_artifact(access, get_project(access, project_id).id, artifact_id)


@router.get("/workspaces/{workspace_id}/projects/{project_id}/artifacts/{artifact_id}/content",
            operation_id="download_artifact", response_class=Response)
def download(project_id: uuid.UUID, artifact_id: uuid.UUID, access: AccessDep):
    artifact = get_artifact(access, get_project(access, project_id).id, artifact_id)
    try:
        content = read_content(access, artifact)
    except IntegrityFailure:
        raise ApiError(500, "internal_error", "Artifact integrity verification failed.") from None
    return Response(content, media_type=artifact.media_type, headers={
        "Content-Disposition": f'attachment; filename="{artifact.id}"',
        "X-Content-SHA256": artifact.sha256, "X-Result-Origin": artifact.origin})


@router.post("/workspaces/{workspace_id}/projects/{project_id}/artifacts/{artifact_id}/ingest",
             response_model=IngestionOut, status_code=201, operation_id="ingest_artifact")
def ingest(project_id: uuid.UUID, artifact_id: uuid.UUID, body: IngestIn, access: AccessDep):
    project = get_project(access, project_id)
    artifact = get_artifact(access, project.id, artifact_id)
    action = ("measurement.record_physical" if artifact.origin == "PHYSICAL"
              else "measurement.record_simulated")
    authorize(access, action, Subject(project_id=project.id), ("artifact", artifact.id))
    return ingest_csv(access, artifact, body.assay_map, body.sample_prefix)
