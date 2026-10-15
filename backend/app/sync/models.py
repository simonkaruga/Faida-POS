import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Identity, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, now


class SyncQueueEntry(Base):
    """Counter side: one saved change waiting to be uploaded, written in the same
    transaction as the change itself, so nothing saved can be missed. Uploaded in `seq`
    order; safe to send twice."""

    __tablename__ = "sync_queue"

    seq: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    table_name: Mapped[str] = mapped_column(String(60))
    row_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    op: Mapped[str] = mapped_column(String(10))  # "upsert" or "delete"
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Device(Base):
    """Cloud side: a counter allowed to upload for one business."""

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)  # its row arrives with the first sync
    name: Mapped[str] = mapped_column(String(60))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    software_version: Mapped[str | None] = mapped_column(String(20))
    clock_offset_seconds: Mapped[int | None] = mapped_column(Integer)  # counter clock minus cloud clock
    last_backup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    backup_error: Mapped[str | None] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class OwnerAccount(Base):
    """Cloud side: the owner's phone login (email, password and a one-time code)."""

    __tablename__ = "owner_accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    email: Mapped[str] = mapped_column(String(120), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    totp_secret: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
