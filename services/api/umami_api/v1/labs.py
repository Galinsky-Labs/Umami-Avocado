"""Laboratory network: adapters, capability registry and contracts (UA-013)."""
import uuid

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from umami_api.authz import authorize
from umami_api.db import utcnow
from umami_api.errors import conflict, not_found
from umami_api.labs.builtin import ADAPTERS
from umami_api.models import LabContract, Laboratory
from umami_api.schemas import (
    AdapterOut,
    LabContractIn,
    LabContractOut,
    LabMatchOut,
    LaboratoryIn,
    LaboratoryOut,
    LaboratoryPatch,
)
from umami_api.security import AccessDep, WorkspaceAccess

router = APIRouter(tags=["laboratories"])


@router.get("/lab-adapters", response_model=list[AdapterOut], operation_id="list_lab_adapters")
def adapters():
    return [AdapterOut(key=key, mode=cls.mode.value, origin=cls.origin,
                       dispatch_enabled=cls.origin == "SIMULATED")
            for key, cls in ADAPTERS.items()]


def get_lab(access: WorkspaceAccess, lab_id: uuid.UUID, lock: bool = False) -> Laboratory:
    query = select(Laboratory).where(Laboratory.id == lab_id,
                                     Laboratory.workspace_id == access.workspace.id)
    lab = access.session.scalar(query.with_for_update() if lock else query)
    if lab is None:
        raise not_found("laboratory")
    return lab


@router.get("/workspaces/{workspace_id}/laboratories", response_model=list[LaboratoryOut],
            operation_id="list_laboratories")
def list_labs(access: AccessDep):
    return access.session.scalars(select(Laboratory).where(
        Laboratory.workspace_id == access.workspace.id).order_by(Laboratory.name)).all()


@router.post("/workspaces/{workspace_id}/laboratories", response_model=LaboratoryOut,
             status_code=201, operation_id="register_laboratory")
def register_lab(body: LaboratoryIn, access: AccessDep):
    authorize(access, "adapter.manage")
    lab = Laboratory(workspace_id=access.workspace.id, created_by=access.principal.id,
                     name=body.name, adapter_key=body.adapter_key,
                     capabilities=[c.model_dump() for c in body.capabilities],
                     public_contact=body.public_contact, notes=body.notes)
    access.session.add(lab)
    try:
        with access.session.begin_nested():
            access.session.flush()
    except IntegrityError as error:
        raise conflict("A laboratory with this name already exists.") from error
    return lab


@router.patch("/workspaces/{workspace_id}/laboratories/{lab_id}", response_model=LaboratoryOut,
              operation_id="update_laboratory")
def update_lab(lab_id: uuid.UUID, body: LaboratoryPatch, access: AccessDep):
    lab = get_lab(access, lab_id, lock=True)
    authorize(access, "adapter.manage", resource=("laboratory", lab.id))
    if body.status == "contracted" and not access.session.scalar(select(LabContract.id).where(
            LabContract.laboratory_id == lab.id, LabContract.status == "signed").limit(1)) \
            and lab.adapter_key != "simulator":
        raise conflict("A laboratory can be marked contracted only with a signed contract.")
    if body.status is not None:
        lab.status = body.status
    if body.capabilities is not None:
        lab.capabilities = [c.model_dump() for c in body.capabilities]
    if body.notes is not None:
        lab.notes = body.notes
    lab.updated_at = utcnow()
    return lab


@router.get("/workspaces/{workspace_id}/laboratories/{lab_id}/contracts",
            response_model=list[LabContractOut], operation_id="list_lab_contracts")
def list_contracts(lab_id: uuid.UUID, access: AccessDep):
    lab = get_lab(access, lab_id)
    return access.session.scalars(select(LabContract).where(
        LabContract.laboratory_id == lab.id).order_by(LabContract.created_at)).all()


@router.post("/workspaces/{workspace_id}/laboratories/{lab_id}/contracts",
             response_model=LabContractOut, status_code=201, operation_id="record_lab_contract")
def record_contract(lab_id: uuid.UUID, body: LabContractIn, access: AccessDep):
    lab = get_lab(access, lab_id)
    authorize(access, "adapter.manage", resource=("laboratory", lab.id))
    contract = LabContract(workspace_id=access.workspace.id, laboratory_id=lab.id,
                           recorded_by=access.principal.id, **body.model_dump())
    access.session.add(contract)
    access.session.flush()
    return contract


@router.get("/workspaces/{workspace_id}/laboratories/match", response_model=list[LabMatchOut],
            operation_id="match_laboratories")
def match(access: AccessDep, capability: str, organism: str):
    """Laboratories offering a capability for an organism, contracted ones first."""
    labs = access.session.scalars(select(Laboratory).where(
        Laboratory.workspace_id == access.workspace.id,
        Laboratory.status != "suspended")).all()
    now = utcnow()
    out = []
    for lab in labs:
        for cap in lab.capabilities:
            if cap["code"] == capability and organism in cap["organisms"]:
                signed = access.session.scalar(select(LabContract.id).where(
                    LabContract.laboratory_id == lab.id, LabContract.status == "signed",
                    (LabContract.expires_at.is_(None)) | (LabContract.expires_at > now))
                    .limit(1)) is not None
                out.append(LabMatchOut(laboratory=LaboratoryOut.model_validate(lab),
                                       capability=cap, contracted=lab.status == "contracted",
                                       has_signed_contract=signed))
    return sorted(out, key=lambda m: (not m.contracted, not m.has_signed_contract,
                                      m.capability.get("unit_price_cents", 0)))
