"""Salaries (owner only): who is paid, how much (per month, week or day), advances,
deductions and shortages, and what is left to pay. Faida never deducts by itself: every
deduction is the owner's decision under her house rules and employment law."""

import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.audit import service as audit
from app.auth.deps import Actor, Db, require
from app.auth.permissions import Action
from app.expenses.models import Expense, ExpenseCategory, PaidHow
from app.expenses.router import ExpenseIn, record_expense, reverse
from app.payroll.models import EmployeeEntry, Employee, EntryKind, PayType
from app.settings.service import today
from app.shifts.models import Handover, Shift, ShortageOutcome, ShortageStatus
from app.staff.models import Staff

router = APIRouter(prefix="/payroll", tags=["payroll"])

Owner = Annotated[Actor, Depends(require(Action.manage_business))]
Money = Annotated[int, Field(ge=1, le=10_000_000)]
Note = Annotated[str, Field(max_length=200)]


def balance(db: Db, employee_id: uuid.UUID) -> int:
    """What the bar owes the employee; below 0, what they owe the bar."""
    return db.scalar(select(func.coalesce(func.sum(EmployeeEntry.amount), 0))
                     .where(EmployeeEntry.employee_id == employee_id))


def _employee(db: Db, actor: Actor, employee_id: uuid.UUID) -> Employee:
    e = db.get(Employee, employee_id)
    if e is None or e.business_id != actor.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found.")
    return e


def _entry(db: Db, actor: Actor, e: Employee, kind: EntryKind, amount: int, request: Request, **fields) -> EmployeeEntry:
    row = EmployeeEntry(business_id=actor.business_id, created_by=actor.staff.id, employee_id=e.id, kind=kind,
                        amount=amount, business_day=today(db, actor.business_id, request.app.state.tz), **fields)
    db.add(row)
    db.flush()
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action=f"payroll.{kind.value}",
                 entity_type="employee", entity_id=e.id,
                 details={"employee": e.name, "amount": amount, "note": fields.get("note")})
    return row


def _paid_out(db: Db, actor: Actor, request: Request, e: Employee, amount: int, paid_how: PaidHow,
              reference: str | None, note: str) -> Expense:
    """Money handed to an employee is a salaries expense (from the cash box if so)."""
    return record_expense(db, actor, request, ExpenseIn(category=ExpenseCategory.salaries, amount=amount, note=note,
                                                        payee=e.name, paid_how=paid_how, reference=reference))


def _shortages(db: Db, e: Employee) -> list["ShortageOut"]:
    """Their cash shortages (linked PIN) not yet decided, newest first."""
    if not e.staff_id:
        return []
    out = []
    for h, day in db.execute(select(Handover, Shift.business_day).join(Shift, Shift.id == Handover.shift_id)
                             .where(Handover.staff_id == e.staff_id, Handover.difference < 0)
                             .order_by(Handover.created_at.desc())):
        if db.scalar(select(ShortageStatus.id).where(ShortageStatus.handover_id == h.id).limit(1)) is None:
            out.append(ShortageOut(handover_id=h.id, day=day, amount=-h.difference))
    return out


def shortage_decided(db: Db, actor: Actor, request: Request, handover: Handover, outcome: ShortageOutcome) -> None:
    """Called when the owner marks a shortage. Deducted: it comes off the linked employee's
    pay; changed to paid back or forgiven later: that deduction is reversed."""
    e = db.scalar(select(Employee).where(Employee.business_id == actor.business_id,
                                         Employee.staff_id == handover.staff_id, Employee.active))
    if e is None:
        return
    taken = db.scalar(select(EmployeeEntry).where(EmployeeEntry.handover_id == handover.id,
                                                  EmployeeEntry.kind == EntryKind.shortage))
    undone = taken and db.scalar(select(EmployeeEntry.id).where(EmployeeEntry.reverses_id == taken.id))
    if outcome is ShortageOutcome.deducted and (taken is None or undone):
        _entry(db, actor, e, EntryKind.shortage, handover.difference, request, handover_id=handover.id,
               note="Cash short at hand-over")
    elif outcome is not ShortageOutcome.deducted and taken and not undone:
        _entry(db, actor, e, EntryKind.reversal, -taken.amount, request, reverses_id=taken.id,
               note=f"Shortage {outcome.value.replace('_', ' ')}")


# Employees


class EmployeeIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    job: Annotated[str, Field(max_length=40)] | None = None
    phone: Annotated[str, Field(max_length=20)] | None = None
    staff_id: uuid.UUID | None = None
    pay_type: PayType
    pay_rate: Annotated[int, Field(ge=0, le=10_000_000)]


class EmployeePatch(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    job: Annotated[str, Field(max_length=40)] | None = None
    phone: Annotated[str, Field(max_length=20)] | None = None
    staff_id: uuid.UUID | None = None
    pay_type: PayType | None = None
    pay_rate: Annotated[int, Field(ge=0, le=10_000_000)] | None = None
    active: bool | None = None


class ShortageOut(BaseModel):
    handover_id: uuid.UUID
    day: date
    amount: int


class EmployeeOut(BaseModel):
    id: uuid.UUID
    name: str
    job: str | None
    phone: str | None
    staff_id: uuid.UUID | None
    staff_name: str | None
    pay_type: PayType
    pay_rate: int
    active: bool
    balance: int  # the bar owes them; below 0 they owe the bar
    paid_to: date | None  # the last salary paid covers up to this day
    shortages: list[ShortageOut]  # not decided yet


def _out(db: Db, e: Employee) -> EmployeeOut:
    paid_to = db.scalar(select(func.max(EmployeeEntry.period_end)).where(EmployeeEntry.employee_id == e.id,
                                                                         EmployeeEntry.kind == EntryKind.salary))
    return EmployeeOut(id=e.id, name=e.name, job=e.job, phone=e.phone, staff_id=e.staff_id,
                       staff_name=db.get(Staff, e.staff_id).name if e.staff_id else None, pay_type=e.pay_type,
                       pay_rate=e.pay_rate, active=e.active, balance=balance(db, e.id), paid_to=paid_to,
                       shortages=_shortages(db, e))


def _check_staff(db: Db, actor: Actor, staff_id: uuid.UUID | None, employee_id: uuid.UUID | None = None) -> None:
    if not staff_id:
        return
    s = db.get(Staff, staff_id)
    if s is None or s.business_id != actor.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Staff not found.")
    other = db.scalar(select(Employee.name).where(Employee.business_id == actor.business_id, Employee.staff_id == staff_id,
                                                  Employee.active, Employee.id != employee_id))
    if other:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{s.name}'s PIN is already linked to {other}.")


@router.get("/employees")
def employees(actor: Owner, db: Db) -> list[EmployeeOut]:
    rows = db.scalars(select(Employee).where(Employee.business_id == actor.business_id)
                      .order_by(Employee.active.desc(), Employee.name))
    return [_out(db, e) for e in rows]


@router.post("/employees", status_code=status.HTTP_201_CREATED)
def add_employee(body: EmployeeIn, actor: Owner, db: Db) -> EmployeeOut:
    _check_staff(db, actor, body.staff_id)
    e = Employee(business_id=actor.business_id, created_by=actor.staff.id, **body.model_dump())
    db.add(e)
    db.flush()
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="payroll.employee_added",
                 entity_type="employee", entity_id=e.id, details=body.model_dump(mode="json"))
    db.commit()
    return _out(db, e)


@router.patch("/employees/{employee_id}")
def update_employee(employee_id: uuid.UUID, body: EmployeePatch, actor: Owner, db: Db) -> EmployeeOut:
    e = _employee(db, actor, employee_id)
    changes = body.model_dump(exclude_unset=True)
    if "staff_id" in changes:
        _check_staff(db, actor, body.staff_id, e.id)
    before = {k: str(getattr(e, k)) for k in changes}
    for k, v in changes.items():
        setattr(e, k, v)
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="payroll.employee_changed",
                 entity_type="employee", entity_id=e.id,
                 details={k: [before[k], str(v)] for k, v in changes.items() if before[k] != str(v)})
    db.commit()
    return _out(db, e)


class RemovedOut(BaseModel):
    deleted: bool  # False: they have a pay history, so they are kept as "no longer works here"


@router.delete("/employees/{employee_id}")
def remove_employee(employee_id: uuid.UUID, actor: Owner, db: Db) -> RemovedOut:
    """Someone added by mistake (nothing in their pay account) is deleted; anyone with a
    pay history is kept, marked as no longer working here, so the history adds up."""
    e = _employee(db, actor, employee_id)
    history = db.scalar(select(EmployeeEntry.id).where(EmployeeEntry.employee_id == e.id).limit(1)) is not None
    if history:
        e.active = False
    else:
        db.delete(e)
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="payroll.employee_removed",
                 entity_type="employee", entity_id=e.id, details={"employee": e.name, "deleted": not history})
    db.commit()
    return RemovedOut(deleted=not history)


# The pay account


class EntryOut(BaseModel):
    id: uuid.UUID
    kind: EntryKind
    amount: int
    balance: int  # after this entry
    note: str | None
    business_day: date
    period_start: date | None
    period_end: date | None
    reversed: bool
    by: str | None
    at: datetime


@router.get("/employees/{employee_id}/entries")
def entries(employee_id: uuid.UUID, actor: Owner, db: Db) -> list[EntryOut]:
    """The pay account, oldest first, with the balance after each line."""
    e = _employee(db, actor, employee_id)
    rows = list(db.scalars(select(EmployeeEntry).where(EmployeeEntry.employee_id == e.id).order_by(EmployeeEntry.created_at)))
    reversed_ids = {r.reverses_id for r in rows if r.reverses_id}
    names = {s.id: s.name for s in db.scalars(select(Staff).where(Staff.business_id == actor.business_id))}
    out, running = [], 0
    for r in rows:
        running += r.amount
        out.append(EntryOut(id=r.id, kind=r.kind, amount=r.amount, balance=running, note=r.note, business_day=r.business_day,
                            period_start=r.period_start, period_end=r.period_end, reversed=r.id in reversed_ids,
                            by=names.get(r.created_by), at=r.created_at))
    return out


class DaysOut(BaseModel):
    days_worked: int | None  # days with a shift, if the employee has a PIN


@router.get("/employees/{employee_id}/days")
def days_worked(employee_id: uuid.UUID, start: date, end: date, actor: Owner, db: Db) -> DaysOut:
    """For a daily wage: the business days the linked PIN had a shift in the period."""
    e = _employee(db, actor, employee_id)
    if not e.staff_id:
        return DaysOut(days_worked=None)
    return DaysOut(days_worked=db.scalar(select(func.count(func.distinct(Shift.business_day)))
                                         .where(Shift.staff_id == e.staff_id, Shift.business_day.between(start, end))))


class MoneyOutIn(BaseModel):
    amount: Money
    paid_how: PaidHow = PaidHow.cash_box
    reference: Annotated[str, Field(max_length=40)] | None = None
    note: Note | None = None


@router.post("/employees/{employee_id}/advances", status_code=status.HTTP_201_CREATED)
def advance(employee_id: uuid.UUID, body: MoneyOutIn, actor: Owner, request: Request, db: Db) -> EmployeeOut:
    """Money given before pay day: it comes off the next pay."""
    e = _employee(db, actor, employee_id)
    expense = _paid_out(db, actor, request, e, body.amount, body.paid_how, body.reference,
                        f"Advance: {e.name}" + (f" ({body.note})" if body.note else ""))
    _entry(db, actor, e, EntryKind.advance, -body.amount, request, note=body.note, expense_id=expense.id)
    db.commit()
    if body.paid_how is PaidHow.cash_box:
        request.app.state.printing.open_drawer()
    return _out(db, e)


class DeductionIn(BaseModel):
    amount: Money
    note: Annotated[str, Field(min_length=1, max_length=200)]  # why: "Broke 3 glasses"


@router.post("/employees/{employee_id}/deductions", status_code=status.HTTP_201_CREATED)
def deduction(employee_id: uuid.UUID, body: DeductionIn, actor: Owner, request: Request, db: Db) -> EmployeeOut:
    e = _employee(db, actor, employee_id)
    _entry(db, actor, e, EntryKind.deduction, -body.amount, request, note=body.note)
    db.commit()
    return _out(db, e)


class PayIn(BaseModel):
    period_start: date
    period_end: date
    earned: Annotated[int, Field(ge=0, le=10_000_000)]  # salary for the period, before deductions
    paid: Annotated[int, Field(ge=0, le=10_000_000)]  # handed over now (the rest stays in the balance)
    paid_how: PaidHow = PaidHow.cash_box
    reference: Annotated[str, Field(max_length=40)] | None = None
    note: Note | None = None


@router.post("/employees/{employee_id}/pay", status_code=status.HTTP_201_CREATED)
def pay(employee_id: uuid.UUID, body: PayIn, actor: Owner, request: Request, db: Db) -> EmployeeOut:
    """Pay day: the salary earned for the period goes in, what is handed over goes out.
    Advances, deductions and shortages already in the account come off."""
    e = _employee(db, actor, employee_id)
    if body.period_end < body.period_start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The period ends before it starts.")
    if body.paid > balance(db, e.id) + body.earned:
        raise HTTPException(status.HTTP_409_CONFLICT, f"That is more than {e.name} is owed.")
    period = f"{body.period_start:%d %b} to {body.period_end:%d %b %Y}"
    _entry(db, actor, e, EntryKind.salary, body.earned, request, period_start=body.period_start,
           period_end=body.period_end, note=body.note or f"Salary {period}")
    if body.paid:
        expense = _paid_out(db, actor, request, e, body.paid, body.paid_how, body.reference, f"Salary: {e.name}, {period}")
        _entry(db, actor, e, EntryKind.payment, -body.paid, request, expense_id=expense.id, note=f"Paid, {period}")
    db.commit()
    if body.paid and body.paid_how is PaidHow.cash_box:
        request.app.state.printing.open_drawer()
    return _out(db, e)


@router.post("/entries/{entry_id}/reverse", status_code=status.HTTP_201_CREATED)
def reverse_entry(entry_id: uuid.UUID, actor: Owner, request: Request, db: Db) -> EmployeeOut:
    """Undo a mistaken line with a visible reversal (and its expense, giving cash back to
    the box). A shortage is undone by changing its status in Shifts instead."""
    r = db.get(EmployeeEntry, entry_id)
    if r is None or r.business_id != actor.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found.")
    if r.kind in (EntryKind.reversal, EntryKind.shortage) or db.scalar(select(EmployeeEntry.id).where(EmployeeEntry.reverses_id == r.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This line can't be reversed here.")
    e = db.get(Employee, r.employee_id)
    if r.expense_id:
        reverse(db, actor, request, db.get(Expense, r.expense_id))
    _entry(db, actor, e, EntryKind.reversal, -r.amount, request, reverses_id=r.id, note=f"Reversed: {r.note or r.kind.value}")
    db.commit()
    return _out(db, e)
