import enum
import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, Record, str_enum


class Method(enum.StrEnum):
    cash = "cash"
    mpesa = "mpesa"


class Payment(Record, Base):
    """Money taken against a bill. `created_by` is the person who took it.

    `amount` is what counts towards the bill. For cash, `tendered` is what the customer
    handed over (change = tendered - amount). For M-Pesa, `tip` is the extra paid to the
    till on top of the bill; tips are not sales.
    """

    __tablename__ = "payments"
    __table_args__ = (Index("ix_payments_mpesa_ref", "business_id", "mpesa_ref"),)

    bill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bills.id"), index=True)
    method: Mapped[Method] = mapped_column(str_enum(Method, "payment_method"))
    amount: Mapped[int] = mapped_column(Integer)
    tendered: Mapped[int | None] = mapped_column(Integer)
    tip: Mapped[int] = mapped_column(Integer, default=0)
    # Last 4 characters of the M-Pesa code, or the full code, per the owner's setting.
    mpesa_ref: Mapped[str | None] = mapped_column(String(12))
    business_day: Mapped[date] = mapped_column(Date)
