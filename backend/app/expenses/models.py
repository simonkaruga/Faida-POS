import enum
import uuid
from datetime import date

from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, Record, str_enum


class ExpenseCategory(enum.StrEnum):
    rent = "rent"
    power = "power"
    water = "water"
    salaries = "salaries"
    transport = "transport"
    repairs = "repairs"
    licences = "licences"
    supplies = "supplies"  # bought outside a stock delivery: gas, cleaning, charcoal
    other = "other"


class PaidHow(enum.StrEnum):
    cash_box = "cash_box"  # cash from the counter box (the box goes down)
    cash = "cash"  # the owner's own cash
    mpesa = "mpesa"
    bank = "bank"


class Expense(Record, Base):
    """A running cost (masterplan 4.9), recorded by the owner for the day it belongs to.
    Permanent: a mistake is undone by a reversal entry with the opposite amount."""

    __tablename__ = "expenses"

    category: Mapped[ExpenseCategory] = mapped_column(str_enum(ExpenseCategory, "expense_category"))
    amount: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(200))
    business_day: Mapped[date] = mapped_column(Date, index=True)
    from_cash_box: Mapped[bool] = mapped_column(Boolean, default=False)
    reverses_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expenses.id"), unique=True)
    # Details (all optional; older expenses have none)
    payee: Mapped[str | None] = mapped_column(String(80))  # paid to: KPLC, the landlord
    paid_how: Mapped[PaidHow | None] = mapped_column(str_enum(PaidHow, "expense_paid_how"))
    reference: Mapped[str | None] = mapped_column(String(40))  # M-Pesa code, receipt or cheque number
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))  # 3 (bags of charcoal)
    unit_price: Mapped[int | None] = mapped_column(Integer)  # 800 each
