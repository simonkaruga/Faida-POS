import enum
import uuid
from datetime import datetime, time

from sqlalchemy import DateTime, ForeignKey, Integer, String, Time, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, Record, SyncStatus, now, str_enum


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    sync_status: Mapped[SyncStatus] = mapped_column(
        str_enum(SyncStatus, "sync_status"), default=SyncStatus.pending
    )


class MpesaCodeEntry(enum.StrEnum):
    """Owner setting "M-Pesa code entry" (masterplan 4.3)."""

    last4 = "last4"
    full = "full"
    none = "none"


class BusinessSettings(Record, Base):
    """One row per business. Every change is written to the audit log."""

    __tablename__ = "business_settings"

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id"), unique=True)
    # The business day ends here, so a 01:30 sale belongs to the previous day.
    business_day_cutoff: Mapped[time] = mapped_column(Time, default=time(6, 0))
    auto_lock_seconds: Mapped[int] = mapped_column(Integer, default=30)
    # Unknown until the owner confirms it (open item 1).
    tot_size_ml: Mapped[int | None] = mapped_column(Integer)
    mpesa_code_entry: Mapped[MpesaCodeEntry] = mapped_column(
        str_enum(MpesaCodeEntry, "mpesa_code_entry"), default=MpesaCodeEntry.last4
    )
    mpesa_till_number: Mapped[str | None] = mapped_column(String(20))
    receipt_footer: Mapped[str] = mapped_column(String(200), default="Thank you, karibu tena!")
