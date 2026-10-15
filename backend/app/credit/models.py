import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, Record, str_enum
from app.payments.models import Method


class CreditCustomer(Record, Base):
    """A named customer allowed to pay later, up to a limit set by the owner."""

    __tablename__ = "credit_customers"

    name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(20))
    credit_limit: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class CreditCollection(Record, Base):
    """A credit customer paying off what they owe, recorded by the owner or supervisor.
    Shows in daily closing as "Credit collected", never in a waiter's cash-up. Permanent."""

    __tablename__ = "credit_collections"

    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("credit_customers.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    method: Mapped[Method] = mapped_column(str_enum(Method, "payment_method"))
    mpesa_ref: Mapped[str | None] = mapped_column(String(12))
    business_day: Mapped[date] = mapped_column(Date)
