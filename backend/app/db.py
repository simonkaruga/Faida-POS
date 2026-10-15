"""Database base classes and the session dependency.

Every business record carries the same five columns (masterplan section 8):
a unique ID created on the counter, the business ID, who created it, when, and its
sync status. `Record` adds them to a model.
"""

import enum
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import DateTime, Enum, ForeignKey, MetaData, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, declared_attr, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def now() -> datetime:
    """The counter clock is the record time (masterplan 5.1 rule 7)."""
    return datetime.now(UTC)


class SyncStatus(enum.StrEnum):
    pending = "pending"
    synced = "synced"


def str_enum(cls: type[enum.Enum], name: str) -> Enum:
    """Store enums by value as a native PostgreSQL enum."""
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class Record:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    @declared_attr
    def business_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(ForeignKey("businesses.id"), index=True)

    @declared_attr
    def created_by(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(ForeignKey("staff.id"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    @declared_attr
    def sync_status(cls) -> Mapped[SyncStatus]:
        return mapped_column(str_enum(SyncStatus, "sync_status"), default=SyncStatus.pending)


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker() as db:
        yield db
