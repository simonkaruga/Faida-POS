import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.audit import service as audit
from app.auth import service as auth
from app.auth.deps import Actor, CurrentActor, Db, require
from app.auth.permissions import Action, Level, level
from app.db import now
from app.floor.models import BillStatus
from app.floor.schemas import Person
from app.floor.service import amounts, finish_bill, place
from app.printing import layouts
from app.printing.models import PrinterName, Ticket, TicketKind
from app.sequences import next_number
from app.settings.service import business_name, today
from app.shifts.models import (
    CashMovement, CashMovementKind, Handover, Shift, ShiftStatus, ShortageOutcome, ShortageStatus,
)
from app.shifts.service import cash_up, current_shift, open_bills_of, open_shift
from app.staff.models import Role, Staff

router = APIRouter(tags=["shifts"])

Receiver = Annotated[Actor, Depends(require(Action.receive_handover))]
OwnerOnly = Annotated[Actor, Depends(require(Action.force_close_shift))]

NOTES = ("1000", "500", "200", "100", "50")  # counted by number of notes; "coins" is an amount


class OpenBillOut(BaseModel):
    id: uuid.UUID
    number: int
    place: str
    balance: int


class ShiftOut(BaseModel):
    id: uuid.UUID
    staff: Person
    business_day: date
    started_at: datetime
    float_amount: int


class MyShift(BaseModel):
    shift: ShiftOut | None
    cash_up: dict | None
    open_bills: list[OpenBillOut]


def _shift_out(db: Db, shift: Shift) -> ShiftOut:
    staff = db.get(Staff, shift.staff_id)
    return ShiftOut(id=shift.id, staff=Person(id=staff.id, name=staff.name), business_day=shift.business_day,
                    started_at=shift.created_at, float_amount=shift.float_amount)


def _open_bills(db: Db, shift: Shift) -> list[OpenBillOut]:
    return [OpenBillOut(id=b.id, number=b.number, place=place(db, b), balance=amounts(db, b).balance)
            for b in open_bills_of(db, shift.business_id, shift.staff_id)]


def _get_shift(db: Db, actor: Actor, shift_id: uuid.UUID) -> Shift:
    shift = db.get(Shift, shift_id, with_for_update=True)
    if shift is None or shift.business_id != actor.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shift not found.")
    if shift.status is not ShiftStatus.open:
        raise HTTPException(status.HTTP_409_CONFLICT, "This shift is already closed.")
    return shift


@router.get("/shifts/me")
def my_shift(actor: CurrentActor, db: Db) -> MyShift:
    """End my shift, screens 1 and 2: open bills that block it, and the cash-up."""
    shift = open_shift(db, actor.business_id, actor.staff.id)
    if shift is None:
        return MyShift(shift=None, cash_up=None, open_bills=[])
    return MyShift(shift=_shift_out(db, shift), cash_up=cash_up(db, shift).as_dict(), open_bills=_open_bills(db, shift))


def _check_receiver(receiver: Staff, shift: Shift) -> None:
    if level(receiver.role, Action.receive_handover) is not Level.allow:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner or a supervisor can receive cash.")
    if receiver.id == shift.staff_id and receiver.role is not Role.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Someone else must receive your cash.")


def _check_actor(actor: Actor, shift: Shift) -> None:
    if actor.staff.id != shift.staff_id and level(actor.staff.role, Action.receive_handover) is not Level.allow:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This is not your shift.")


class PinIn(BaseModel):
    pin: Annotated[str, Field(min_length=1, max_length=12)]


class ReceiverOut(BaseModel):
    receiver: Person
    cash_up: dict


@router.post("/shifts/{shift_id}/receiver")
def check_receiver(shift_id: uuid.UUID, body: PinIn, actor: CurrentActor, request: Request, db: Db) -> ReceiverOut:
    """Screen 3 starts with the receiver's PIN; they then see each M-Pesa payment to tick off."""
    shift = _get_shift(db, actor, shift_id)
    _check_actor(actor, shift)
    state = request.app.state
    receiver = auth.find_staff_by_pin(db, state.keypad, state.config.pin_secret, actor.business_id, body.pin)
    _check_receiver(receiver, shift)
    return ReceiverOut(receiver=Person(id=receiver.id, name=receiver.name), cash_up=cash_up(db, shift).as_dict())


class CloseIn(BaseModel):
    receiver_pin: Annotated[str, Field(min_length=1, max_length=12)]
    counted_notes: dict[str, Annotated[int, Field(ge=0, le=100_000)]] | None = None
    received: Annotated[int, Field(ge=0, le=100_000_000)] | None = None
    receiver_note: Annotated[str, Field(max_length=200)] | None = None
    staff_pin: Annotated[str, Field(min_length=1, max_length=12)]
    agree: bool
    staff_note: Annotated[str, Field(max_length=200)] | None = None

    @model_validator(mode="after")
    def counted(self):
        if self.counted_notes is None and self.received is None:
            raise ValueError("Count the cash by note or type the total.")
        if self.counted_notes and set(self.counted_notes) - {*NOTES, "coins"}:
            raise ValueError("Unknown note.")
        if not self.agree and not (self.staff_note or "").strip():
            raise ValueError("Say why you disagree.")
        return self

    def total(self) -> int:
        if self.counted_notes is None:
            return self.received
        n = self.counted_notes
        return sum(int(note) * n.get(note, 0) for note in NOTES) + n.get("coins", 0)


class HandoverOut(BaseModel):
    id: uuid.UUID
    shift_id: uuid.UUID
    staff: Person
    receiver: Person
    expected: int
    received: int
    difference: int
    staff_agrees: bool | None
    staff_note: str | None
    receiver_note: str | None
    forced: bool
    created_at: datetime
    shortage_status: ShortageOutcome | None
    printed: bool


def _handover_out(db: Db, h: Handover) -> HandoverOut:
    db.expire_all()  # the print worker updates the slip in its own session
    staff, receiver = db.get(Staff, h.staff_id), db.get(Staff, h.created_by)
    latest = db.scalar(select(ShortageStatus.outcome).where(ShortageStatus.handover_id == h.id)
                       .order_by(ShortageStatus.created_at.desc()).limit(1))
    ticket = db.scalar(select(Ticket).where(Ticket.shift_id == h.shift_id, Ticket.kind == TicketKind.handover))
    return HandoverOut(
        id=h.id, shift_id=h.shift_id, staff=Person(id=staff.id, name=staff.name),
        receiver=Person(id=receiver.id, name=receiver.name), expected=h.expected, received=h.received,
        difference=h.difference, staff_agrees=h.staff_agrees, staff_note=h.staff_note,
        receiver_note=h.receiver_note, forced=h.forced, created_at=h.created_at, shortage_status=latest,
        printed=ticket is not None and ticket.status.value == "printed",
    )


def _close(
    db: Db, request: Request, shift: Shift, receiver: Staff, received: int, counted: dict | None,
    receiver_note: str | None, agrees: bool | None, staff_note: str | None, forced: bool,
) -> tuple[Handover, Ticket]:
    """Record the hand-over, put the cash in the box, close the shift, make the slips."""
    cash = cash_up(db, shift)
    ended = now()
    handover = Handover(
        business_id=shift.business_id, created_by=receiver.id, shift_id=shift.id, staff_id=shift.staff_id,
        expected=cash.cash_to_hand_over, counted_notes=counted, received=received,
        difference=received - cash.cash_to_hand_over, receiver_note=receiver_note or None,
        staff_agrees=agrees, staff_note=staff_note or None, forced=forced, summary=cash.as_dict(),
    )
    db.add(handover)
    db.flush()
    if received:
        db.add(CashMovement(business_id=shift.business_id, created_by=receiver.id, kind=CashMovementKind.handover,
                            amount=received, business_day=today(db, shift.business_id, request.app.state.tz),
                            shift_id=shift.id, note=db.get(Staff, shift.staff_id).name))
    shift.status, shift.ended_at = ShiftStatus.closed, ended
    tz = request.app.state.tz
    content = layouts.handover_slip(
        business_name(db, shift.business_id), db.get(Staff, shift.staff_id).name, shift.created_at.astimezone(tz),
        ended.astimezone(tz), handover.summary, received, receiver.name, agrees, staff_note, receiver_note, forced,
    )
    ticket = Ticket(business_id=shift.business_id, created_by=receiver.id, shift_id=shift.id, kind=TicketKind.handover,
                    number=next_number(db, shift.business_id, "handover"), printer=PrinterName.counter,
                    content=content, copies=["WAITER COPY", "OWNER COPY"])
    db.add(ticket)
    return handover, ticket


@router.post("/shifts/{shift_id}/close")
def close_shift(shift_id: uuid.UUID, body: CloseIn, actor: CurrentActor, request: Request, db: Db) -> HandoverOut:
    """End my shift, screens 3 and 4: the receiver counts the cash with their PIN, then the
    waiter agrees (or disagrees with a note) with theirs. Two slips print. Faida works out
    the amount due; nobody types it, and the hand-over can't be edited afterwards."""
    shift = _get_shift(db, actor, shift_id)
    _check_actor(actor, shift)
    if open_bills_of(db, shift.business_id, shift.staff_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Finish every open bill first.")
    state = request.app.state
    receiver = auth.find_staff_by_pin(db, state.keypad, state.config.pin_secret, actor.business_id, body.receiver_pin)
    _check_receiver(receiver, shift)
    signer = auth.find_staff_by_pin(db, state.keypad, state.config.pin_secret, actor.business_id, body.staff_pin)
    if signer.id != shift.staff_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"That isn't {db.get(Staff, shift.staff_id).name}'s PIN.")
    handover, ticket = _close(db, request, shift, receiver, body.total(), body.counted_notes, body.receiver_note,
                              body.agree, body.staff_note, forced=False)
    audit.record(db, business_id=actor.business_id, actor_id=receiver.id, action="shift.closed",
                 entity_type="shift", entity_id=shift.id,
                 details={"staff": signer.name, "expected": handover.expected, "received": handover.received,
                          "difference": handover.difference, "agrees": body.agree})
    db.commit()
    state.printing.open_drawer()
    state.printing.print_tickets([ticket])
    return _handover_out(db, handover)


class ForceCloseIn(BaseModel):
    received: Annotated[int, Field(ge=0, le=100_000_000)] = 0
    note: Annotated[str, Field(min_length=1, max_length=200)]


@router.post("/shifts/{shift_id}/force-close")
def force_close(shift_id: uuid.UUID, body: ForceCloseIn, actor: OwnerOnly, request: Request, db: Db) -> HandoverOut:
    """The waiter left without closing. Their open bills become "unpaid - waiter
    responsible"; the owner records the cash actually received (maybe 0), so the rest
    shows as that waiter's shortage. Sign-off is recorded as "not present"."""
    shift = _get_shift(db, actor, shift_id)
    tz = request.app.state.tz
    left_open = open_bills_of(db, shift.business_id, shift.staff_id)
    for bill in left_open:
        if amounts(db, bill).balance > 0:
            finish_bill(db, bill, BillStatus.unpaid_responsible, tz)
        else:
            bill.status, bill.closed_at = BillStatus.cancelled, now()  # nothing on it
    db.flush()
    handover, ticket = _close(db, request, shift, actor.staff, body.received, None, body.note, None, None, forced=True)
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="shift.force_closed",
                 entity_type="shift", entity_id=shift.id,
                 details={"staff": db.get(Staff, shift.staff_id).name, "expected": handover.expected,
                          "received": handover.received, "difference": handover.difference,
                          "bills_marked_unpaid": [b.number for b in left_open], "note": body.note})
    db.commit()
    request.app.state.printing.print_tickets([ticket])
    return _handover_out(db, handover)


class FloatIn(BaseModel):
    staff_id: uuid.UUID
    amount: Annotated[int, Field(ge=1, le=1_000_000)]


@router.post("/shifts/float")
def give_float(body: FloatIn, actor: Receiver, request: Request, db: Db) -> ShiftOut:
    """Change given to someone at the start of their shift, from the counter cash box."""
    staff = db.get(Staff, body.staff_id)
    if staff is None or staff.business_id != actor.business_id or not staff.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Staff member not found.")
    tz = request.app.state.tz
    shift = current_shift(db, actor.business_id, staff.id, tz)
    shift.float_amount += body.amount
    db.add(CashMovement(business_id=actor.business_id, created_by=actor.staff.id, kind=CashMovementKind.float,
                        amount=-body.amount, business_day=today(db, actor.business_id, tz), shift_id=shift.id,
                        note=staff.name))
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="shift.float_given",
                 entity_type="shift", entity_id=shift.id,
                 details={"staff": staff.name, "amount": body.amount, "float_now": shift.float_amount})
    db.commit()
    request.app.state.printing.open_drawer()
    return _shift_out(db, shift)


class ShiftRow(BaseModel):
    shift: ShiftOut
    status: ShiftStatus
    ended_at: datetime | None
    open_bills: int
    expected: int  # live for an open shift
    handover: HandoverOut | None


@router.get("/shifts")
def list_shifts(actor: Receiver, request: Request, db: Db) -> list[ShiftRow]:
    """Every open shift, and every shift of today's business day."""
    day = today(db, actor.business_id, request.app.state.tz)
    shifts = db.scalars(
        select(Shift).where(Shift.business_id == actor.business_id,
                            (Shift.status == ShiftStatus.open) | (Shift.business_day == day))
        .order_by(Shift.created_at)
    )
    rows = []
    for shift in shifts:
        handover = db.scalar(select(Handover).where(Handover.shift_id == shift.id))
        rows.append(ShiftRow(
            shift=_shift_out(db, shift), status=shift.status, ended_at=shift.ended_at,
            open_bills=len(open_bills_of(db, shift.business_id, shift.staff_id)) if shift.status is ShiftStatus.open else 0,
            expected=handover.expected if handover else cash_up(db, shift).cash_to_hand_over,
            handover=_handover_out(db, handover) if handover else None,
        ))
    return rows


class ShortageIn(BaseModel):
    outcome: ShortageOutcome
    note: Annotated[str, Field(max_length=200)] | None = None


@router.post("/handovers/{handover_id}/shortage-status")
def shortage_status(
    handover_id: uuid.UUID, body: ShortageIn,
    actor: Annotated[Actor, Depends(require(Action.record_shortage_status))], db: Db,
) -> HandoverOut:
    """Owner only: a shortage was paid back, deducted or forgiven. Faida never deducts
    pay itself; a deduction is the owner's decision under her house rules and the law."""
    handover = db.get(Handover, handover_id)
    if handover is None or handover.business_id != actor.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hand-over not found.")
    if handover.difference >= 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "This hand-over was not short.")
    db.add(ShortageStatus(business_id=actor.business_id, created_by=actor.staff.id, handover_id=handover.id,
                          outcome=body.outcome, note=body.note))
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="shortage.status",
                 entity_type="handover", entity_id=handover.id,
                 details={"staff": db.get(Staff, handover.staff_id).name, "short": -handover.difference,
                          "outcome": body.outcome.value, "note": body.note})
    db.commit()
    return _handover_out(db, handover)


class Alert(BaseModel):
    staff: Person
    times: int
    total_short: int
    message: str


@router.get("/shifts/alerts")
def shortage_alerts(
    actor: Annotated[Actor, Depends(require(Action.record_shortage_status))], request: Request, db: Db,
) -> list[Alert]:
    """Pattern alert: anyone short more than once this calendar month."""
    first = today(db, actor.business_id, request.app.state.tz).replace(day=1)
    counts: dict[uuid.UUID, list[int]] = {}
    for h in db.scalars(
        select(Handover).join(Shift, Shift.id == Handover.shift_id)
        .where(Handover.business_id == actor.business_id, Handover.difference < 0, Shift.business_day >= first)
    ):
        counts.setdefault(h.staff_id, []).append(-h.difference)
    alerts = []
    for staff_id, shorts in counts.items():
        if len(shorts) >= 2:
            name = db.get(Staff, staff_id).name
            alerts.append(Alert(staff=Person(id=staff_id, name=name), times=len(shorts), total_short=sum(shorts),
                                message=f"{name} short {len(shorts)} times this month - KSh {sum(shorts):,}"))
    return sorted(alerts, key=lambda a: -a.total_short)
