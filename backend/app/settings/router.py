from datetime import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from app import backup
from app.audit import service as audit
from app.auth import service as auth
from app.auth.deps import Actor, CurrentActor, Db, require
from app.auth.permissions import Action
from app.db import now
from app.settings.models import BusinessSettings, MpesaCodeEntry

router = APIRouter(prefix="/settings", tags=["settings"])

Owner = Annotated[Actor, Depends(require(Action.manage_business))]


class SettingsOut(BaseModel):
    business_day_cutoff: time
    auto_lock_seconds: int
    tot_size_ml: int | None
    mpesa_code_entry: MpesaCodeEntry
    mpesa_till_number: str | None
    receipt_footer: str
    note_presets: list[str]
    tab_section: str
    report_emails: list[str]


class SettingsPatch(BaseModel):
    business_day_cutoff: time | None = None
    auto_lock_seconds: int | None = Field(default=None, ge=10, le=600)
    tot_size_ml: int | None = Field(default=None, ge=5, le=100)
    mpesa_code_entry: MpesaCodeEntry | None = None
    mpesa_till_number: str | None = Field(default=None, pattern=r"^\d{5,10}$")
    receipt_footer: str | None = Field(default=None, max_length=200)
    note_presets: list[Annotated[str, Field(min_length=1, max_length=40)]] | None = Field(
        default=None, max_length=24
    )
    tab_section: Annotated[str, Field(min_length=1, max_length=30)] | None = None
    report_emails: list[Annotated[str, Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=120)]] | None = Field(
        default=None, max_length=5
    )


def _settings(db: Db, actor: Actor) -> BusinessSettings:
    return db.scalar(
        select(BusinessSettings).where(BusinessSettings.business_id == actor.business_id)
    )


@router.get("")
def get_settings(actor: CurrentActor, db: Db) -> SettingsOut:
    return SettingsOut.model_validate(_settings(db, actor), from_attributes=True)


@router.patch("")
def update_settings(body: SettingsPatch, actor: Owner, db: Db) -> SettingsOut:
    """Only fields that are sent are changed. Every change is logged with old and new values."""
    row = _settings(db, actor)
    changes = {}
    for field, new in body.model_dump(exclude_unset=True).items():
        if new is None:
            continue
        old = getattr(row, field)
        if old != new:
            changes[field] = [str(old) if old is not None else None, str(new)]
            setattr(row, field, new)
    if changes:
        audit.record(
            db, business_id=actor.business_id, actor_id=actor.staff.id, action="settings.updated",
            entity_type="business_settings", entity_id=row.id, details=changes,
        )
        db.commit()
    return SettingsOut.model_validate(row, from_attributes=True)


@router.post("/exit-screen", status_code=204)
def exit_screen(actor: Owner, request: Request, db: Db) -> None:
    """Owner only: close the full-screen counter to reach the Windows desktop. The kiosk
    task (kiosk.ps1) sees this file change, closes the window and doesn't reopen it until
    the Faida POS icon is used or Windows signs in again."""
    path = Path(request.app.state.config.state_dir) / "exit-screen.flag"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(now().isoformat())
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="screen.exited")
    db.commit()


# Everything that happened (sales, money, stock movements, the log). Kept: the menu, stock
# items, tables, staff and PINs, employees, credit customers, suppliers and settings.
RECORDS = (
    "bill_handovers", "bill_lines", "payments", "tickets", "bills", "cash_movements", "shortage_statuses",
    "employee_entries", "handovers", "stock_take_lines", "stock_takes", "delivery_lines", "deliveries",
    "stock_movements", "shifts", "credit_collections", "expenses", "daily_closings", "audit_entries", "approvals",
    "sync_queue", "email_outbox", "sequences",
)


class AfreshIn(BaseModel):
    pin: Annotated[str, Field(min_length=1, max_length=12)]
    confirm: str


class AfreshOut(BaseModel):
    backup: str  # where everything was saved first


@router.post("/start-afresh")
def start_afresh(body: AfreshIn, actor: Owner, request: Request, db: Db) -> AfreshOut:
    """Owner only, after trying Faida out: delete every sale, payment, shift, hand-over,
    expense, salary entry, delivery, stock count and the log, so the business starts at
    nothing (stock at 0, bills from #1). A backup is taken first; Restore-Backup brings
    it all back. Permanent records can't be deleted one by one: they are emptied as a whole."""
    state = request.app.state
    if state.config.mode != "local":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a counter can start afresh.")
    if body.confirm != "DELETE":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Type DELETE to confirm.")
    if auth.find_staff_by_pin(db, state.keypad, state.config.pin_secret, actor.business_id, body.pin).id != actor.staff.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "That is not your PIN.")
    to = Path(state.config.state_dir).resolve().parent / "update-backups"
    try:
        saved = backup.create(state.config, str(to), keep=10)
    except backup.BackupError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Nothing was deleted: the backup first failed ({e}).") from e
    db.execute(text(f"TRUNCATE {', '.join(RECORDS)}"))
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="records.started_afresh",
                 details={"backup": str(saved)})
    db.commit()
    return AfreshOut(backup=str(saved))
