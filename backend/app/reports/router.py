from datetime import date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.audit import service as audit
from app.auth.deps import Actor, Db, require
from app.auth.permissions import Action, Level, level
from app.db import now
from app.floor.service import cancel_untouched
from app.reports import export, mailer
from app.reports.dashboard import dashboard
from app.reports import service as reports
from app.reports.models import DailyClosing
from app.settings.models import Business
from app.settings.service import get_settings, today
from app.staff.models import Staff

router = APIRouter(tags=["reports"])

Closer = Annotated[Actor, Depends(require(Action.run_daily_closing))]
Owner = Annotated[Actor, Depends(require(Action.view_financials))]
MAX_PERIOD = timedelta(days=366)


class ClosingOut(BaseModel):
    day: date
    closed: bool
    closed_by: str | None
    closed_at: datetime | None
    cash_box_counted: int | None
    note: str | None
    report: dict[str, Any]


def _money(actor: Actor) -> bool:
    return level(actor.staff.role, Action.view_financials) is Level.allow


def _strip(report: dict) -> dict:
    """A supervisor's copy of a saved closing: no profit or shilling values."""
    out = {k: v for k, v in report.items() if k != "profit"}
    out["stock"] = {**report["stock"], "value": None}
    out["stock_variance"] = [{**v, "value": None} for v in report["stock_variance"]]
    return out


@router.get("/dashboard")
def get_dashboard(actor: Closer, request: Request, db: Db) -> dict[str, Any]:
    """The owner area's home page: today so far against the same day last week, what's
    selling, who's on shift and what needs attention. Profit for the owner only."""
    tz = request.app.state.tz
    return dashboard(db, actor.business_id, today(db, actor.business_id, tz), tz, now(), _money(actor))


@router.get("/closing")
def get_closing(actor: Closer, request: Request, db: Db, day: date | None = None) -> ClosingOut:
    """The daily closing for a business day (default: today). Once closed, the saved
    report is shown as it was at closing."""
    day = day or today(db, actor.business_id, request.app.state.tz)
    saved = db.scalar(select(DailyClosing).where(DailyClosing.business_id == actor.business_id,
                                                 DailyClosing.business_day == day))
    if saved:
        report = saved.report if _money(actor) else _strip(saved.report)
        return ClosingOut(day=day, closed=True, closed_by=db.get(Staff, saved.created_by).name, closed_at=saved.created_at,
                          cash_box_counted=saved.cash_box_counted, note=saved.note, report=report)
    report = reports.closing_report(db, actor.business_id, day, request.app.state.tz, _money(actor))
    return ClosingOut(day=day, closed=False, closed_by=None, closed_at=None, cash_box_counted=None, note=None, report=report)


class CloseDayIn(BaseModel):
    day: date
    cash_box_counted: Annotated[int, Field(ge=0, le=100_000_000)] | None = None
    note: Annotated[str, Field(max_length=200)] | None = None


@router.post("/closing", status_code=status.HTTP_201_CREATED)
def close_day(body: CloseDayIn, actor: Closer, request: Request, db: Db) -> ClosingOut:
    """Close the business day once every shift is handed over and every bill finished.
    The full report (with profit) is saved; it can't be changed afterwards."""
    tz = request.app.state.tz
    if body.day > today(db, actor.business_id, tz):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That business day hasn't started.")
    if db.scalar(select(DailyClosing.id).where(DailyClosing.business_id == actor.business_id,
                                               DailyClosing.business_day == body.day)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This day is already closed.")
    cancel_untouched(db, actor.business_id)
    blocking = reports.blockers(db, actor.business_id, body.day)
    if blocking["open_shifts"] or blocking["open_bills"]:
        names = ", ".join(blocking["open_shifts"]) or "none"
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Not yet: shifts still open ({names}) and {len(blocking['open_bills'])} open bills.")
    report = reports.closing_report(db, actor.business_id, body.day, tz, money=True)
    expected = report["cash_box"]["expected_now"]
    closing = DailyClosing(business_id=actor.business_id, created_by=actor.staff.id, business_day=body.day,
                           cash_box_expected=expected, cash_box_counted=body.cash_box_counted, note=body.note,
                           report=report)
    db.add(closing)
    db.flush()
    business = db.get(Business, actor.business_id).name
    mailer.queue_closing(db, request.app.state.config, business, get_settings(db, actor.business_id).report_emails,
                         report, export.closing_workbook(business, report))
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="day.closed",
                 entity_type="daily_closing", entity_id=closing.id,
                 details={"day": body.day.isoformat(), "sales": report["sales"]["total"],
                          "cash_box_expected": expected, "cash_box_counted": body.cash_box_counted})
    db.commit()
    return get_closing(actor, request, db, body.day)


class ReportOut(BaseModel):
    start: date
    end: date
    sales: dict
    profit: dict
    breakdown: dict
    expenses: dict
    shortages: list[dict]
    variance: list[dict]
    debtors: list[dict]
    stock: dict
    voids: dict
    comps: dict
    credit_collected: dict


@router.get("/reports")
def report(
    actor: Owner, request: Request, db: Db,
    start: Annotated[date, Query()], end: Annotated[date, Query()],
) -> ReportOut:
    """Owner reports for any period of business days (masterplan 4.9)."""
    if end < start or end - start > MAX_PERIOD:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose a period of up to a year.")
    bid, p = actor.business_id, reports.Period(start, end)
    return ReportOut(
        start=start, end=end, sales=reports.sales(db, bid, p), profit=reports.profit(db, bid, p),
        breakdown=reports.breakdown(db, bid, p, request.app.state.tz), expenses=reports.expenses(db, bid, p),
        shortages=reports.shortage_history(db, bid, p), variance=reports.variance_history(db, bid, p, money=True),
        debtors=reports.debtors(db, bid), stock=reports.stock_status(db, bid, money=True),
        voids=reports.voids_and_discounts(db, bid, p), comps=reports.comps(db, bid, p),
        credit_collected=reports.credit_collected(db, bid, p),
    )


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _download(data: bytes, name: str) -> Response:
    return Response(data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/closing/export")
def export_closing(actor: Closer, request: Request, db: Db, day: date | None = None) -> Response:
    """The daily closing as an Excel file (a supervisor's copy has no profit or values)."""
    closing = get_closing(actor, request, db, day)
    business = db.get(Business, actor.business_id).name
    return _download(export.closing_workbook(business, closing.report), f"closing-{closing.day}.xlsx")


@router.get("/reports/export")
def export_report(
    actor: Owner, request: Request, db: Db,
    start: Annotated[date, Query()], end: Annotated[date, Query()],
) -> Response:
    r = report(actor, request, db, start, end)
    business = db.get(Business, actor.business_id).name
    return _download(export.report_workbook(business, r.model_dump(mode="json")), f"report-{start}-to-{end}.xlsx")
