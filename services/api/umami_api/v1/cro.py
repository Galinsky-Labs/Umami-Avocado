"""Supervised manual CRO workflow and secure file exchange (UA-014).

A person prepares a work order from a PHYSICAL proposal; the platform freezes the order
package as an immutable artifact (its digest is what gets approved); a different human
approves it; dispatch is a physical action and is denied while live submission is
disabled. Every exchanged file is an immutable artifact logged in ``exchange_items``.
"""
import json
import uuid

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from umami_api.artifacts import create_artifact
from umami_api.authz import authorize
from umami_api.db import utcnow
from umami_api.errors import conflict, invalid, not_found
from umami_api.models import (
    ExchangeItem,
    ExperimentProposal,
    Laboratory,
    ProtocolVersion,
    Reservation,
    WorkOrder,
)
from umami_api.policy import Subject
from umami_api.schemas import ExchangeItemOut, ExchangeNoteIn, WorkOrderIn, WorkOrderOut
from umami_api.security import AccessDep, WorkspaceAccess
from umami_api.v1.projects import get_project
from umami_api.v1.studio import evaluate

router = APIRouter(tags=["cro"])
PHYSICAL_GATE = "physical_execution_available"


def _order(access: WorkspaceAccess, project_id: uuid.UUID, order_id: uuid.UUID) -> WorkOrder:
    order = access.session.scalar(select(WorkOrder).where(
        WorkOrder.id == order_id, WorkOrder.project_id == project_id,
        WorkOrder.workspace_id == access.workspace.id).with_for_update())
    if order is None:
        raise not_found("work order")
    return order


def _log(access, order, direction, note="", artifact_id=None):
    access.session.add(ExchangeItem(workspace_id=access.workspace.id, work_order_id=order.id,
                                    direction=direction, note=note, artifact_id=artifact_id,
                                    recorded_by=access.principal.id))


@router.post("/workspaces/{workspace_id}/projects/{project_id}/work-orders",
             response_model=WorkOrderOut, status_code=201, operation_id="create_work_order")
def create(project_id: uuid.UUID, body: WorkOrderIn, access: AccessDep):
    project = get_project(access, project_id)
    authorize(access, "cro.exchange", Subject(project_id=project.id), ("project", project.id))
    lab = access.session.scalar(select(Laboratory).where(
        Laboratory.id == body.laboratory_id, Laboratory.workspace_id == access.workspace.id))
    if lab is None:
        raise not_found("laboratory")
    if lab.adapter_key != "manual_cro":
        raise invalid("Work orders are only for manual CRO laboratories.")
    proposal = access.session.scalar(select(ExperimentProposal).where(
        ExperimentProposal.id == body.proposal_id, ExperimentProposal.project_id == project.id))
    if proposal is None:
        raise not_found("proposal")
    if proposal.target_origin != "PHYSICAL":
        raise conflict("Only PHYSICAL proposals become CRO work orders.")
    if body.reservation_id is not None:
        reservation = access.session.get(Reservation, body.reservation_id)
        if reservation is None or reservation.project_id != project.id:
            raise not_found("reservation")
    protocol = access.session.get(ProtocolVersion, proposal.protocol_version_id)
    order = WorkOrder(workspace_id=access.workspace.id, project_id=project.id,
                      laboratory_id=lab.id, proposal_id=proposal.id,
                      reservation_id=body.reservation_id, title=body.title,
                      author_id=access.principal.id)
    access.session.add(order)
    access.session.flush()
    package = json.dumps({
        "work_order_id": str(order.id), "title": body.title, "laboratory": lab.name,
        "proposal": {"id": str(proposal.id), "title": proposal.title,
                     "hypothesis": proposal.hypothesis},
        "protocol": {"id": str(protocol.id), "key": protocol.key, "version": protocol.version,
                     "content": protocol.content},
        "notice": "Draft package. Not authorised for execution unless approved and dispatched "
                  "through the platform.",
    }, sort_keys=True, indent=2).encode()
    artifact = create_artifact(access, project_id=project.id, name=f"work-order-{order.id}.json",
                               media_type="application/json", content=package,
                               origin="PHYSICAL", source="export",
                               provenance={"work_order_id": str(order.id), "kind": "package"})
    order.package_artifact_id, order.package_sha256 = artifact.id, artifact.sha256
    _log(access, order, "note", "Order package frozen", artifact.id)
    return order


@router.get("/workspaces/{workspace_id}/projects/{project_id}/work-orders",
            response_model=list[WorkOrderOut], operation_id="list_work_orders")
def list_orders(project_id: uuid.UUID, access: AccessDep):
    project = get_project(access, project_id)
    return access.session.scalars(select(WorkOrder).where(WorkOrder.project_id == project.id)
                                  .order_by(WorkOrder.created_at.desc())).all()


@router.post("/workspaces/{workspace_id}/projects/{project_id}/work-orders/{order_id}/approve",
             response_model=WorkOrderOut, operation_id="approve_work_order")
def approve(project_id: uuid.UUID, order_id: uuid.UUID, access: AccessDep):
    """Human approval of the exact frozen package. Approval does not dispatch anything."""
    order = _order(access, get_project(access, project_id).id, order_id)
    authorize(access, "experiment.approve_physical",
              Subject(project_id=order.project_id, author_id=order.author_id),
              ("work_order", order.id))
    if order.state != "draft":
        raise conflict("Only draft work orders can be approved.")
    proposal = access.session.get(ExperimentProposal, order.proposal_id)
    result = evaluate(access, proposal)
    failing = [c["key"] for c in result["checks"] if c["severity"] == "blocker"
               and not c["passed"] and c["key"] != PHYSICAL_GATE]
    if failing:
        raise conflict("Preflight blockers must be resolved: " + ", ".join(failing))
    protocol = access.session.get(ProtocolVersion, proposal.protocol_version_id)
    cost = int(protocol.content.get("estimated_cost_cents", 0))
    if cost > 0:
        reservation = access.session.get(Reservation, order.reservation_id) \
            if order.reservation_id else None
        if reservation is None or reservation.status != "approved" or \
                reservation.amount_cents < cost:
            raise conflict("An approved spending reservation covering the estimated cost "
                           "is required.")
    order.state, order.approved_by, order.approved_at = "approved", access.principal.id, utcnow()
    order.updated_at = utcnow()
    _log(access, order, "note", f"Approved package sha256={order.package_sha256}")
    return order


@router.post("/workspaces/{workspace_id}/projects/{project_id}/work-orders/{order_id}/dispatch",
             response_model=WorkOrderOut, operation_id="dispatch_work_order")
def dispatch(project_id: uuid.UUID, order_id: uuid.UUID, access: AccessDep):
    order = _order(access, get_project(access, project_id).id, order_id)
    authorize(access, "cro.dispatch", Subject(project_id=order.project_id),
              ("work_order", order.id))
    raise conflict("Unreachable while live submission is disabled.")  # pragma: no cover


@router.post("/workspaces/{workspace_id}/projects/{project_id}/work-orders/{order_id}/cancel",
             response_model=WorkOrderOut, operation_id="cancel_work_order")
def cancel(project_id: uuid.UUID, order_id: uuid.UUID, access: AccessDep):
    order = _order(access, get_project(access, project_id).id, order_id)
    authorize(access, "cro.exchange", Subject(project_id=order.project_id),
              ("work_order", order.id))
    if order.state in ("closed", "cancelled"):
        raise conflict("The work order is already finished.")
    order.state, order.updated_at = "cancelled", utcnow()
    _log(access, order, "note", "Cancelled")
    return order


@router.post("/workspaces/{workspace_id}/projects/{project_id}/work-orders/{order_id}/files",
             response_model=ExchangeItemOut, status_code=201, operation_id="receive_cro_file")
async def receive_file(project_id: uuid.UUID, order_id: uuid.UUID, request: Request,
                       access: AccessDep,
                       name: str = Query(min_length=1, max_length=200, pattern=r"^[\w .()-]+$"),
                       note: str = Query(default="", max_length=2000)):
    """Record a file returned by the CRO. Only possible after a dispatched order."""
    order = _order(access, get_project(access, project_id).id, order_id)
    authorize(access, "cro.exchange", Subject(project_id=order.project_id),
              ("work_order", order.id))
    authorize(access, "measurement.record_physical", Subject(project_id=order.project_id))
    if order.state not in ("dispatched", "in_progress", "results_received"):
        raise conflict("Files can only be received for dispatched work orders.")
    content = await request.body()
    media_type = request.headers.get("content-type", "application/octet-stream").split(";")[0]
    artifact = create_artifact(access, project_id=order.project_id, name=name,
                               media_type=media_type, content=content, origin="PHYSICAL",
                               source="cro_exchange",
                               provenance={"work_order_id": str(order.id), "note": note})
    order.state, order.updated_at = "results_received", utcnow()
    item = ExchangeItem(workspace_id=access.workspace.id, work_order_id=order.id,
                        direction="inbound", artifact_id=artifact.id, note=note,
                        recorded_by=access.principal.id)
    access.session.add(item)
    access.session.flush()
    return item


@router.post("/workspaces/{workspace_id}/projects/{project_id}/work-orders/{order_id}/notes",
             response_model=ExchangeItemOut, status_code=201, operation_id="add_exchange_note")
def add_note(project_id: uuid.UUID, order_id: uuid.UUID, body: ExchangeNoteIn,
             access: AccessDep):
    order = _order(access, get_project(access, project_id).id, order_id)
    authorize(access, "cro.exchange", Subject(project_id=order.project_id),
              ("work_order", order.id))
    item = ExchangeItem(workspace_id=access.workspace.id, work_order_id=order.id,
                        direction="note", note=body.note, recorded_by=access.principal.id)
    access.session.add(item)
    access.session.flush()
    return item


@router.get("/workspaces/{workspace_id}/projects/{project_id}/work-orders/{order_id}/exchange",
            response_model=list[ExchangeItemOut], operation_id="list_exchange")
def exchange(project_id: uuid.UUID, order_id: uuid.UUID, access: AccessDep):
    order = _order(access, get_project(access, project_id).id, order_id)
    return access.session.scalars(select(ExchangeItem).where(
        ExchangeItem.work_order_id == order.id).order_by(ExchangeItem.created_at)).all()
