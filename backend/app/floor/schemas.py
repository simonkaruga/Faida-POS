import uuid
from datetime import date, datetime

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.floor.models import Bill, BillStatus, VoidReason
from app.floor.service import bill_lines, place, totals
from app.menu.models import Station
from app.payments.models import Method, Payment
from app.printing.models import PrintStatus, Ticket, TicketKind
from app.staff.models import Staff


class Person(BaseModel):
    id: uuid.UUID
    name: str


class LineOut(BaseModel):
    id: uuid.UUID
    item_name: str
    option_label: str
    station: Station
    unit_price: int
    note: str | None
    sent_at: datetime
    ticket_id: uuid.UUID
    voided: bool
    void_reason: VoidReason | None


class TicketOut(BaseModel):
    id: uuid.UUID
    kind: TicketKind
    number: int
    status: PrintStatus
    created_at: datetime
    printed_at: datetime | None
    reprints: int
    last_error: str | None


class PaymentOut(BaseModel):
    id: uuid.UUID
    method: Method
    amount: int
    tendered: int | None
    tip: int
    mpesa_ref: str | None
    created_at: datetime
    taken_by: str


class BillOut(BaseModel):
    id: uuid.UUID
    number: int
    place: str
    table_id: uuid.UUID | None
    tab_name: str | None
    waiter: Person
    status: BillStatus
    business_day: date
    opened_at: datetime
    lines: list[LineOut]
    tickets: list[TicketOut]
    payments: list[PaymentOut]
    total: int
    paid: int
    balance: int
    tips: int


def bill_detail(db: Session, bill: Bill) -> BillOut:
    db.expire_all()  # print workers update tickets in their own sessions
    bill = db.get(Bill, bill.id)
    total, paid, tips = totals(db, bill)
    waiter = db.get(Staff, bill.waiter_id)
    tickets = db.scalars(select(Ticket).where(Ticket.bill_id == bill.id).order_by(Ticket.created_at))
    payments = db.execute(
        select(Payment, Staff.name).join(Staff, Staff.id == Payment.created_by)
        .where(Payment.bill_id == bill.id).order_by(Payment.created_at)
    )
    return BillOut(
        id=bill.id, number=bill.number, place=place(db, bill), table_id=bill.table_id,
        tab_name=bill.tab_name, waiter=Person(id=waiter.id, name=waiter.name), status=bill.status,
        business_day=bill.business_day, opened_at=bill.created_at,
        lines=[
            LineOut(
                id=l.id, item_name=l.item_name, option_label=l.option_label, station=l.station,
                unit_price=l.unit_price, note=l.note, sent_at=l.created_at, ticket_id=l.ticket_id,
                voided=l.voided_at is not None, void_reason=l.void_reason,
            )
            for l in bill_lines(db, bill)
        ],
        tickets=[TicketOut.model_validate(t, from_attributes=True) for t in tickets],
        payments=[
            PaymentOut(id=p.id, method=p.method, amount=p.amount, tendered=p.tendered, tip=p.tip,
                       mpesa_ref=p.mpesa_ref, created_at=p.created_at, taken_by=name)
            for p, name in payments
        ],
        total=total, paid=paid, balance=total - paid, tips=tips,
    )
