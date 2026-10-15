"""Counter side: put every saved change in the sync queue (masterplan 5.1 rule 3).

A listener on every database session copies each inserted, changed or deleted business
record into `sync_queue` during the same flush, so the change and its queue entry are
committed (or rolled back) together. Within a flush, parents are queued before
children, so the cloud never receives a row before the row it refers to.
"""

import enum
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, Numeric, Time, Uuid, event, insert, inspect
from sqlalchemy.orm import Session

from app.db import Base, Record
from app.settings.models import Business
from app.sync.models import SyncQueueEntry


def synced_tables() -> set[str]:
    """Business records (they carry the business ID) and the business itself."""
    names = {m.class_.__tablename__ for m in Base.registry.mappers if issubclass(m.class_, Record)}
    return names | {Business.__tablename__}


def _rank() -> dict[str, int]:
    return {t.name: i for i, t in enumerate(Base.metadata.sorted_tables)}


def to_json(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, uuid.UUID | Decimal):
        return str(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    return value


def from_json(column_type: Any, value: Any) -> Any:
    """Back to the Python type a column expects (used by the cloud when applying)."""
    if value is None:
        return None
    if isinstance(column_type, Uuid):
        return uuid.UUID(value)
    if isinstance(column_type, DateTime):
        return datetime.fromisoformat(value)
    if isinstance(column_type, Date):
        return date.fromisoformat(value)
    if isinstance(column_type, Time):
        return time.fromisoformat(value)
    if isinstance(column_type, Numeric):
        return Decimal(str(value))  # str() keeps 3.2 as 3.2 if it arrived as a JSON number
    return value


def payload(obj: Any) -> dict[str, Any]:
    mapper = inspect(obj).mapper
    return {c.key: to_json(getattr(obj, c.key)) for c in mapper.column_attrs}


@event.listens_for(Session, "after_flush")
def _queue_changes(session: Session, _context: Any) -> None:
    if session.info.get("no_sync_queue"):
        return
    tables = synced_tables()
    rank = _rank()
    changes = [("upsert", o) for o in session.new] + [
        ("upsert", o) for o in session.dirty if session.is_modified(o, include_collections=False)
    ]
    upserts = sorted(
        ((op, o) for op, o in changes if o.__tablename__ in tables), key=lambda c: rank[c[1].__tablename__]
    )
    deletes = sorted(
        (("delete", o) for o in session.deleted if o.__tablename__ in tables),
        key=lambda c: -rank[c[1].__tablename__],
    )
    rows = [
        dict(table_name=o.__tablename__, row_id=o.id, op=op, payload=payload(o) if op == "upsert" else None)
        for op, o in upserts + deletes
    ]
    if rows:
        session.connection().execute(insert(SyncQueueEntry), rows)
