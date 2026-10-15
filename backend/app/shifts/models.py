import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, Record, str_enum


class ShiftStatus(enum.StrEnum):
    open = "open"
    closed = "closed"


class Shift(Record, Base):
    """One person's working period with money responsibility. It starts the first time
    they open a bill, take a payment, receive a bill or are given a float, and ends at
    the cash hand-over. A shift belongs to the business day it started in."""

    __tablename__ = "shifts"
    __table_args__ = (
        Index("uq_shifts_one_open", "business_id", "staff_id", unique=True,
              postgresql_where=text("status = 'open'")),
    )

    staff_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("staff.id"), index=True)
    business_day: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[ShiftStatus] = mapped_column(str_enum(ShiftStatus, "shift_status"), default=ShiftStatus.open)
    float_amount: Mapped[int] = mapped_column(Integer, default=0)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Handover(Record, Base):
    """The cash hand-over that closes a shift. Permanent: a database trigger refuses
    edits, so any correction is a new, visible entry. `created_by` is the receiver."""

    __tablename__ = "handovers"

    shift_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shifts.id"), unique=True)
    staff_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("staff.id"), index=True)
    expected: Mapped[int] = mapped_column(Integer)  # calculated by Faida, never typed
    counted_notes: Mapped[dict[str, int] | None] = mapped_column(JSONB)  # {"1000": 3, "coins": 40}
    received: Mapped[int] = mapped_column(Integer)
    difference: Mapped[int] = mapped_column(Integer)  # received - expected: below 0 short, above 0 over
    receiver_note: Mapped[str | None] = mapped_column(String(200))
    # True agrees, False disagrees (see note); None: not present (force-closed).
    staff_agrees: Mapped[bool | None] = mapped_column(Boolean)
    staff_note: Mapped[str | None] = mapped_column(String(200))
    forced: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB)  # the cash-up as shown and printed


class ShortageOutcome(enum.StrEnum):
    paid_back = "paid_back"
    deducted = "deducted"
    forgiven = "forgiven"


class ShortageStatus(Record, Base):
    """What became of a shortage. Permanent; the latest entry is the current status."""

    __tablename__ = "shortage_statuses"

    handover_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("handovers.id"), index=True)
    outcome: Mapped[ShortageOutcome] = mapped_column(str_enum(ShortageOutcome, "shortage_outcome"))
    note: Mapped[str | None] = mapped_column(String(200))


class CashMovementKind(enum.StrEnum):
    handover = "handover"  # in: cash a waiter handed over
    float = "float"  # out: change given to a waiter at the start of a shift
    payout = "payout"  # out: cash taken from takings, e.g. to buy ice
    credit_collected = "credit_collected"  # in: a credit customer paying in cash
    owner = "owner"  # in or out: the owner adding change or taking cash away (e.g. banking)


class CashMovement(Record, Base):
    """Cash going into or out of the counter cash box held by the owner or supervisor.
    `amount` is positive into the box, negative out of it. Permanent."""

    __tablename__ = "cash_movements"

    kind: Mapped[CashMovementKind] = mapped_column(str_enum(CashMovementKind, "cash_movement_kind"))
    amount: Mapped[int] = mapped_column(Integer)
    business_day: Mapped[date] = mapped_column(Date, index=True)
    shift_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("shifts.id"))
    reference_id: Mapped[uuid.UUID | None] = mapped_column()
    note: Mapped[str | None] = mapped_column(String(200))
