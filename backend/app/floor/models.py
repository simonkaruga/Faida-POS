import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, Record, str_enum
from app.menu.models import Station


class Table(Record, Base):
    __tablename__ = "tables"

    name: Mapped[str] = mapped_column(String(30))
    section: Mapped[str] = mapped_column(String(30), default="Main")  # Indoor, Garden, VIP...
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class BillStatus(enum.StrEnum):
    open = "open"
    paid = "paid"
    credit = "credit"  # Phase 3
    unpaid_responsible = "unpaid_responsible"  # Phase 3
    cancelled = "cancelled"  # closed empty, or a paid bill reversed with approval
    merged = "merged"  # its lines were moved into `merged_into_id`


class VoidReason(enum.StrEnum):
    not_prepared = "not_prepared"  # goes back to stock (Phase 4)
    already_prepared = "already_prepared"  # recorded as waste


class CompReason(enum.StrEnum):
    """Why something was given free. It still comes out of stock, and shows in closing."""

    house = "house"  # on the house
    staff_drink = "staff_drink"
    owner_guest = "owner_guest"
    complaint = "complaint"
    promotion = "promotion"


class DiscountKind(enum.StrEnum):
    amount = "amount"
    percent = "percent"


class Bill(Record, Base):
    """An order, known by its number (#0031). It may have a table: one set up in Tables &
    sections, or a number typed by the waiter (table_label). Belongs to one waiter at a time."""

    __tablename__ = "bills"
    __table_args__ = (UniqueConstraint("business_id", "number", name="uq_bills_number"),)

    number: Mapped[int] = mapped_column(Integer)  # shown as #0142
    section: Mapped[str] = mapped_column(String(30), default="Main")  # where it was sold, for reports
    table_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tables.id"))
    tab_name: Mapped[str | None] = mapped_column(String(40))
    table_label: Mapped[str | None] = mapped_column(String(30))
    waiter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("staff.id"), index=True)
    status: Mapped[BillStatus] = mapped_column(
        str_enum(BillStatus, "bill_status"), default=BillStatus.open, index=True
    )
    business_day: Mapped[date] = mapped_column(Date)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bills.id"))
    # The shift of the waiter who finished the bill (paid, credit or unpaid). Its sales
    # count in that shift's cash-up.
    finished_shift_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("shifts.id"), index=True)
    # Discount on the whole bill: a fixed amount or a percentage (see floor.service.amounts).
    discount_kind: Mapped[DiscountKind | None] = mapped_column(str_enum(DiscountKind, "discount_kind"))
    discount_value: Mapped[int] = mapped_column(Integer, default=0)
    # Approved credit: what was left to pay moves to the customer's account.
    credit_customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("credit_customers.id"), index=True)
    credit_amount: Mapped[int] = mapped_column(Integer, default=0)
    # Cancelled after payment: what happens to the items (back to stock or waste).
    cancel_reason: Mapped[VoidReason | None] = mapped_column(str_enum(VoidReason, "void_reason"))


class BillLine(Record, Base):
    """One unit of one sell option, sent on one bar slip or kitchen ticket.

    Name, option, station and price are copied at order time, so later menu or price
    changes never alter a bill. Lines are created only by SEND; voiding marks them.
    """

    __tablename__ = "bill_lines"

    bill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bills.id"), index=True)
    sell_option_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sell_options.id"))
    item_name: Mapped[str] = mapped_column(String(80))
    option_label: Mapped[str] = mapped_column(String(40))
    station: Mapped[Station] = mapped_column(str_enum(Station, "station"))
    unit_price: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(120))
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id"))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff.id"))
    void_reason: Mapped[VoidReason | None] = mapped_column(str_enum(VoidReason, "void_reason"))
    # Choices made when ordering: [{"group": "Mixer", "label": "Coke", "price": 0, "id": ...}]
    modifiers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # Happy hour: the menu price before the offer, and the offer's name.
    list_price: Mapped[int | None] = mapped_column(Integer)
    price_rule: Mapped[str | None] = mapped_column(String(40))
    # Given free (comp): the line no longer counts towards the bill.
    comp_reason: Mapped[CompReason | None] = mapped_column(str_enum(CompReason, "comp_reason"))
    comped_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff.id"))
    comped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A part of a combo: free on its own line, charged in the combo's line.
    combo_parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bill_lines.id"))


class BillHandover(Record, Base):
    """A bill passed to another waiter, who accepted it with their PIN.
    From then on the bill and its money belong to them."""

    __tablename__ = "bill_handovers"

    bill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bills.id"), index=True)
    from_waiter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("staff.id"))
    to_waiter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("staff.id"))
