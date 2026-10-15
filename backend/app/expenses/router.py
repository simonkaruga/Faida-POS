import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.audit import service as audit
from app.auth.deps import Actor, Db, require
from app.auth.permissions import Action
from app.expenses.models import Expense, ExpenseCategory
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


# Expenses (owner)


class ExpenseIn(BaseModel):
    category: ExpenseCategory
    amount: Annotated[int, Field(ge=1, le=100_000_000)]
    note: Annotated[str, Field(max_length=200)] | None = None
    business_day: date | None = None  # default: today
    from_cash_box: bool = False  # paid in cash from the counter box


class ExpenseOut(BaseModel):
    id: uuid.UUID
    category: ExpenseCategory
    amount: int
    note: str | None
    business_day: date
    from_cash_box: bool
    reversed: bool
    is_reversal: bool
    by: str


def _expense_out(db: Db, e: Expense) -> ExpenseOut:
    reversed_ = db.scalar(select(Expense.id).where(Expense.reverses_id == e.id)) is not None
    return ExpenseOut(id=e.id, category=e.category, amount=e.amount, note=e.note, business_day=e.business_day,
                      from_cash_box=e.from_cash_box, reversed=reversed_, is_reversal=e.reverses_id is not None,
                      by=db.get(Staff, e.created_by).name)


@router.get("/expenses")
def list_expenses(
    actor: Annotated[Actor, Depends(require(Action.record_expense))], db: Db, start: date, end: date,
) -> list[ExpenseOut]:
    rows = db.scalars(select(Expense).where(Expense.business_id == actor.business_id,
                                            Expense.business_day.between(start, end))
                      .order_by(Expense.business_day.desc(), Expense.created_at.desc()))
    return [_expense_out(db, e) for e in rows]


@router.post("/expenses", status_code=status.HTTP_201_CREATED)
def add_expense(
    body: ExpenseIn, actor: Annotated[Actor, Depends(require(Action.record_expense))], request: Request, db: Db,
) -> ExpenseOut:
    day = body.business_day or today(db, actor.business_id, request.app.state.tz)
    e = Expense(business_id=actor.business_id, created_by=actor.staff.id, category=body.category, amount=body.amount,
                note=body.note, business_day=day, from_cash_box=body.from_cash_box)
    db.add(e)
    db.flush()
    if body.from_cash_box:
        db.add(CashMovement(business_id=actor.business_id, created_by=actor.staff.id, kind=CashMovementKind.owner,
                            amount=-body.amount, business_day=today(db, actor.business_id, request.app.state.tz),
                            reference_id=e.id, note=f"Expense: {body.category.value}"))
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="expense.added",
                 entity_type="expense", entity_id=e.id, details=body.model_dump(mode="json"))
    db.commit()
    if body.from_cash_box:
        request.app.state.printing.open_drawer()
    return _expense_out(db, e)


@router.post("/expenses/{expense_id}/reverse", status_code=status.HTTP_201_CREATED)
def reverse_expense(
    expense_id: uuid.UUID, actor: Annotated[Actor, Depends(require(Action.record_expense))], request: Request, db: Db,
) -> ExpenseOut:
    """Undo a mistaken expense with a visible reversal entry (nothing is deleted)."""
    e = db.get(Expense, expense_id)
    if e is None or e.business_id != actor.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Expense not found.")
    if e.reverses_id or db.scalar(select(Expense.id).where(Expense.reverses_id == e.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Already reversed.")
    r = Expense(business_id=actor.business_id, created_by=actor.staff.id, category=e.category, amount=-e.amount,
                note=f"Reversal: {e.note or ''}".strip(), business_day=e.business_day, from_cash_box=e.from_cash_box,
                reverses_id=e.id)
    db.add(r)
    db.flush()
    if e.from_cash_box:
        db.add(CashMovement(business_id=actor.business_id, created_by=actor.staff.id, kind=CashMovementKind.owner,
                            amount=e.amount, business_day=today(db, actor.business_id, request.app.state.tz),
                            reference_id=r.id, note=f"Expense reversed: {e.category.value}"))
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="expense.reversed",
                 entity_type="expense", entity_id=e.id, details={"amount": e.amount, "category": e.category.value})
    db.commit()
    return _expense_out(db, r)
