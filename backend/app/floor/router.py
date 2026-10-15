import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.audit import service as audit
from app.auth import service as auth
from app.auth.deps import Actor, CurrentActor, Db, require
from app.auth.permissions import Action, Level, level
from app.db import now
from app.floor.models import Bill, BillHandover, BillLine, BillStatus, DiscountKind, Table, VoidReason
from app.floor.schemas import BillOut, Person, bill_detail
from app.floor.service import (
    Printing, amounts, bill_lines, group_items, load_bill, place, table_has_open_bill, totals,
)
from app.menu.models import MenuItem, SellOption, Station
from app.printing import layouts
from app.printing.models import PrinterName, PrintStatus, Ticket, TicketKind
from app.sequences import next_number
from app.payments.models import Payment
from app.settings.service import get_settings, today
from app.shifts.models import Shift, ShiftStatus
from app.shifts.service import current_shift
from app.staff.models import Staff
from app.stock import service as stock

router = APIRouter(tags=["floor"])

Owner = Annotated[Actor, Depends(require(Action.manage_business))]


def _printing(request: Request) -> Printing:
    return Printing(request.app.state.tz)


# Tables


class TableOut(BaseModel):
    id: uuid.UUID
    name: str


class TableIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=30)]
    sort_order: int = 0


class TablePatch(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=30)] | None = None
    sort_order: int | None = None
    active: bool | None = None


@router.post("/tables", status_code=status.HTTP_201_CREATED)
def create_table(body: TableIn, actor: Owner, db: Db) -> TableOut:
    table = Table(business_id=actor.business_id, created_by=actor.staff.id, **body.model_dump())
    db.add(table)
    db.flush()
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="table.created",
                 entity_type="table", entity_id=table.id, details={"name": table.name})
    db.commit()
    return TableOut(id=table.id, name=table.name)


@router.patch("/tables/{table_id}", status_code=status.HTTP_204_NO_CONTENT)
def update_table(table_id: uuid.UUID, body: TablePatch, actor: Owner, db: Db) -> None:
    table = db.get(Table, table_id)
    if table is None or table.business_id != actor.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Table not found.")
    changes = {}
    for field, new in body.model_dump(exclude_unset=True).items():
        if new is not None and getattr(table, field) != new:
            changes[field] = [str(getattr(table, field)), str(new)]
            setattr(table, field, new)
    if changes:
        audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="table.updated",
                     entity_type="table", entity_id=table.id, details=changes)
        db.commit()


# The floor: the waiter's home screen


class FloorBill(BaseModel):
    id: uuid.UUID
    number: int
    place: str
    table_id: uuid.UUID | None
    tab_name: str | None
    waiter: Person
    mine: bool
    # Hidden on other waiters' bills for a waiter (shown grey and locked).
    total: int | None
    balance: int | None
    not_printed: bool | None


class FloorOut(BaseModel):
    tables: list[TableOut]
    bills: list[FloorBill]


@router.get("/floor")
def floor(actor: CurrentActor, db: Db) -> FloorOut:
    bid = actor.business_id
    tables = db.scalars(
        select(Table).where(Table.business_id == bid, Table.active).order_by(Table.sort_order, Table.name)
    )
    sees_all = level(actor.staff.role, Action.view_other_bills) is Level.allow
    bills = []
    for bill in db.scalars(
        select(Bill).where(Bill.business_id == bid, Bill.status == BillStatus.open).order_by(Bill.number)
    ):
        mine = bill.waiter_id == actor.staff.id
        visible = mine or sees_all
        total, paid, _ = totals(db, bill) if visible else (None, None, None)
        unprinted = visible and db.scalar(
            select(Ticket.id).where(Ticket.bill_id == bill.id, Ticket.status == PrintStatus.not_printed,
                                    Ticket.kind != TicketKind.bill).limit(1)
        ) is not None
        waiter = db.get(Staff, bill.waiter_id)
        bills.append(FloorBill(
            id=bill.id, number=bill.number, place=place(db, bill), table_id=bill.table_id,
            tab_name=bill.tab_name, waiter=Person(id=waiter.id, name=waiter.name), mine=mine,
            total=total, balance=None if total is None else total - paid,
            not_printed=unprinted if visible else None,
        ))
    return FloorOut(tables=[TableOut(id=t.id, name=t.name) for t in tables], bills=bills)


# Bills


class OpenBill(BaseModel):
    table_id: uuid.UUID | None = None
    tab_name: Annotated[str, Field(min_length=1, max_length=40)] | None = None

    @model_validator(mode="after")
    def one_place(self):
        if (self.table_id is None) == (self.tab_name is None):
            raise ValueError("Give either a table or a tab name.")
        return self


@router.post("/bills", status_code=status.HTTP_201_CREATED)
def open_bill(body: OpenBill, actor: Annotated[Actor, Depends(require(Action.open_bill))], request: Request, db: Db) -> BillOut:
    if body.table_id:
        table = db.get(Table, body.table_id)
        if table is None or table.business_id != actor.business_id or not table.active:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Table not found.")
        if existing := table_has_open_bill(db, actor.business_id, table.id):
            owner = db.get(Staff, existing.waiter_id).name
            raise HTTPException(status.HTTP_409_CONFLICT, f"{table.name} already has an open bill ({owner}).")
    bill = Bill(
        business_id=actor.business_id, created_by=actor.staff.id,
        number=next_number(db, actor.business_id, "bill"),
        table_id=body.table_id, tab_name=body.tab_name.strip() if body.tab_name else None,
        waiter_id=actor.staff.id, business_day=today(db, actor.business_id, request.app.state.tz),
    )
    db.add(bill)
    current_shift(db, actor.business_id, actor.staff.id, request.app.state.tz)
    db.commit()
    return bill_detail(db, bill)


@router.get("/bills/{bill_id}")
def get_bill(bill_id: uuid.UUID, actor: CurrentActor, db: Db) -> BillOut:
    return bill_detail(db, load_bill(db, actor, bill_id, Action.open_bill, open_only=False))


class RoundItem(BaseModel):
    sell_option_id: uuid.UUID
    quantity: Annotated[int, Field(ge=1, le=50)] = 1
    note: Annotated[str, Field(max_length=120)] | None = None


class SendIn(BaseModel):
    items: list[RoundItem] = Field(min_length=1, max_length=100)


@router.post("/bills/{bill_id}/send")
def send(bill_id: uuid.UUID, body: SendIn, actor: CurrentActor, request: Request, db: Db) -> BillOut:
    """SEND a round: drinks print on a bar slip at the counter, food on a kitchen ticket.

    Prices are taken from the menu now and fixed on the bill. The round is saved even
    if a printer is down; its ticket then shows "Not printed".
    """
    bill = load_bill(db, actor, bill_id, Action.open_bill)
    options = {
        o.id: (o, i)
        for o, i in db.execute(
            select(SellOption, MenuItem).join(MenuItem, MenuItem.id == SellOption.menu_item_id)
            .where(SellOption.id.in_({it.sell_option_id for it in body.items}),
                   SellOption.business_id == actor.business_id, SellOption.active, MenuItem.active)
        )
    }
    if {it.sell_option_id for it in body.items} - options.keys():
        raise HTTPException(status.HTTP_409_CONFLICT, "An item is no longer on the menu. Refresh and try again.")

    printing, sent_at = _printing(request), now()
    header = printing.header(db, bill, sent_at)
    tickets, sent = [], []
    for station, kind, printer, layout in (
        (Station.bar, TicketKind.bar_slip, PrinterName.counter, layouts.bar_slip),
        (Station.kitchen, TicketKind.kitchen_ticket, PrinterName.kitchen, layouts.kitchen_ticket),
    ):
        items = [it for it in body.items if options[it.sell_option_id][1].station is station]
        if not items:
            continue
        number = next_number(db, actor.business_id, kind.value)
        ticket = printing.new_ticket(db, actor, bill, kind, printer, content=[], number=number)
        lines = []
        for it in items:
            option, item = options[it.sell_option_id]
            note = it.note.strip() if it.note and it.note.strip() else None
            for _ in range(it.quantity):
                lines.append(BillLine(
                    business_id=actor.business_id, created_by=actor.staff.id, created_at=sent_at,
                    bill_id=bill.id, sell_option_id=option.id, item_name=item.name,
                    option_label=option.label, station=station, unit_price=option.price,
                    note=note, ticket_id=ticket.id,
                ))
        db.add_all(lines)
        ticket.content = layout(header, number, group_items(lines))
        tickets.append(ticket)
        sent.extend(lines)
    db.flush()
    stock.record_sale(db, sent, tot_size=get_settings(db, actor.business_id).tot_size_ml, actor_id=actor.staff.id,
                      day=today(db, actor.business_id, request.app.state.tz))
    db.commit()
    request.app.state.printing.print_tickets(tickets)
    return bill_detail(db, bill)


@router.post("/bills/{bill_id}/print")
def print_bill(bill_id: uuid.UUID, actor: CurrentActor, request: Request, db: Db) -> BillOut:
    """Print the bill for the customer. Can be printed as often as needed."""
    bill = load_bill(db, actor, bill_id, Action.open_bill)
    lines = [l for l in bill_lines(db, bill) if l.voided_at is None]
    if not lines:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing has been sent on this bill yet.")
    a = amounts(db, bill)
    printing = _printing(request)
    content = layouts.bill(printing.header(db, bill, now()), group_items(lines), a.gross, a.discount, a.paid,
                           get_settings(db, actor.business_id).mpesa_till_number)
    ticket = printing.new_ticket(db, actor, bill, TicketKind.bill, PrinterName.counter, content, bill.number)
    db.commit()
    request.app.state.printing.print_tickets([ticket])
    return bill_detail(db, bill)


class VoidIn(BaseModel):
    reason: VoidReason
    approval_id: uuid.UUID | None = None


@router.post("/bills/{bill_id}/lines/{line_id}/void")
def void_line(bill_id: uuid.UUID, line_id: uuid.UUID, body: VoidIn, actor: CurrentActor, request: Request, db: Db) -> BillOut:
    """Remove an item already sent. Waiters need an Owner or Supervisor PIN.
    "Not prepared" returns it to stock; "Already prepared" records it as waste (Phase 4)."""
    bill = load_bill(db, actor, bill_id, Action.void_item)
    line = db.get(BillLine, line_id)
    if line is None or line.bill_id != bill.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found on this bill.")
    if line.voided_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "This item was already removed.")
    approval = auth.authorize(db, actor, Action.void_item, body.approval_id)
    line.voided_at, line.voided_by, line.void_reason = now(), actor.staff.id, body.reason
    db.flush()
    if amounts(db, bill).balance < 0:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Payments already taken are more than the new total.")
    stock.reverse_sale(db, line, body.reason, actor_id=actor.staff.id,
                       day=today(db, actor.business_id, request.app.state.tz), note=f"Void, bill #{bill.number:04d}")
    audit.record(
        db, business_id=actor.business_id, actor_id=actor.staff.id, action="bill_line.voided",
        entity_type="bill_line", entity_id=line.id, approval=approval,
        details={"bill": bill.number, "item": line.item_name, "option": line.option_label,
                 "price": line.unit_price, "reason": body.reason.value},
    )
    db.commit()
    return bill_detail(db, bill)


class MoveIn(BaseModel):
    table_id: uuid.UUID


@router.post("/bills/{bill_id}/move")
def move_bill(bill_id: uuid.UUID, body: MoveIn, actor: CurrentActor, db: Db) -> BillOut:
    bill = load_bill(db, actor, bill_id, Action.move_bill_table)
    table = db.get(Table, body.table_id)
    if table is None or table.business_id != actor.business_id or not table.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Table not found.")
    if table_has_open_bill(db, actor.business_id, table.id):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{table.name} already has an open bill.")
    before = place(db, bill)
    bill.table_id, bill.tab_name = table.id, None
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="bill.moved",
                 entity_type="bill", entity_id=bill.id,
                 details={"bill": bill.number, "from": before, "to": table.name})
    db.commit()
    return bill_detail(db, bill)


class HandoverIn(BaseModel):
    to_pin: Annotated[str, Field(min_length=1, max_length=12)]


@router.post("/bills/{bill_id}/handover")
def hand_over(bill_id: uuid.UUID, body: HandoverIn, actor: CurrentActor, request: Request, db: Db) -> BillOut:
    """The receiving waiter types their PIN to accept the bill and its money."""
    bill = load_bill(db, actor, bill_id, Action.hand_over_bill)
    state = request.app.state
    receiver = auth.find_staff_by_pin(db, state.keypad, state.config.pin_secret, actor.business_id, body.to_pin)
    if receiver.id == bill.waiter_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "This bill is already theirs.")
    giver = bill.waiter_id
    db.add(BillHandover(business_id=actor.business_id, created_by=actor.staff.id, bill_id=bill.id,
                        from_waiter_id=giver, to_waiter_id=receiver.id))
    bill.waiter_id = receiver.id
    current_shift(db, actor.business_id, receiver.id, state.tz)
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="bill.handed_over",
                 entity_type="bill", entity_id=bill.id,
                 details={"bill": bill.number, "from": str(giver), "to": str(receiver.id), "to_name": receiver.name})
    db.commit()
    return bill_detail(db, bill)


class MergeIn(BaseModel):
    from_bill_id: uuid.UUID


@router.post("/bills/{bill_id}/merge")
def merge(bill_id: uuid.UUID, body: MergeIn, actor: CurrentActor, db: Db) -> BillOut:
    """Move every item from another bill of the same waiter onto this one."""
    if body.from_bill_id == bill_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a different bill.")
    target = load_bill(db, actor, bill_id, Action.open_bill)
    source = load_bill(db, actor, body.from_bill_id, Action.open_bill)
    if source.waiter_id != target.waiter_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only bills of the same waiter can be merged.")
    if totals(db, source)[1]:
        raise HTTPException(status.HTTP_409_CONFLICT, "That bill already has payments. Finish paying it first.")
    for line in bill_lines(db, source):
        line.bill_id = target.id
    for ticket in db.scalars(select(Ticket).where(Ticket.bill_id == source.id)):
        ticket.bill_id = target.id
    source.status, source.merged_into_id, source.closed_at = BillStatus.merged, target.id, now()
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="bill.merged",
                 entity_type="bill", entity_id=target.id,
                 details={"into": target.number, "from": source.number})
    db.commit()
    return bill_detail(db, target)


class SplitIn(BaseModel):
    line_ids: list[uuid.UUID] = Field(min_length=1)


@router.post("/bills/{bill_id}/split", status_code=status.HTTP_201_CREATED)
def split(bill_id: uuid.UUID, body: SplitIn, actor: CurrentActor, request: Request, db: Db) -> BillOut:
    """Move the chosen items to a new bill at the same place, for the same waiter."""
    bill = load_bill(db, actor, bill_id, Action.open_bill)
    lines = {l.id: l for l in bill_lines(db, bill) if l.voided_at is None}
    chosen = set(body.line_ids)
    if not chosen <= lines.keys():
        raise HTTPException(status.HTTP_409_CONFLICT, "Some items are not on this bill.")
    if chosen == lines.keys():
        raise HTTPException(status.HTTP_409_CONFLICT, "Leave at least one item on this bill.")
    new = Bill(
        business_id=actor.business_id, created_by=actor.staff.id,
        number=next_number(db, actor.business_id, "bill"), table_id=bill.table_id,
        tab_name=bill.tab_name, waiter_id=bill.waiter_id,
        business_day=today(db, actor.business_id, request.app.state.tz),
    )
    db.add(new)
    db.flush()
    for i in chosen:
        lines[i].bill_id = new.id
    db.flush()
    if amounts(db, bill).balance < 0:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Payments already taken are more than what would be left.")
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="bill.split",
                 entity_type="bill", entity_id=new.id,
                 details={"from": bill.number, "new": new.number, "items": len(chosen)})
    db.commit()
    return bill_detail(db, new)


@router.post("/bills/{bill_id}/close-empty")
def close_empty(bill_id: uuid.UUID, actor: CurrentActor, db: Db) -> BillOut:
    """Close a bill with nothing left on it: opened by mistake, or every item voided."""
    bill = load_bill(db, actor, bill_id, Action.open_bill)
    total, paid, _ = totals(db, bill)
    if total or paid:
        raise HTTPException(status.HTTP_409_CONFLICT, "This bill still has items or payments.")
    bill.status, bill.closed_at = BillStatus.cancelled, now()
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="bill.closed_empty",
                 entity_type="bill", entity_id=bill.id, details={"bill": bill.number})
    db.commit()
    return bill_detail(db, bill)


class ReprintIn(BaseModel):
    approval_id: uuid.UUID | None = None


@router.post("/tickets/{ticket_id}/reprint")
def reprint(ticket_id: uuid.UUID, body: ReprintIn, actor: CurrentActor, request: Request, db: Db) -> BillOut:
    """Reprint a slip, kitchen ticket or receipt.

    Printing one that never came out (printer was offline) needs no approval. Printing
    one that already came out again needs an Owner or Supervisor PIN for a waiter, so a
    second slip can't be used to pour a second drink.
    """
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or ticket.business_id != actor.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Printout not found.")
    bill = load_bill(db, actor, ticket.bill_id, Action.open_bill, open_only=False)
    already_out = ticket.printed_at is not None
    approval = None
    if already_out and ticket.kind is not TicketKind.bill:
        approval = auth.authorize(db, actor, Action.reprint_receipt, body.approval_id)
    ticket.reprints += 1
    ticket.status = PrintStatus.pending
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="ticket.reprinted",
                 entity_type="ticket", entity_id=ticket.id, approval=approval,
                 details={"bill": bill.number, "kind": ticket.kind.value, "number": ticket.number,
                          "was_printed": already_out})
    db.commit()
    request.app.state.printing.print_tickets([ticket], reprint=already_out)
    return bill_detail(db, bill)


class DiscountIn(BaseModel):
    kind: DiscountKind
    value: Annotated[int, Field(ge=0, le=1_000_000)]  # 0 removes the discount
    reason: Annotated[str, Field(min_length=1, max_length=120)]
    approval_id: uuid.UUID | None = None


@router.post("/bills/{bill_id}/discount")
def discount(bill_id: uuid.UUID, body: DiscountIn, actor: CurrentActor, db: Db) -> BillOut:
    """A discount on the whole bill: a fixed amount or a percentage. Waiters need an
    Owner or Supervisor PIN. Sales and the waiter's cash due are net of it."""
    bill = load_bill(db, actor, bill_id, Action.discount)
    if body.kind is DiscountKind.percent and body.value > 100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A percentage can't be more than 100.")
    approval = auth.authorize(db, actor, Action.discount, body.approval_id)
    before = amounts(db, bill).discount
    bill.discount_kind, bill.discount_value = (body.kind, body.value) if body.value else (None, 0)
    db.flush()
    after = amounts(db, bill)
    if after.balance < 0:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Payments already taken are more than the discounted total.")
    audit.record(
        db, business_id=actor.business_id, actor_id=actor.staff.id, action="bill.discounted",
        entity_type="bill", entity_id=bill.id, approval=approval,
        details={"bill": bill.number, "kind": body.kind.value, "value": body.value,
                 "amount": after.discount, "previous_amount": before, "reason": body.reason},
    )
    db.commit()
    return bill_detail(db, bill)


class CancelIn(BaseModel):
    reason: VoidReason  # what happens to the items: back to stock, or waste
    approval_id: uuid.UUID | None = None


@router.post("/bills/{bill_id}/cancel")
def cancel_paid(bill_id: uuid.UUID, body: CancelIn, actor: CurrentActor, request: Request, db: Db) -> BillOut:
    """Cancel a paid (or credit) bill: its payments are reversed, the money goes back to
    the customer, and its sale no longer counts. Possible only while the shift that
    finished it is still open; after the hand-over a refund is a pay-out."""
    bill = load_bill(db, actor, bill_id, Action.cancel_paid_bill, open_only=False)
    if bill.status not in (BillStatus.paid, BillStatus.credit):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a paid or credit bill can be cancelled.")
    shift = db.get(Shift, bill.finished_shift_id) if bill.finished_shift_id else None
    if shift is None or shift.status is not ShiftStatus.open:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This bill's shift has already been handed over. Record the refund as a pay-out.")
    approval = auth.authorize(db, actor, Action.cancel_paid_bill, body.approval_id)
    a = amounts(db, bill)
    refunded = {"cash": 0, "mpesa": 0}
    for p in db.scalars(select(Payment).where(Payment.bill_id == bill.id, Payment.reversed_at.is_(None))):
        p.reversed_at = now()
        refunded[p.method.value] += p.amount
    day = today(db, actor.business_id, request.app.state.tz)
    for line in bill_lines(db, bill):
        if line.voided_at is None:
            stock.reverse_sale(db, line, body.reason, actor_id=actor.staff.id, day=day,
                               note=f"Cancelled bill #{bill.number:04d}")
    was = bill.status
    bill.status, bill.cancel_reason = BillStatus.cancelled, body.reason
    audit.record(
        db, business_id=actor.business_id, actor_id=actor.staff.id, action="bill.cancelled",
        entity_type="bill", entity_id=bill.id, approval=approval,
        details={"bill": bill.number, "was": was.value, "total": a.total, "refund_cash": refunded["cash"],
                 "refund_mpesa": refunded["mpesa"], "credit": bill.credit_amount if was is BillStatus.credit else 0,
                 "reason": body.reason.value},
    )
    db.commit()
    return bill_detail(db, bill)


class FinishedBill(BaseModel):
    id: uuid.UUID
    number: int
    place: str
    waiter: Person
    status: BillStatus
    total: int
    closed_at: datetime | None


@router.get("/bills")
def finished_bills(actor: CurrentActor, request: Request, db: Db) -> list[FinishedBill]:
    """Bills already closed: a waiter's own from their current shift, or every bill of
    today's business day for an Owner or Supervisor. Used to reprint or cancel."""
    query = select(Bill).where(
        Bill.business_id == actor.business_id,
        Bill.status.in_((BillStatus.paid, BillStatus.credit, BillStatus.unpaid_responsible, BillStatus.cancelled)),
        Bill.finished_shift_id.is_not(None),  # leaves out bills closed empty
    )
    if level(actor.staff.role, Action.view_other_bills) is Level.allow:
        query = query.where(Bill.business_day == today(db, actor.business_id, request.app.state.tz))
    else:
        shift = db.scalar(select(Shift).where(Shift.staff_id == actor.staff.id, Shift.status == ShiftStatus.open))
        if shift is None:
            return []
        query = query.where(Bill.finished_shift_id == shift.id, Bill.waiter_id == actor.staff.id)
    rows = []
    for bill in db.scalars(query.order_by(Bill.closed_at.desc()).limit(200)):
        waiter = db.get(Staff, bill.waiter_id)
        rows.append(FinishedBill(id=bill.id, number=bill.number, place=place(db, bill),
                                 waiter=Person(id=waiter.id, name=waiter.name), status=bill.status,
                                 total=amounts(db, bill).total, closed_at=bill.closed_at))
    return rows
