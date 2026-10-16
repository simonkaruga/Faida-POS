import uuid
from collections import OrderedDict
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import Actor
from app.auth.permissions import Action, Level, level
from app.db import now
from app.floor.models import Bill, BillLine, BillStatus, DiscountKind, Table
from app.payments.models import Payment
from app.printing import layouts
from app.printing.models import PrinterName, Ticket, TicketKind
from app.settings.service import business_name
from app.staff.models import Staff


def display_name(item_name: str, option_label: str) -> str:
    """"Tusker" for a single-option item, "Johnnie Walker Red - Single tot" otherwise."""
    return f"{item_name} - {option_label}" if option_label else item_name


def place(db: Session, bill: Bill) -> str:
    """Where the order is: its table if it has one, else its number ("Order #0031")."""
    if bill.table_id:
        return db.get(Table, bill.table_id).name
    if bill.table_label:
        return f"Table {bill.table_label}"
    if bill.tab_name:
        return f"Tab - {bill.tab_name}"
    return f"Order #{bill.number:04d}"


def find_table(db: Session, business_id, label: str) -> Table | None:
    """A typed table number matched to one set up in Tables & sections ("7" finds "T7")."""
    wanted = label.strip().lower()
    for table in db.scalars(select(Table).where(Table.business_id == business_id, Table.active)):
        name = table.name.lower()
        if wanted in (name, name.removeprefix("t"), name.removeprefix("table ").strip()):
            return table
    return None


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


@dataclass
class Amounts:
    gross: int  # sum of items still on the bill (not voided, not given free)
    discount: int
    total: int  # gross - discount: what the customer owes, and the sale
    paid: int
    tips: int

    @property
    def balance(self) -> int:
        return self.total - self.paid


def discount_on(bill: Bill, gross: int) -> int:
    if bill.discount_kind is DiscountKind.amount:
        return min(bill.discount_value, gross)
    if bill.discount_kind is DiscountKind.percent:
        return round(gross * bill.discount_value / 100)
    return 0


def amounts(db: Session, bill: Bill) -> Amounts:
    """Voided lines don't count, reversed payments don't count, tips are not part of the bill."""
    gross = db.scalar(
        select(func.coalesce(func.sum(BillLine.unit_price), 0))
        .where(BillLine.bill_id == bill.id, BillLine.voided_at.is_(None), BillLine.comp_reason.is_(None))
    )
    paid, tips = db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0), func.coalesce(func.sum(Payment.tip), 0))
        .where(Payment.bill_id == bill.id, Payment.reversed_at.is_(None))
    ).one()
    discount = discount_on(bill, gross)
    return Amounts(gross=gross, discount=discount, total=gross - discount, paid=paid, tips=tips)


def totals(db: Session, bill: Bill) -> tuple[int, int, int]:
    """(total after discount, paid, tips)."""
    a = amounts(db, bill)
    return a.total, a.paid, a.tips


def finish_bill(db: Session, bill: Bill, status: BillStatus, tz: ZoneInfo) -> None:
    """Close a bill as paid, on credit or unpaid. Its sale counts in the cash-up of the
    shift of the waiter it belongs to now."""
    from app.shifts.service import current_shift  # here: shifts.service imports this module

    bill.status, bill.closed_at = status, now()
    bill.finished_shift_id = current_shift(db, bill.business_id, bill.waiter_id, tz).id


def table_has_open_bill(db: Session, business_id: uuid.UUID, table_id: uuid.UUID) -> Bill | None:
    return db.scalar(
        select(Bill).where(
            Bill.business_id == business_id, Bill.table_id == table_id, Bill.status == BillStatus.open
        ).limit(1)
    )


COMP_LABEL = {
    "house": "On the house",
    "staff_drink": "Staff drink",
    "owner_guest": "Owner's guest",
    "complaint": "Complaint",
    "promotion": "Promotion",
}


def charged(line: BillLine) -> int:
    """What a line adds to the bill: nothing once voided or given free."""
    return 0 if line.voided_at or line.comp_reason else line.unit_price


def group_items(lines: list[BillLine], *, for_customer: bool = False) -> list[layouts.ItemRow]:
    """Identical lines print as one row: "2 x Tusker". Modifiers print under the item.

    For the customer (bill, receipt) a combo is one priced line with its parts hidden,
    and happy hour or free items say so; for a station slip, every part is listed."""
    groups: OrderedDict[tuple, layouts.ItemRow] = OrderedDict()
    for line in lines:
        if for_customer and line.combo_parent_id:
            continue
        extras = [f"+ {m['label']}" + (f"  {m['price']:,}" if m.get("price") else "") for m in line.modifiers or []]
        if for_customer and line.price_rule and line.list_price:
            extras.append(f"{line.price_rule} (was {line.list_price:,})")
        if for_customer and line.comp_reason:
            extras.append(f"{COMP_LABEL[line.comp_reason.value]} (free)")
        key = (line.item_name, line.option_label, line.unit_price, line.note, tuple(extras))
        if key in groups:
            groups[key].quantity += 1
            groups[key].amount += charged(line)
        else:
            groups[key] = layouts.ItemRow(1, display_name(line.item_name, line.option_label), line.note,
                                          charged(line), extras)
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
