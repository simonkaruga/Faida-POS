"""Cloud side: the health monitor (masterplan 7.2). Avinaya is alerted when a counter
hasn't synced for 24 hours, when its backups stop, or when its clock is off."""

import json
import urllib.request
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db, now
from app.settings.models import Business
from app.sync.models import Device

SYNC_LIMIT = timedelta(hours=24)
BACKUP_LIMIT = timedelta(hours=36)  # nightly, with room for a late closing
CLOCK_LIMIT_SECONDS = 300


def device_problems(device: Device, at: datetime) -> list[str]:
    problems = []
    if device.last_sync_at is None:
        problems.append("The counter has never synced")
    elif at - device.last_sync_at > SYNC_LIMIT:
        problems.append(f"The counter hasn't synced since {device.last_sync_at:%d %b %H:%M} UTC")
    if device.backup_error:
        problems.append(f"Last backup failed: {device.backup_error}")
    elif device.last_sync_at and (device.last_backup_at is None or at - device.last_backup_at > BACKUP_LIMIT):
        problems.append("No backup to USB in the last 36 hours")
    if device.clock_offset_seconds is not None and abs(device.clock_offset_seconds) > CLOCK_LIMIT_SECONDS:
        problems.append(f"The counter clock is off by {abs(device.clock_offset_seconds) // 60} minutes")
    return problems


def all_problems(db: Session, at: datetime | None = None) -> list[dict]:
    at = at or now()
    rows = []
    for device in db.scalars(select(Device).where(Device.active).order_by(Device.created_at)):
        business = db.get(Business, device.business_id)
        for problem in device_problems(device, at):
            rows.append({"business": business.name if business else str(device.business_id),
                         "device": device.name, "problem": problem})
    return rows


def send_alerts(webhook: str, problems: list[dict]) -> None:
    """Post the problems as JSON to a webhook (e.g. a WhatsApp or Slack bridge)."""
    body = json.dumps({"text": "\n".join(f"{p['business']} ({p['device']}): {p['problem']}" for p in problems),
                       "problems": problems}).encode()
    request = urllib.request.Request(webhook, data=body, method="POST", headers={"Content-Type": "application/json"})
    urllib.request.urlopen(request, timeout=15).close()


router = APIRouter(prefix="/admin", tags=["admin"])


def admin(request: Request, x_admin_token: Annotated[str | None, Header()] = None) -> None:
    expected = request.app.state.config.admin_token
    if not expected or x_admin_token != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin token required.")


@router.get("/health", dependencies=[Depends(admin)])
def health(db: Annotated[Session, Depends(get_db)]) -> dict:
    devices = []
    for d in db.scalars(select(Device).order_by(Device.created_at)):
        business = db.get(Business, d.business_id)
        devices.append({"business": business.name if business else None, "device": d.name,
                        "last_sync_at": d.last_sync_at, "version": d.software_version,
                        "clock_offset_seconds": d.clock_offset_seconds, "last_backup_at": d.last_backup_at,
                        "problems": device_problems(d, now())})
    return {"devices": devices, "problems": all_problems(db)}
