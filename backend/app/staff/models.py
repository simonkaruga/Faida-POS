import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, Record, str_enum


class Role(enum.StrEnum):
    owner = "owner"
    supervisor = "supervisor"
    waiter = "waiter"


class Staff(Record, Base):
    """A staff member who leaves is deactivated, never deleted."""

    __tablename__ = "staff"
    __table_args__ = (
        # Staff log in with their PIN alone, so active PINs must be unique.
        Index(
            "uq_staff_active_pin",
            "business_id",
            "pin_lookup",
            unique=True,
            postgresql_where=text("active"),
        ),
    )

    name: Mapped[str] = mapped_column(String(80))
    role: Mapped[Role] = mapped_column(str_enum(Role, "staff_role"))
    # Keyed hash of the PIN (see auth/pins.py). The PIN itself is never stored.
    pin_lookup: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
