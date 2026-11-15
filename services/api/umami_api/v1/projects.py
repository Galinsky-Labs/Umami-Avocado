"""Workspace-scoped research projects (portfolio)."""
import uuid

from fastapi import APIRouter
from sqlalchemy import select

from umami_api.db import utcnow
from umami_api.errors import conflict, not_found
from umami_api.models import Project
from umami_api.schemas import ProjectIn, ProjectOut, ProjectPatch
from umami_api.security import AccessDep, WorkspaceAccess
from umami_api.v1.identity import require_role

router = APIRouter(tags=["projects"])
WRITER_ROLES = ("owner", "admin", "scientist")


def get_project(access: WorkspaceAccess, project_id: uuid.UUID) -> Project:
    project = access.session.scalar(
        select(Project).where(Project.id == project_id,
                              Project.workspace_id == access.workspace.id)
    )
    if project is None:
        raise not_found("project")
    return project


@router.get("/workspaces/{workspace_id}/projects", response_model=list[ProjectOut],
            operation_id="list_projects")
def list_projects(access: AccessDep):
    return access.session.scalars(
        select(Project).where(Project.workspace_id == access.workspace.id)
        .order_by(Project.created_at)
    ).all()


@router.post("/workspaces/{workspace_id}/projects", response_model=ProjectOut, status_code=201,
             operation_id="create_project")
def create_project(body: ProjectIn, access: AccessDep):
    require_role(access, WRITER_ROLES)
    exists = access.session.scalar(select(Project.id).where(
        Project.workspace_id == access.workspace.id, Project.slug == body.slug))
    if exists:
        raise conflict("A project with this slug already exists in the workspace.")
    project = Project(workspace_id=access.workspace.id, created_by=access.principal.id,
                      **body.model_dump())
    access.session.add(project)
    access.session.flush()
    return project


@router.get("/workspaces/{workspace_id}/projects/{project_id}", response_model=ProjectOut,
            operation_id="get_project")
def read_project(project_id: uuid.UUID, access: AccessDep):
    return get_project(access, project_id)


@router.patch("/workspaces/{workspace_id}/projects/{project_id}", response_model=ProjectOut,
              operation_id="update_project")
def update_project(project_id: uuid.UUID, body: ProjectPatch,
                   access: AccessDep):
    require_role(access, WRITER_ROLES)
    project = get_project(access, project_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(project, key, value)
    project.updated_at = utcnow()
    return project
