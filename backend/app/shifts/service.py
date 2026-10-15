"""Shifts and the cash-up (masterplan 4.6).

Who owes what is worked out from two facts recorded as things happen:
- a bill's sale belongs to the shift of the waiter who finished it (`finished_shift_id`);
- a cash payment is in the hands of whoever took it (`Payment.shift_id`).
Normally both are the same waiter, and the cash-up reduces to the masterplan table.
When someone else took cash on a waiter's bill (e.g. before a hand-over), it moves
from one cash-up to the other, so nobody is charged for cash they never held.
"""

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db import now
from app.floor.models import Bill, BillStatus
from app.floor.service import amounts
from app.payments.models import Method, Payment
from app.settings.service import today
from app.shifts.models import Shift, ShiftStatus

FINISHED = (BillStatus.paid, BillStatus.credit, BillStatus.unpaid_responsible)


def open_shift(db: Session, business_id: uuid.UUID, staff_id: uuid.UUID) -> Shift | None:
    return db.scalar(
        select(Shift).where(Shift.business_id == business_id, Shift.staff_id == staff_id,
                            Shift.status == ShiftStatus.open)
    )


def current_shift(db: Session, business_id: uuid.UUID, staff_id: uuid.UUID, tz: ZoneInfo) -> Shift:
    """The person's open shift, starting one if they have none."""
    if shift := open_shift(db, business_id, staff_id):
        return shift
    db.execute(
        insert(Shift)
        .values(id=uuid.uuid4(), business_id=business_id, created_by=staff_id, created_at=now(),
                staff_id=staff_id, business_day=today(db, business_id, tz), status=ShiftStatus.open,
                float_amount=0, sync_status="pending")
        .on_conflict_do_nothing()
    )
    return open_shift(db, business_id, staff_id)


@dataclass
class MpesaRow:
    bill_number: int
    amount: int
    tip: int
    ref: str | None
    at: datetime


@dataclass
class CashUp:
    bills: int
    total_sales: int  # every bill finished: paid, credit, or unpaid (responsible)
    mpesa: int  # M-Pesa bill amounts only, tips excluded
    credit: int
    cash_taken_by_others: int  # cash someone else took on this person's bills
    cash_due_from_sales: int
    unpaid_responsible: int  # included in cash due
    cash_taken_for_others: int  # cash this person took on other people's bills
    float_amount: int
    mpesa_tips: int  # paid to the till, so taken out of the cash in hand
    cash_to_hand_over: int
    mpesa_payments: list[MpesaRow] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        for row in d["mpesa_payments"]:
            row["at"] = row["at"].isoformat()
        return d


def cash_up(db: Session, shift: Shift) -> CashUp:
    bills = list(db.scalars(
        select(Bill).where(Bill.finished_shift_id == shift.id, Bill.status.in_(FINISHED))
        .order_by(Bill.number)
    ))
    bill_ids = {b.id for b in bills}
    numbers = {b.id: b.number for b in bills}
    on_my_bills = list(db.scalars(
        select(Payment).where(Payment.bill_id.in_(bill_ids), Payment.reversed_at.is_(None))
        .order_by(Payment.created_at)
    )) if bill_ids else []
    taken_by_me = list(db.scalars(
        select(Payment).where(Payment.shift_id == shift.id, Payment.reversed_at.is_(None))
    ))

    total_sales = credit = unpaid = 0
    for bill in bills:
        a = amounts(db, bill)
        total_sales += a.total
        if bill.status is BillStatus.credit:
            credit += bill.credit_amount
        elif bill.status is BillStatus.unpaid_responsible:
            unpaid += a.balance

    mpesa = sum(p.amount for p in on_my_bills if p.method is Method.mpesa)
    by_others = sum(p.amount for p in on_my_bills if p.method is Method.cash and p.shift_id not in (shift.id, None))
    for_others = sum(p.amount for p in taken_by_me if p.method is Method.cash and p.bill_id not in bill_ids)
    tips = sum(p.tip for p in taken_by_me)

    cash_due = total_sales - mpesa - credit - by_others
    return CashUp(
        bills=len(bills),
        total_sales=total_sales,
        mpesa=mpesa,
        credit=credit,
        cash_taken_by_others=by_others,
        cash_due_from_sales=cash_due,
        unpaid_responsible=unpaid,
        cash_taken_for_others=for_others,
        float_amount=shift.float_amount,
        mpesa_tips=tips,
        cash_to_hand_over=cash_due + for_others + shift.float_amount - tips,
        mpesa_payments=[
            MpesaRow(numbers[p.bill_id], p.amount, p.tip, p.mpesa_ref, p.created_at)
            for p in on_my_bills if p.method is Method.mpesa
        ],
    )


def open_bills_of(db: Session, business_id: uuid.UUID, staff_id: uuid.UUID) -> list[Bill]:
    return list(db.scalars(
        select(Bill).where(Bill.business_id == business_id, Bill.waiter_id == staff_id,
                           Bill.status == BillStatus.open).order_by(Bill.number)
    ))
