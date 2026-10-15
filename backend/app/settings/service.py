import uuid
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import now
from app.settings.business_day import business_day
from app.settings.models import Business, BusinessSettings


def get_settings(db: Session, business_id: uuid.UUID) -> BusinessSettings:
    return db.scalar(select(BusinessSettings).where(BusinessSettings.business_id == business_id))


def business_name(db: Session, business_id: uuid.UUID) -> str:
    return db.get(Business, business_id).name


def today(db: Session, business_id: uuid.UUID, tz: ZoneInfo) -> date:
    """The current business day, using the owner's cut-off."""
    return business_day(now(), get_settings(db, business_id).business_day_cutoff, tz)
