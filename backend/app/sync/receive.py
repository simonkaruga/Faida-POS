"""Cloud side: accept uploads from registered counters (masterplan 5.1, 7.2).

Each entry is applied as an insert-or-update by its unique ID, so a batch that is sent
twice (a dropped connection) changes nothing the second time. Every row must belong to
the uploading counter's business; one cloud serves all Faida clients.
"""

import hashlib
import secrets
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db import Base, get_db, now
from app.settings.config import VERSION
from app.sync.models import Device
from app.sync.outbox import from_json, synced_tables

router = APIRouter(prefix="/sync", tags=["sync"])

CLOCK_WARNING_SECONDS = 300


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_device(db: Session, business_id: uuid.UUID, name: str) -> tuple[Device, str]:
    """Register a counter. The token is shown once and kept only as a hash."""
    token = secrets.token_urlsafe(32)
    device = Device(business_id=business_id, name=name, token_hash=token_hash(token))
    db.add(device)
    db.commit()
    return device, token


def compatible(version: str) -> bool:
    """The cloud accepts the current and the previous minor version (masterplan 7.1), so a
    counter that hasn't been updated yet keeps syncing."""
    try:
        major, minor = (int(x) for x in version.split(".")[:2])
    except ValueError:
        return False
    cur_major, cur_minor = (int(x) for x in VERSION.split(".")[:2])
    return major == cur_major and cur_minor - 1 <= minor <= cur_minor


class Entry(BaseModel):
    seq: int
    table: str
    op: str
    id: uuid.UUID
    data: dict[str, Any] | None


class UploadIn(BaseModel):
    software_version: str
    counter_time: datetime
    backup: dict[str, Any] = {}
    entries: list[Entry]


def device_for(db: Annotated[Session, Depends(get_db)], authorization: Annotated[str | None, Header()] = None) -> Device:
    token = (authorization or "").removeprefix("Bearer ").strip()
    device = db.scalar(select(Device).where(Device.token_hash == token_hash(token))) if token else None
    if device is None or not device.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown counter.")
    return device


def _apply(db: Session, device: Device, entry: Entry) -> None:
    if entry.table not in synced_tables():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown table {entry.table}.")
    table = Base.metadata.tables[entry.table]
    if entry.op == "delete":
        owner = "id" if entry.table == "businesses" else "business_id"
        db.execute(delete(table).where(table.c.id == entry.id, table.c[owner] == device.business_id))
        return
    data = {c.name: from_json(c.type, entry.data[c.name]) for c in table.columns if c.name in entry.data}
    data["sync_status"] = "synced"  # in the cloud, every row has arrived
    owner = data.get("id") if entry.table == "businesses" else data.get("business_id")
    if owner != device.business_id or data.get("id") != entry.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "A record doesn't belong to this counter's business.")
    stmt = insert(table).values(**data)
    db.execute(stmt.on_conflict_do_update(index_elements=[table.c.id],
                                          set_={k: stmt.excluded[k] for k in data if k != "id"}))


@router.post("/upload")
def upload(body: UploadIn, device: Annotated[Device, Depends(device_for)],
           db: Annotated[Session, Depends(get_db)]) -> dict:
    if not compatible(body.software_version):
        raise HTTPException(status.HTTP_426_UPGRADE_REQUIRED,
                            f"Counter version {body.software_version} is too old for the cloud ({VERSION}).")
    received = now()
    for entry in sorted(body.entries, key=lambda e: e.seq):
        if entry.seq > device.last_seq:  # already applied otherwise
            _apply(db, device, entry)
    device = db.get(Device, device.id)
    if body.entries:
        device.last_seq = max(device.last_seq, max(e.seq for e in body.entries))
    device.last_sync_at = received
    device.software_version = body.software_version
    device.clock_offset_seconds = round((body.counter_time - received).total_seconds())
    if body.backup.get("last_ok_at"):
        device.last_backup_at = datetime.fromisoformat(body.backup["last_ok_at"])
    device.backup_error = (body.backup.get("error") or None) and str(body.backup["error"])[:300]
    db.commit()
    return {"accepted_up_to": device.last_seq,
            "clock_warning": abs(device.clock_offset_seconds) > CLOCK_WARNING_SECONDS}
