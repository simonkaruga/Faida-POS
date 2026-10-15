"""Cloud side: the owner's phone view (masterplan 4.10). Read-only in Version 1.

Built from the synced copy of the counter's data with the same report functions the
counter uses, and always says how fresh it is ("Last updated HH:MM").
"""

from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.owner import LoginGuard, OwnerToken, check_password, check_totp, issue_token, read_token
from app.db import get_db, now
from app.reports import service as reports
from app.reports.models import DailyClosing
from app.settings.models import Business, BusinessSettings
from app.settings.service import today
from app.sync.health import device_problems
from app.sync.models import Device, OwnerAccount

router = APIRouter(prefix="/phone", tags=["phone"])

Db = Annotated[Session, Depends(get_db)]


class LoginIn(BaseModel):
    email: Annotated[str, Field(min_length=3, max_length=120)]
    password: Annotated[str, Field(min_length=1, max_length=200)]
    code: Annotated[str, Field(min_length=6, max_length=6)]


@router.post("/login")
def login(body: LoginIn, request: Request, db: Db) -> dict:
    guard: LoginGuard = request.app.state.owner_logins
    email = body.email.strip().lower()
    if guard.locked(email):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again in a few minutes.")
    owner = db.scalar(select(OwnerAccount).where(OwnerAccount.email == email, OwnerAccount.active))
    if owner is None or not check_password(body.password, owner.password_hash) or not check_totp(owner.totp_secret, body.code):
        guard.failed(email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email, password or code is wrong.")
    guard.succeeded(email)
    business = db.get(Business, owner.business_id)
    return {"token": issue_token(request.app.state.config.pin_secret, owner.id, owner.business_id),
            "business_name": business.name if business else None}


def phone_owner(request: Request, db: Db, authorization: Annotated[str | None, Header()] = None) -> OwnerToken:
    token = read_token(request.app.state.config.pin_secret, (authorization or "").removeprefix("Bearer ").strip())
    if token is None or not db.scalar(select(OwnerAccount.active).where(OwnerAccount.id == token.owner_id)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please log in.")
    if db.scalar(select(BusinessSettings.id).where(BusinessSettings.business_id == token.business_id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nothing has arrived from the counter yet.")
    return token


Owner = Annotated[OwnerToken, Depends(phone_owner)]


def _freshness(db: Session, owner: OwnerToken) -> dict[str, Any]:
    last = db.scalar(select(func.max(Device.last_sync_at)).where(Device.business_id == owner.business_id))
    return {"last_updated": last.isoformat() if last else None}


@router.get("/today")
def today_view(owner: Owner, request: Request, db: Db) -> dict:
    """Today at a glance: sales, cash, M-Pesa, credit, shortages, voids, low stock."""
    bid, tz = owner.business_id, request.app.state.tz
    day = today(db, bid, tz)
    p = reports.Period(day, day)
    sales = reports.sales(db, bid, p)
    shifts = reports.handovers(db, bid, p)
    voids = reports.voids_and_discounts(db, bid, p)
    stock = reports.stock_status(db, bid, money=True)
    alerts = [f"{s['staff']} short KSh {-s['difference']:,}" for s in shifts if s["difference"] < 0]
    if voids["voids"]:
        alerts.append(f"{len(voids['voids'])} items removed after sending (KSh {voids['void_total']:,})")
    if stock["check"]:
        alerts.append(f"{len(stock['check'])} stock items below zero: count them")
    if stock["low"]:
        alerts.append(f"{len(stock['low'])} items low on stock")
    for device in db.scalars(select(Device).where(Device.business_id == bid, Device.active)):
        alerts += [problem for problem in device_problems(device, now())]
    return {
        "business_name": db.get(Business, bid).name,
        "day": day.isoformat(),
        **_freshness(db, owner),
        "sales": sales,
        "credit_collected": reports.credit_collected(db, bid, p),
        "shortages": [s for s in shifts if s["difference"] < 0],
        "voids": {"count": len(voids["voids"]), "total": voids["void_total"]},
        "low_stock": stock["low"],
        "check_stock": stock["check"],
        "open_shifts": reports.blockers(db, bid, day)["open_shifts"],
        "closed": db.scalar(select(DailyClosing.id).where(DailyClosing.business_id == bid,
                                                          DailyClosing.business_day == day)) is not None,
        "alerts": alerts,
    }


@router.get("/closing")
def closing(owner: Owner, request: Request, db: Db, day: date | None = None) -> dict:
    """The daily closing: as saved when the day was closed, otherwise as it stands."""
    bid = owner.business_id
    day = day or today(db, bid, request.app.state.tz)
    saved = db.scalar(select(DailyClosing).where(DailyClosing.business_id == bid, DailyClosing.business_day == day))
    report = saved.report if saved else reports.closing_report(db, bid, day, request.app.state.tz, money=True)
    return {**_freshness(db, owner), "day": day.isoformat(), "closed": saved is not None,
            "cash_box_counted": saved.cash_box_counted if saved else None, "report": report}


@router.get("/stock")
def stock_view(owner: Owner, request: Request, db: Db) -> dict:
    bid = owner.business_id
    day = today(db, bid, request.app.state.tz)
    return {**_freshness(db, owner), **reports.stock_status(db, bid, money=True),
            "variance": reports.variance_history(db, bid, reports.Period(day - timedelta(days=30), day), money=True)}


@router.get("/profit")
def profit_view(owner: Owner, request: Request, db: Db, start: date | None = None, end: date | None = None) -> dict:
    bid = owner.business_id
    end = end or today(db, bid, request.app.state.tz)
    start = start or end.replace(day=1)
    if end < start or end - start > timedelta(days=366):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose a period of up to a year.")
    p = reports.Period(start, end)
    return {**_freshness(db, owner), "start": start.isoformat(), "end": end.isoformat(),
            "profit": reports.profit(db, bid, p), "sales": reports.sales(db, bid, p),
            "shortages": reports.shortage_history(db, bid, p)}


@router.get("/debtors")
def debtors_view(owner: Owner, db: Db) -> dict:
    rows = reports.debtors(db, owner.business_id)
    return {**_freshness(db, owner), "debtors": rows, "total": sum(r["owed"] for r in rows)}
