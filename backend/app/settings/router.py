from datetime import time
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.audit import service as audit
from app.auth.deps import Actor, CurrentActor, Db, require
from app.auth.permissions import Action
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
