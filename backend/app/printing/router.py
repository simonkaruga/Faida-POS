"""Seeing printouts on screen: the exact receipt, slip or ticket as it was printed, so
staff can check it (and print it from the screen when no printer is attached)."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from app.audit import service as audit
from app.auth.deps import Actor, CurrentActor, Db, require
from app.auth.permissions import Action, Level, level
from app.floor.models import Bill
from app.floor.service import load_bill, place
from app.printing.models import PrinterName, PrintStatus, Ticket, TicketKind
from app.shifts.models import Shift
from app.staff.models import Staff

router = APIRouter(tags=["printing"])

Receiver = Annotated[Actor, Depends(require(Action.receive_handover))]


class PrintoutOut(BaseModel):
    id: uuid.UUID
    kind: TicketKind
    number: int
    printer: PrinterName
    status: PrintStatus
    created_at: datetime
    printed_at: datetime | None
    reprints: int
    last_error: str | None
    title: str  # "T2 · Bill #0142" or "Hand-over · Jane"


class PrintoutDoc(PrintoutOut):
    copies: list[str | None]
    content: list[dict[str, Any]]


def _title(db: Db, ticket: Ticket) -> str:
    if ticket.bill_id:
        bill = db.get(Bill, ticket.bill_id)
        return f"{place(db, bill)} · Bill #{bill.number:04d}"
    shift = db.get(Shift, ticket.shift_id)
    return f"Hand-over · {db.get(Staff, shift.staff_id).name}"


def _ticket(db: Db, actor: Actor, ticket_id: uuid.UUID) -> Ticket:
    """A printout the actor may see: one of their bills, or (Owner/Supervisor) any."""
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or ticket.business_id != actor.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Printout not found.")
    if ticket.bill_id:
        load_bill(db, actor, ticket.bill_id, Action.open_bill, open_only=False)
    else:
        shift = db.get(Shift, ticket.shift_id)
        if shift.staff_id != actor.staff.id and level(actor.staff.role, Action.receive_handover) is not Level.allow:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This isn't your printout.")
    return ticket


def _out(db: Db, ticket: Ticket) -> PrintoutOut:
    return PrintoutOut(**{f: getattr(ticket, f) for f in PrintoutOut.model_fields if f != "title"}, title=_title(db, ticket))


@router.get("/tickets/{ticket_id}")
def get_printout(ticket_id: uuid.UUID, actor: CurrentActor, db: Db) -> PrintoutDoc:
    db.expire_all()  # print workers update the status in their own sessions
    ticket = _ticket(db, actor, ticket_id)
    return PrintoutDoc(**_out(db, ticket).model_dump(), copies=ticket.copies or [None], content=ticket.content)


@router.get("/printouts")
def printouts(actor: Receiver, db: Db, limit: Annotated[int, Query(ge=1, le=200)] = 60) -> list[PrintoutOut]:
    """The printer log: the latest printouts on every printer, newest first."""
    rows = db.scalars(select(Ticket).where(Ticket.business_id == actor.business_id)
                      .order_by(Ticket.created_at.desc()).limit(limit))
    return [_out(db, t) for t in rows]


@router.post("/handover-slips/{ticket_id}/reprint")
def reprint_slip(ticket_id: uuid.UUID, actor: Receiver, request: Request, db: Db) -> PrintoutOut:
    """Hand-over slips print again for the owner or a supervisor (both copies)."""
    ticket = _ticket(db, actor, ticket_id)
    if ticket.kind is not TicketKind.handover:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Use the bill's reprint for this printout.")
    already_out = ticket.printed_at is not None
    ticket.reprints += 1
    ticket.status = PrintStatus.pending
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="ticket.reprinted",
                 entity_type="ticket", entity_id=ticket.id,
                 details={"kind": ticket.kind.value, "number": ticket.number, "was_printed": already_out})
    db.commit()
    request.app.state.printing.print_tickets([ticket], reprint=already_out)
    db.expire_all()
    return _out(db, db.get(Ticket, ticket.id))
