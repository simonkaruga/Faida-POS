import enum
import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String
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
