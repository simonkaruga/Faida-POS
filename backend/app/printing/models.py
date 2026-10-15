import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, Record, str_enum


class TicketKind(enum.StrEnum):
    bar_slip = "bar_slip"
    kitchen_ticket = "kitchen_ticket"
    bill = "bill"  # before payment
    receipt = "receipt"  # after payment: customer copy + COUNTER COPY
    handover = "handover"  # cash hand-over slip: waiter copy + owner copy


class PrinterName(enum.StrEnum):
    counter = "counter"  # USB, with the cash drawer; bar slips, bills, receipts
    kitchen = "kitchen"  # network; kitchen tickets


class PrintStatus(enum.StrEnum):
    pending = "pending"
    printed = "printed"
    not_printed = "not_printed"


class Ticket(Record, Base):
    """Every printout. The content is stored, so a reprint is identical to the original."""

    __tablename__ = "tickets"

    bill_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bills.id"), index=True)
    shift_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("shifts.id"))
    kind: Mapped[TicketKind] = mapped_column(str_enum(TicketKind, "ticket_kind"))
    number: Mapped[int] = mapped_column(Integer)
    printer: Mapped[PrinterName] = mapped_column(str_enum(PrinterName, "printer_name"))
    status: Mapped[PrintStatus] = mapped_column(
        str_enum(PrintStatus, "print_status"), default=PrintStatus.pending
    )
    content: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    copies: Mapped[list[str | None]] = mapped_column(JSONB, default=lambda: [None])
    printed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reprints: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(200))
