import uuid
from collections import OrderedDict
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import Actor
from app.auth.permissions import Action, Level, level
from app.floor.models import Bill, BillLine, BillStatus, Table
from app.payments.models import Payment
from app.printing import layouts
from app.printing.models import PrinterName, Ticket, TicketKind
from app.settings.service import business_name
from app.staff.models import Staff


def display_name(item_name: str, option_label: str) -> str:
    """"Tusker" for a single-option item, "Johnnie Walker Red - Single tot" otherwise."""
    return f"{item_name} - {option_label}" if option_label else item_name


def place(db: Session, bill: Bill) -> str:
    if bill.table_id:
        return db.get(Table, bill.table_id).name
    return f"Tab - {bill.tab_name}"


def load_bill(db: Session, actor: Actor, bill_id: uuid.UUID, action: Action, *, open_only: bool = True) -> Bill:
    """Fetch a bill the actor may act on. Waiters may only touch their own bills."""
    bill = db.get(Bill, bill_id, with_for_update=open_only)
    if bill is None or bill.business_id != actor.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found.")
    role_level = level(actor.staff.role, action)
    if role_level is Level.deny:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have permission to do this.")
    if role_level is not Level.allow and bill.waiter_id != actor.staff.id:
        owner = db.get(Staff, bill.waiter_id).name
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"This is {owner}'s bill.")
    if open_only and bill.status is not BillStatus.open:
        raise HTTPException(status.HTTP_409_CONFLICT, "This bill is already closed.")
    return bill


def bill_lines(db: Session, bill: Bill) -> list[BillLine]:
    return list(db.scalars(
        select(BillLine).where(BillLine.bill_id == bill.id).order_by(BillLine.created_at, BillLine.id)
    ))


def totals(db: Session, bill: Bill) -> tuple[int, int, int]:
    """(total, paid, tips). Voided lines don't count; tips are not part of the bill."""
    total = db.scalar(
        select(func.coalesce(func.sum(BillLine.unit_price), 0))
        .where(BillLine.bill_id == bill.id, BillLine.voided_at.is_(None))
    )
    paid, tips = db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0), func.coalesce(func.sum(Payment.tip), 0))
        .where(Payment.bill_id == bill.id)
    ).one()
    return total, paid, tips


def table_has_open_bill(db: Session, business_id: uuid.UUID, table_id: uuid.UUID) -> Bill | None:
    return db.scalar(
        select(Bill).where(
            Bill.business_id == business_id, Bill.table_id == table_id, Bill.status == BillStatus.open
        ).limit(1)
    )


def group_items(lines: list[BillLine]) -> list[layouts.ItemRow]:
    """Identical lines (same item, option, price and note) print as one row: "2 x Tusker"."""
    groups: OrderedDict[tuple, layouts.ItemRow] = OrderedDict()
    for line in lines:
        key = (line.item_name, line.option_label, line.unit_price, line.note)
        if key in groups:
            groups[key].quantity += 1
            groups[key].amount += line.unit_price
        else:
            groups[key] = layouts.ItemRow(1, display_name(line.item_name, line.option_label), line.note, line.unit_price)
    return list(groups.values())


@dataclass
class Printing:
    tz: ZoneInfo

    def header(self, db: Session, bill: Bill, when) -> layouts.Header:
        return layouts.Header(
            business=business_name(db, bill.business_id),
            place=place(db, bill),
            waiter=db.get(Staff, bill.waiter_id).name,
            when=when.astimezone(self.tz),
            bill_number=bill.number,
        )

    def new_ticket(
        self, db: Session, actor: Actor, bill: Bill, kind: TicketKind, printer: PrinterName,
        content: list, number: int, copies: list | None = None,
    ) -> Ticket:
        ticket = Ticket(
            business_id=bill.business_id, created_by=actor.staff.id, bill_id=bill.id, kind=kind,
            number=number, printer=printer, content=content, copies=copies or [None],
        )
        db.add(ticket)
        db.flush()
        return ticket
