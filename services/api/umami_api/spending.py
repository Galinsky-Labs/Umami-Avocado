"""Double-entry spending ledger and cap enforcement (UA-008).

Accounts per project: funding (source, negative), available, reserved, spent.
The effective ceiling on approved reservations is the lower of the project budget
and the platform cap LAB_MAX_AUTHORIZED_SPEND_USD (0 by default, so nothing can be
approved until the owner deliberately raises both). Money is never moved to
``spent`` in this codebase: consumption requires a supervised physical order (UA-027).
"""
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from umami_api.models import Budget, LedgerEntry


def post(session: Session, *, workspace_id: uuid.UUID, project_id: uuid.UUID,
         actor_id: uuid.UUID, memo: str, legs: list[tuple[str, int]],
         reservation_id: uuid.UUID | None = None) -> uuid.UUID:
    if sum(amount for _, amount in legs) != 0 or not legs:
        raise ValueError("Ledger postings must balance.")
    posting = uuid.uuid4()
    for account, amount in legs:
        session.add(LedgerEntry(workspace_id=workspace_id, project_id=project_id,
                                posting_id=posting, account=account, amount_cents=amount,
                                reservation_id=reservation_id, memo=memo, posted_by=actor_id))
    session.flush()
    return posting


def balances(session: Session, project_id: uuid.UUID) -> dict[str, int]:
    rows = session.execute(select(LedgerEntry.account, func.sum(LedgerEntry.amount_cents))
                           .where(LedgerEntry.project_id == project_id)
                           .group_by(LedgerEntry.account)).all()
    values = {"funding": 0, "available": 0, "reserved": 0, "spent": 0}
    values.update({account: int(total) for account, total in rows})
    return values


def committed(values: dict[str, int]) -> int:
    return values["reserved"] + values["spent"]


def lock_budget(session: Session, project_id: uuid.UUID) -> Budget | None:
    return session.scalar(select(Budget).where(Budget.project_id == project_id).with_for_update())
