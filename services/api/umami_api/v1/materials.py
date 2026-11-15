"""Biological-material and sample lineage / custody graph (UA-012)."""
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from umami_api.authz import authorize
from umami_api.errors import ApiError, conflict, invalid, not_found
from umami_api.models import CustodyEvent, LineageEdge, Material
from umami_api.policy import Subject
from umami_api.schemas import (
    CustodyIn,
    CustodyOut,
    DeriveIn,
    LineageEdgeOut,
    LineageOut,
    MaterialIn,
    MaterialOut,
)
from umami_api.security import AccessDep, WorkspaceAccess
from umami_api.v1.projects import get_project

router = APIRouter(tags=["materials"])
MAX_DEPTH = 25


def _material(access: WorkspaceAccess, material_id: uuid.UUID, lock: bool = False) -> Material:
    query = select(Material).where(Material.id == material_id,
                                   Material.workspace_id == access.workspace.id)
    material = access.session.scalar(query.with_for_update() if lock else query)
    if material is None:
        raise not_found("material")
    return material


def register_material(access: WorkspaceAccess, body: MaterialIn,
                      run_id: uuid.UUID | None = None) -> Material:
    if body.project_id is not None:
        get_project(access, body.project_id)
    authorize(access, "material.register", Subject(project_id=body.project_id))
    if access.principal.kind == "agent" and body.origin != "SIMULATED":
        raise ApiError(403, "policy_denied", "Agents may only register SIMULATED materials.")
    if len(json.dumps(body.attributes)) > 8000:
        raise invalid("Material attributes are limited to 8 kB.")
    material = Material(workspace_id=access.workspace.id, created_by=access.principal.id,
                        run_id=run_id, **body.model_dump())
    access.session.add(material)
    try:
        with access.session.begin_nested():
            access.session.flush()
    except IntegrityError as error:
        raise conflict("A material with this label already exists.") from error
    access.session.add(CustodyEvent(workspace_id=access.workspace.id, material_id=material.id,
                                    event="registered", to_party=body.custodian,
                                    location=body.location, recorded_by=access.principal.id))
    return material


@router.get("/workspaces/{workspace_id}/materials", response_model=list[MaterialOut],
            operation_id="list_materials")
def list_materials(access: AccessDep, project_id: uuid.UUID | None = None,
                   limit: Annotated[int, Query(ge=1, le=500)] = 200):
    query = select(Material).where(Material.workspace_id == access.workspace.id)
    if project_id:
        query = query.where(Material.project_id == project_id)
    return access.session.scalars(query.order_by(Material.created_at.desc()).limit(limit)).all()


@router.post("/workspaces/{workspace_id}/materials", response_model=MaterialOut,
             status_code=201, operation_id="register_material")
def create_material(body: MaterialIn, access: AccessDep):
    return register_material(access, body)


@router.post("/workspaces/{workspace_id}/materials/derive", response_model=MaterialOut,
             status_code=201, operation_id="derive_material")
def derive(body: DeriveIn, access: AccessDep):
    """Create a child material from one or more parents. Origins can never mix:
    a SIMULATED parent cannot yield PHYSICAL material or vice versa."""
    parents = [_material(access, pid) for pid in dict.fromkeys(body.parent_ids)]
    if any(p.origin != body.child.origin for p in parents):
        raise conflict("Parent and child materials must share the same origin.")
    if any(p.status != "active" for p in parents):
        raise conflict("Only active materials can be derived from.")
    child = register_material(access, body.child)
    for parent in parents:
        access.session.add(LineageEdge(workspace_id=access.workspace.id, parent_id=parent.id,
                                       child_id=child.id, relation=body.relation,
                                       recorded_by=access.principal.id))
    access.session.flush()
    return child


def _walk(access: WorkspaceAccess, root: uuid.UUID) -> tuple[set[uuid.UUID], list[LineageEdge]]:
    seen, frontier, edges = {root}, {root}, {}
    for _ in range(MAX_DEPTH):
        if not frontier:
            break
        rows = access.session.scalars(select(LineageEdge).where(
            LineageEdge.workspace_id == access.workspace.id,
            or_(LineageEdge.parent_id.in_(frontier), LineageEdge.child_id.in_(frontier)))).all()
        nxt = set()
        for edge in rows:
            edges[edge.id] = edge
            for node in (edge.parent_id, edge.child_id):
                if node not in seen:
                    seen.add(node)
                    nxt.add(node)
        frontier = nxt
    return seen, list(edges.values())


@router.get("/workspaces/{workspace_id}/materials/{material_id}/lineage",
            response_model=LineageOut, operation_id="get_lineage")
def lineage(material_id: uuid.UUID, access: AccessDep):
    root = _material(access, material_id)
    ids, edges = _walk(access, root.id)
    materials = access.session.scalars(select(Material).where(Material.id.in_(ids))).all()
    return LineageOut(root=root.id, materials=[MaterialOut.model_validate(m) for m in materials],
                      edges=[LineageEdgeOut.model_validate(e) for e in edges])


@router.get("/workspaces/{workspace_id}/materials/{material_id}/custody",
            response_model=list[CustodyOut], operation_id="list_custody")
def custody(material_id: uuid.UUID, access: AccessDep):
    material = _material(access, material_id)
    return access.session.scalars(select(CustodyEvent).where(
        CustodyEvent.material_id == material.id).order_by(CustodyEvent.occurred_at)).all()


@router.post("/workspaces/{workspace_id}/materials/{material_id}/custody",
             response_model=CustodyOut, status_code=201, operation_id="record_custody")
def record_custody(material_id: uuid.UUID, body: CustodyIn, access: AccessDep):
    material = _material(access, material_id, lock=True)
    action = "material.ship" if body.event == "shipped" else "material.custody"
    authorize(access, action, Subject(project_id=material.project_id),
              ("material", material.id))
    if material.status != "active":
        raise conflict("Consumed or disposed materials accept no further custody events.")
    if body.event in ("transferred", "received") and not body.to_party:
        raise invalid("Transfers and receipts must name the receiving party.")
    event = CustodyEvent(workspace_id=access.workspace.id, material_id=material.id,
                         event=body.event, from_party=material.custodian, to_party=body.to_party,
                         location=body.location, notes=body.notes,
                         recorded_by=access.principal.id)
    if body.to_party:
        material.custodian = body.to_party
    if body.location:
        material.location = body.location
    if body.event in ("consumed", "disposed"):
        material.status = body.event
    access.session.add(event)
    access.session.flush()
    return event
