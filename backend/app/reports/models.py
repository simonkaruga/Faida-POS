import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Integer, LargeBinary, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, Record, now


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


class EmailOutbox(Base):
    """Counter side: emails waiting to go (the daily closing to the owner). Sent when
    the internet is there, retried until they go."""

    __tablename__ = "email_outbox"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    to: Mapped[list[str]] = mapped_column(JSONB)
    subject: Mapped[str] = mapped_column(String(200))
    html: Mapped[str] = mapped_column(Text)
    attachment_name: Mapped[str | None] = mapped_column(String(120))
    attachment: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(300))
