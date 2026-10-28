import enum
import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, Record, str_enum


class PayType(enum.StrEnum):
    monthly = "monthly"
    weekly = "weekly"
    daily = "daily"  # paid per day worked


class Employee(Record, Base):
    """Someone the owner pays: a waiter with a PIN, or a cook, cleaner or guard without
    one. Linked to their PIN (staff_id), their cash shortages can be deducted from pay."""

    __tablename__ = "employees"

    name: Mapped[str] = mapped_column(String(80))
    job: Mapped[str | None] = mapped_column(String(40))
    phone: Mapped[str | None] = mapped_column(String(20))
    staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff.id"))
    pay_type: Mapped[PayType] = mapped_column(str_enum(PayType, "pay_type"))
    pay_rate: Mapped[int] = mapped_column(Integer)  # KSh per month, week or day
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class EntryKind(enum.StrEnum):
    salary = "salary"  # + earned for a period
    advance = "advance"  # - money given before pay day
    deduction = "deduction"  # - e.g. a broken glass, decided by the owner
    shortage = "shortage"  # - a cash shortage the owner marked Deducted
    payment = "payment"  # - pay handed over
    reversal = "reversal"  # undoes a mistaken entry


class EmployeeEntry(Record, Base):
    """One line of an employee's pay account. The balance (sum of amounts) is what the bar
    owes them; below 0, what they owe the bar. Permanent: a mistake gets a reversal."""

    __tablename__ = "employee_entries"

    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), index=True)
    kind: Mapped[EntryKind] = mapped_column(str_enum(EntryKind, "employee_entry_kind"))
    amount: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(200))
    business_day: Mapped[date] = mapped_column(Date)
    period_start: Mapped[date | None] = mapped_column(Date)  # a salary: the days it pays for
    period_end: Mapped[date | None] = mapped_column(Date)
    handover_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("handovers.id"))  # a shortage
    expense_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expenses.id"))  # money paid out
    reverses_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employee_entries.id"), unique=True)
