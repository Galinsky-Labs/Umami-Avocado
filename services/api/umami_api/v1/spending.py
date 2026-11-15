"""Budgets, quotes, reservations and the ledger (UA-008)."""
import uuid

from fastapi import APIRouter
from sqlalchemy import select

from umami_api.authz import authorize
from umami_api.db import utcnow
from umami_api.errors import ApiError, conflict, not_found
from umami_api.models import Budget, LedgerEntry, Quote, Reservation
from umami_api.policy import Subject
from umami_api.schemas import (
    BalancesOut,
    BudgetIn,
    LedgerEntryOut,
    QuoteIn,
    QuoteOut,
    ReservationIn,
    ReservationOut,
)
from umami_api.security import AccessDep, WorkspaceAccess
from umami_api.spending import balances, committed, lock_budget, post
from umami_api.v1.projects import get_project

router = APIRouter(tags=["spending"])


def limit_exceeded(message: str) -> ApiError:
    return ApiError(409, "limit_exceeded", message)


def _balances_out(access: WorkspaceAccess, project_id: uuid.UUID) -> BalancesOut:
    budget = access.session.scalar(select(Budget).where(Budget.project_id == project_id))
    values = balances(access.session, project_id)
    return BalancesOut(project_id=project_id, cap_cents=budget.cap_cents if budget else 0,
                       available_cents=values["available"], reserved_cents=values["reserved"],
                       spent_cents=values["spent"],
                       platform_cap_cents=access.caller.settings.max_authorized_spend_cents)


@router.get("/workspaces/{workspace_id}/projects/{project_id}/budget", response_model=BalancesOut,
            operation_id="get_budget")
def get_budget(project_id: uuid.UUID, access: AccessDep):
    return _balances_out(access, get_project(access, project_id).id)


@router.put("/workspaces/{workspace_id}/projects/{project_id}/budget", response_model=BalancesOut,
            operation_id="set_budget")
def set_budget(project_id: uuid.UUID, body: BudgetIn, access: AccessDep):
    project = get_project(access, project_id)
    authorize(access, "budget.manage", Subject(project_id=project.id), ("project", project.id))
    budget = lock_budget(access.session, project.id)
    previous = budget.cap_cents if budget else 0
    values = balances(access.session, project.id)
    if body.cap_cents < committed(values):
        raise conflict("The cap cannot be lowered below reserved and spent funds.")
    if budget is None:
        budget = Budget(workspace_id=access.workspace.id, project_id=project.id,
                        cap_cents=body.cap_cents, set_by=access.principal.id)
        access.session.add(budget)
    else:
        budget.cap_cents, budget.set_by, budget.updated_at = (body.cap_cents, access.principal.id,
                                                              utcnow())
    delta = body.cap_cents - previous
    if delta:
        post(access.session, workspace_id=access.workspace.id, project_id=project.id,
             actor_id=access.principal.id, memo="budget cap change",
             legs=[("funding", -delta), ("available", delta)])
    return _balances_out(access, project.id)


@router.get("/workspaces/{workspace_id}/projects/{project_id}/ledger",
            response_model=list[LedgerEntryOut], operation_id="list_ledger")
def ledger(project_id: uuid.UUID, access: AccessDep):
    project = get_project(access, project_id)
    return access.session.scalars(select(LedgerEntry).where(LedgerEntry.project_id == project.id)
                                  .order_by(LedgerEntry.posted_at, LedgerEntry.account)).all()


@router.get("/workspaces/{workspace_id}/quotes", response_model=list[QuoteOut],
            operation_id="list_quotes")
def list_quotes(access: AccessDep):
    return access.session.scalars(select(Quote).where(Quote.workspace_id == access.workspace.id)
                                  .order_by(Quote.created_at.desc())).all()


@router.post("/workspaces/{workspace_id}/quotes", response_model=QuoteOut, status_code=201,
             operation_id="record_quote")
def record_quote(body: QuoteIn, access: AccessDep):
    project = get_project(access, body.project_id)
    authorize(access, "quote.record", Subject(project_id=project.id))
    if access.principal.kind == "agent" and body.origin != "SIMULATED":
        raise ApiError(403, "policy_denied", "Agents may only record SIMULATED quotes.")
    quote = Quote(workspace_id=access.workspace.id, recorded_by=access.principal.id,
                  **body.model_dump())
    access.session.add(quote)
    access.session.flush()
    return quote


def _reservation(access: WorkspaceAccess, reservation_id: uuid.UUID) -> Reservation:
    reservation = access.session.scalar(select(Reservation).where(
        Reservation.id == reservation_id, Reservation.workspace_id == access.workspace.id)
        .with_for_update())
    if reservation is None:
        raise not_found("reservation")
    return reservation


@router.get("/workspaces/{workspace_id}/reservations", response_model=list[ReservationOut],
            operation_id="list_reservations")
def list_reservations(access: AccessDep):
    return access.session.scalars(select(Reservation).where(
        Reservation.workspace_id == access.workspace.id)
        .order_by(Reservation.created_at.desc())).all()


@router.post("/workspaces/{workspace_id}/reservations", response_model=ReservationOut,
             status_code=201, operation_id="request_reservation")
def request_reservation(body: ReservationIn, access: AccessDep):
    project = get_project(access, body.project_id)
    authorize(access, "spend.reserve", Subject(project_id=project.id))
    if body.quote_id is not None:
        quote = access.session.get(Quote, body.quote_id)
        if quote is None or quote.project_id != project.id:
            raise not_found("quote")
        if quote.origin != "PHYSICAL":
            raise conflict("Simulated quotes cannot back a spending reservation.")
    reservation = Reservation(workspace_id=access.workspace.id, requested_by=access.principal.id,
                              **body.model_dump())
    access.session.add(reservation)
    access.session.flush()
    return reservation


@router.post("/workspaces/{workspace_id}/reservations/{reservation_id}/approve",
             response_model=ReservationOut, operation_id="approve_reservation")
def approve(reservation_id: uuid.UUID, access: AccessDep):
    reservation = _reservation(access, reservation_id)
    authorize(access, "spend.approve", Subject(project_id=reservation.project_id,
                                               author_id=reservation.requested_by),
              ("reservation", reservation.id))
    if reservation.status != "requested":
        raise conflict("Only requested reservations can be approved.")
    budget = lock_budget(access.session, reservation.project_id)
    values = balances(access.session, reservation.project_id)
    platform_cap = access.caller.settings.max_authorized_spend_cents
    project_cap = budget.cap_cents if budget else 0
    if committed(values) + reservation.amount_cents > platform_cap:
        raise limit_exceeded("Approval would exceed the platform spending cap "
                             "(LAB_MAX_AUTHORIZED_SPEND_USD).")
    if reservation.amount_cents > values["available"] or (
            committed(values) + reservation.amount_cents > project_cap):
        raise limit_exceeded("Approval would exceed the project budget.")
    post(access.session, workspace_id=access.workspace.id, project_id=reservation.project_id,
         actor_id=access.principal.id, memo="reservation approved", reservation_id=reservation.id,
         legs=[("available", -reservation.amount_cents), ("reserved", reservation.amount_cents)])
    reservation.status, reservation.decided_by, reservation.decided_at = (
        "approved", access.principal.id, utcnow())
    return reservation


@router.post("/workspaces/{workspace_id}/reservations/{reservation_id}/reject",
             response_model=ReservationOut, operation_id="reject_reservation")
def reject(reservation_id: uuid.UUID, access: AccessDep):
    reservation = _reservation(access, reservation_id)
    authorize(access, "spend.approve", Subject(project_id=reservation.project_id),
              ("reservation", reservation.id))
    if reservation.status != "requested":
        raise conflict("Only requested reservations can be rejected.")
    reservation.status, reservation.decided_by, reservation.decided_at = (
        "rejected", access.principal.id, utcnow())
    return reservation


@router.post("/workspaces/{workspace_id}/reservations/{reservation_id}/release",
             response_model=ReservationOut, operation_id="release_reservation")
def release(reservation_id: uuid.UUID, access: AccessDep):
    reservation = _reservation(access, reservation_id)
    authorize(access, "budget.manage", Subject(project_id=reservation.project_id),
              ("reservation", reservation.id))
    if reservation.status != "approved":
        raise conflict("Only approved reservations can be released.")
    lock_budget(access.session, reservation.project_id)
    post(access.session, workspace_id=access.workspace.id, project_id=reservation.project_id,
         actor_id=access.principal.id, memo="reservation released", reservation_id=reservation.id,
         legs=[("reserved", -reservation.amount_cents), ("available", reservation.amount_cents)])
    reservation.status = "released"
    return reservation
