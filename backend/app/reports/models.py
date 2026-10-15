from datetime import date
from typing import Any

from sqlalchemy import Date, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, Record


class DailyClosing(Record, Base):
    """The end of a business day (masterplan 4.9), run by the owner or a supervisor once
    every shift is handed over. Keeps the report as it was at closing. Permanent."""

    __tablename__ = "daily_closings"
    __table_args__ = (UniqueConstraint("business_id", "business_day", name="uq_daily_closings_day"),)

    business_day: Mapped[date] = mapped_column(Date)
    cash_box_expected: Mapped[int] = mapped_column(Integer)
    cash_box_counted: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(200))
    report: Mapped[dict[str, Any]] = mapped_column(JSONB)
