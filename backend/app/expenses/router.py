import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select

from app.audit import service as audit
from app.auth.deps import Actor, Db, require
from app.auth.permissions import Action
from app.credit.models import CreditCollection, CreditCustomer
from app.expenses.models import Expense, ExpenseCategory, PaidHow
from app.floor.models import Bill, BillStatus
from app.floor.service import place
from app.payments.models import Payment
from app.reports import service as reports
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


class Takings(BaseModel):
    """Today's money by how it was paid: sales, plus credit customers paying off."""
    cash: int
    mpesa: int
    card: int
    credit: int  # sold on credit today (not paid yet)
    unpaid: int  # unpaid, waiter responsible
    total: int
    credit_paid_cash: int
    credit_paid_mpesa: int


class PaymentRow(BaseModel):
    at: datetime
    what: str  # "Table 4 · #0031", or the credit customer
    method: str  # cash, mpesa, card, credit, credit_paid
    paid_by: str | None = None  # for credit paid: cash or mpesa
    amount: int
    ref: str | None  # M-Pesa code or card slip
    by: str


class CashBoxOut(BaseModel):
    expected: int  # what should be in the counter cash box right now
    today: list[MovementOut]
    takings: Takings | None = None
    payments: list[PaymentRow] = []


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
    day = today(db, actor.business_id, request.app.state.tz)
    return CashBoxOut(expected=expected, today=[
        MovementOut(id=m.id, kind=m.kind, amount=m.amount, note=m.note, by=name, at=m.created_at) for m, name in rows
    ], takings=_takings(db, actor, day), payments=_payments(db, actor, day))


def _takings(db: Db, actor: Actor, day: date) -> Takings:
    period = reports.Period(day, day)
    s = reports.sales(db, actor.business_id, period)
    c = reports.credit_collected(db, actor.business_id, period)
    return Takings(cash=s["cash"], mpesa=s["mpesa"], card=s["card"], credit=s["credit"], unpaid=s["unpaid"],
                   total=s["total"], credit_paid_cash=c["cash"], credit_paid_mpesa=c["mpesa"])


def _payments(db: Db, actor: Actor, day: date) -> list[PaymentRow]:
    """Every payment today, newest first: bills paid (cash, M-Pesa, card), bills put on
    credit, and credit customers paying off."""
    out = []
    for p, bill, name in db.execute(
        select(Payment, Bill, Staff.name).join(Bill, Bill.id == Payment.bill_id).join(Staff, Staff.id == Payment.created_by)
        .where(Payment.business_id == actor.business_id, Payment.business_day == day, Payment.reversed_at.is_(None))
    ):
        out.append(PaymentRow(at=p.created_at, what=f"{place(db, bill)} · #{bill.number:04d}", method=p.method.value,
                              amount=p.amount, ref=p.mpesa_ref or p.card_ref, by=name))
    for bill, customer, name in db.execute(
        select(Bill, CreditCustomer.name, Staff.name).join(CreditCustomer, CreditCustomer.id == Bill.credit_customer_id)
        .join(Staff, Staff.id == Bill.waiter_id)
        .where(Bill.business_id == actor.business_id, Bill.business_day == day, Bill.status == BillStatus.credit)
    ):
        out.append(PaymentRow(at=bill.closed_at or bill.created_at, what=f"{customer} · #{bill.number:04d}", method="credit",
                              amount=bill.credit_amount, ref=None, by=name))
    for c, customer, name in db.execute(
        select(CreditCollection, CreditCustomer.name, Staff.name)
        .join(CreditCustomer, CreditCustomer.id == CreditCollection.customer_id).join(Staff, Staff.id == CreditCollection.created_by)
        .where(CreditCollection.business_id == actor.business_id, CreditCollection.business_day == day)
    ):
        out.append(PaymentRow(at=c.created_at, what=customer, method="credit_paid", paid_by=c.method.value,
                              amount=c.amount, ref=c.mpesa_ref, by=name))
    return sorted(out, key=lambda r: r.at, reverse=True)


# Expenses (owner)


class ExpenseIn(BaseModel):
    category: ExpenseCategory
    amount: Annotated[int, Field(ge=1, le=100_000_000)] | None = None  # default: quantity x unit price
    note: Annotated[str, Field(max_length=200)] | None = None
    business_day: date | None = None  # default: today
    from_cash_box: bool = False  # paid in cash from the counter box (same as paid_how cash_box)
    payee: Annotated[str, Field(max_length=80)] | None = None
    paid_how: PaidHow | None = None
    reference: Annotated[str, Field(max_length=40)] | None = None
    quantity: Annotated[Decimal, Field(gt=0, le=1_000_000, max_digits=12, decimal_places=3)] | None = None
    unit_price: Annotated[int, Field(ge=1, le=100_000_000)] | None = None

    @model_validator(mode="after")
    def total(self):
        if self.amount is None:
            if self.quantity is None or self.unit_price is None:
                raise ValueError("Give the amount, or the quantity and the price of one.")
            self.amount = int((self.quantity * self.unit_price).to_integral_value())
        if self.paid_how is PaidHow.cash_box:
            self.from_cash_box = True
        elif self.from_cash_box and self.paid_how is None:
            self.paid_how = PaidHow.cash_box
        elif self.from_cash_box:
            raise ValueError("Paid from the cash box, or another way: not both.")
        return self


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
    payee: str | None = None
    paid_how: PaidHow | None = None
    reference: str | None = None
    quantity: Decimal | None = None
    unit_price: int | None = None


def _expense_out(db: Db, e: Expense) -> ExpenseOut:
    reversed_ = db.scalar(select(Expense.id).where(Expense.reverses_id == e.id)) is not None
    return ExpenseOut(id=e.id, category=e.category, amount=e.amount, note=e.note, business_day=e.business_day,
                      from_cash_box=e.from_cash_box, reversed=reversed_, is_reversal=e.reverses_id is not None,
                      by=db.get(Staff, e.created_by).name, payee=e.payee, paid_how=e.paid_how, reference=e.reference,
                      quantity=e.quantity, unit_price=e.unit_price)


@router.get("/expenses")
def list_expenses(
    actor: Annotated[Actor, Depends(require(Action.record_expense))], db: Db, start: date, end: date,
) -> list[ExpenseOut]:
    rows = db.scalars(select(Expense).where(Expense.business_id == actor.business_id,
                                            Expense.business_day.between(start, end))
                      .order_by(Expense.business_day.desc(), Expense.created_at.desc()))
    return [_expense_out(db, e) for e in rows]


class MonthTotals(BaseModel):
    month: str  # "2026-10"
    total: int
    by_category: dict[str, int]


class ExpenseSummary(BaseModel):
    this_month: MonthTotals
    last_month: MonthTotals


def _month(db: Db, actor: Actor, first: date) -> MonthTotals:
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    by = {c.value: 0 for c in ExpenseCategory}
    for category, total in db.execute(
        select(Expense.category, func.sum(Expense.amount))
        .where(Expense.business_id == actor.business_id, Expense.business_day.between(first, last))
        .group_by(Expense.category)
    ):
        by[category.value] = total  # reversals carry minus amounts, so they cancel here
    return MonthTotals(month=f"{first:%Y-%m}", total=sum(by.values()), by_category=by)


@router.get("/expenses/summary")
def expense_summary(
    actor: Annotated[Actor, Depends(require(Action.record_expense))], request: Request, db: Db, month: str | None = None,
) -> ExpenseSummary:
    """Totals by category for a month ("2026-10", default this month) and the month before."""
    try:
        first = date.fromisoformat(f"{month}-01") if month else today(db, actor.business_id, request.app.state.tz).replace(day=1)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Month as YYYY-MM, e.g. 2026-10.")
    return ExpenseSummary(this_month=_month(db, actor, first),
                          last_month=_month(db, actor, (first - timedelta(days=1)).replace(day=1)))


@router.post("/expenses", status_code=status.HTTP_201_CREATED)
def add_expense(
    body: ExpenseIn, actor: Annotated[Actor, Depends(require(Action.record_expense))], request: Request, db: Db,
) -> ExpenseOut:
    e = record_expense(db, actor, request, body)
    db.commit()
    if body.from_cash_box:
        request.app.state.printing.open_drawer()
    return _expense_out(db, e)


def record_expense(db: Db, actor: Actor, request: Request, body: ExpenseIn) -> Expense:
    """Adds the expense (and its cash box movement) without committing; also used for pay."""
    day = body.business_day or today(db, actor.business_id, request.app.state.tz)
    e = Expense(business_id=actor.business_id, created_by=actor.staff.id, category=body.category, amount=body.amount,
                note=body.note, business_day=day, from_cash_box=body.from_cash_box, payee=body.payee,
                paid_how=body.paid_how, reference=body.reference, quantity=body.quantity, unit_price=body.unit_price)
    db.add(e)
    db.flush()
    if body.from_cash_box:
        db.add(CashMovement(business_id=actor.business_id, created_by=actor.staff.id, kind=CashMovementKind.owner,
                            amount=-body.amount, business_day=today(db, actor.business_id, request.app.state.tz),
                            reference_id=e.id, note=f"Expense: {body.category.value}"))
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="expense.added",
                 entity_type="expense", entity_id=e.id, details=body.model_dump(mode="json"))
    return e


@router.post("/expenses/{expense_id}/reverse", status_code=status.HTTP_201_CREATED)
def reverse_expense(
    expense_id: uuid.UUID, actor: Annotated[Actor, Depends(require(Action.record_expense))], request: Request, db: Db,
) -> ExpenseOut:
    """Undo a mistaken expense with a visible reversal entry (nothing is deleted)."""
    e = db.get(Expense, expense_id)
    if e is None or e.business_id != actor.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Expense not found.")
    r = reverse(db, actor, request, e)
    db.commit()
    return _expense_out(db, r)


def reverse(db: Db, actor: Actor, request: Request, e: Expense) -> Expense:
    """Adds the reversal of an expense (and gives cash back to the box) without committing."""
    if e.reverses_id or db.scalar(select(Expense.id).where(Expense.reverses_id == e.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Already reversed.")
    r = Expense(business_id=actor.business_id, created_by=actor.staff.id, category=e.category, amount=-e.amount,
                note=f"Reversal: {e.note or ''}".strip(), business_day=e.business_day, from_cash_box=e.from_cash_box,
                reverses_id=e.id, payee=e.payee, paid_how=e.paid_how, reference=e.reference)
    db.add(r)
    db.flush()
    if e.from_cash_box:
        db.add(CashMovement(business_id=actor.business_id, created_by=actor.staff.id, kind=CashMovementKind.owner,
                            amount=e.amount, business_day=today(db, actor.business_id, request.app.state.tz),
                            reference_id=r.id, note=f"Expense reversed: {e.category.value}"))
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="expense.reversed",
                 entity_type="expense", entity_id=e.id, details={"amount": e.amount, "category": e.category.value})
    return r
