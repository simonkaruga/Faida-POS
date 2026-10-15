import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.audit import service as audit
from app.auth.deps import Actor, Db, require
from app.auth.permissions import Action
from app.settings.service import today
from app.shifts.models import CashMovement, CashMovementKind
from app.staff.models import Staff

router = APIRouter(tags=["cash"])

Cashier = Annotated[Actor, Depends(require(Action.record_payout))]
Owner = Annotated[Actor, Depends(require(Action.manage_business))]


class PayoutIn(BaseModel):
    amount: Annotated[int, Field(ge=1, le=10_000_000)]
    reason: Annotated[str, Field(min_length=1, max_length=200)]


class OwnerCashIn(BaseModel):
    amount: Annotated[int, Field(ge=-100_000_000, le=100_000_000)]  # + into the box, - out
    note: Annotated[str, Field(min_length=1, max_length=200)]


class MovementOut(BaseModel):
    id: uuid.UUID
    kind: CashMovementKind
    amount: int
    note: str | None
    by: str
    at: datetime


class CashBoxOut(BaseModel):
    expected: int  # what should be in the counter cash box right now
    today: list[MovementOut]


def _move(db: Db, actor: Actor, request: Request, kind: CashMovementKind, amount: int, note: str) -> None:
    db.add(CashMovement(business_id=actor.business_id, created_by=actor.staff.id, kind=kind, amount=amount,
                        business_day=today(db, actor.business_id, request.app.state.tz), note=note))
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action=f"cash.{kind.value}",
                 details={"amount": amount, "note": note})
    db.commit()
    request.app.state.printing.open_drawer()


@router.post("/payouts", status_code=status.HTTP_201_CREATED)
def payout(body: PayoutIn, actor: Cashier, request: Request, db: Db) -> CashBoxOut:
    """Cash taken from the day's takings, e.g. to buy ice. Reduces the cash expected
    at daily closing."""
    _move(db, actor, request, CashMovementKind.payout, -body.amount, body.reason)
    return cash_box(actor, request, db)


@router.post("/cashbox/owner", status_code=status.HTTP_201_CREATED)
def owner_cash(body: OwnerCashIn, actor: Owner, request: Request, db: Db) -> CashBoxOut:
    """The owner putting change into the box, or taking cash out of it (e.g. to bank)."""
    if body.amount == 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter an amount.")
    _move(db, actor, request, CashMovementKind.owner, body.amount, body.note)
    return cash_box(actor, request, db)


@router.get("/cashbox")
def cash_box(actor: Cashier, request: Request, db: Db) -> CashBoxOut:
    expected = db.scalar(select(func.coalesce(func.sum(CashMovement.amount), 0))
                         .where(CashMovement.business_id == actor.business_id))
    rows = db.execute(
        select(CashMovement, Staff.name).join(Staff, Staff.id == CashMovement.created_by)
        .where(CashMovement.business_id == actor.business_id,
               CashMovement.business_day == today(db, actor.business_id, request.app.state.tz))
        .order_by(CashMovement.created_at.desc())
    )
    return CashBoxOut(expected=expected, today=[
        MovementOut(id=m.id, kind=m.kind, amount=m.amount, note=m.note, by=name, at=m.created_at) for m, name in rows
    ])
