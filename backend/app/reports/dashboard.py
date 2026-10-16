"""The owner area's home page: today at a glance, compared with the same day last week
(like the home screens of Square, Toast and Lightspeed)."""

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.floor.models import Bill, BillLine, BillStatus, Table
from app.floor.service import amounts, place
from app.menu.models import MenuItem, SellOption
from app.menu.router import image_url
from app.payments.models import Payment
from app.printing.models import PrintStatus, Ticket
from app.reports import service as reports
from app.reports.service import FINISHED, Period
from app.settings.service import get_settings
from app.shifts.models import Shift, ShiftStatus
from app.staff.models import Staff


def _hours(bills: list[tuple[Bill, int]], tz: ZoneInfo, cutoff: int) -> list[int]:
    """Sales per hour of the business day, starting at the cut-off hour (24 slots)."""
    slots = [0] * 24
    for bill, total in bills:
        slots[(bill.closed_at.astimezone(tz).hour - cutoff) % 24] += total
    return slots


def _summary(bills: list[tuple[Bill, int]]) -> dict:
    total = sum(t for _, t in bills)
    return {"sales": total, "bills": len(bills), "average_bill": round(total / len(bills)) if bills else 0}


def dashboard(db: Session, bid: uuid.UUID, day: date, tz: ZoneInfo, at: datetime, money: bool) -> dict:
    cutoff = get_settings(db, bid).business_day_cutoff.hour
    week_ago = day - timedelta(days=7)

    def finished(d: date, until: datetime | None = None) -> list[tuple[Bill, int]]:
        q = select(Bill).where(Bill.business_id == bid, Bill.status.in_(FINISHED), Bill.business_day == d)
        if until is not None:
            q = q.where(Bill.closed_at <= until)
        return [(b, amounts(db, b).total) for b in db.scalars(q.order_by(Bill.closed_at))]

    today_bills = finished(day)
    last_week_all = finished(week_ago)
    last_week_so_far = [(b, t) for b, t in last_week_all if b.closed_at <= at - timedelta(days=7)]
    p = Period(day, day)
    sales = reports.sales(db, bid, p)

    # Best sellers by menu item (all sizes together), with the tile picture.
    items: dict[uuid.UUID, dict] = {}
    ids = [b.id for b, _ in today_bills]
    if ids:
        rows = db.execute(
            select(MenuItem.id, MenuItem.name, MenuItem.image, func.count(BillLine.id), func.sum(BillLine.unit_price))
            .join(SellOption, SellOption.id == BillLine.sell_option_id).join(MenuItem, MenuItem.id == SellOption.menu_item_id)
            .where(BillLine.bill_id.in_(ids), BillLine.voided_at.is_(None), BillLine.comp_reason.is_(None),
                   BillLine.combo_parent_id.is_(None))
            .group_by(MenuItem.id, MenuItem.name, MenuItem.image)
        )
        for item_id, name, image, quantity, total in rows:
            items[item_id] = {"item": name, "image": image_url(image), "quantity": quantity, "sales": int(total)}
    best = sorted(items.values(), key=lambda r: (-r["sales"], r["item"]))[:6]
    breakdown = reports.breakdown(db, bid, p, tz)

    # Right now: open bills, tables in use, who is on shift.
    open_bills = list(db.scalars(select(Bill).where(Bill.business_id == bid, Bill.status == BillStatus.open)))
    open_value = sum(amounts(db, b).balance for b in open_bills)
    tables = db.scalar(select(func.count(Table.id)).where(Table.business_id == bid, Table.active)) or 0
    on_shift = [
        {"staff": name, "since": started.isoformat(), "role": role.value}
        for name, role, started in db.execute(
            select(Staff.name, Staff.role, Shift.created_at).join(Staff, Staff.id == Shift.staff_id)
            .where(Shift.business_id == bid, Shift.status == ShiftStatus.open).order_by(Shift.created_at))
    ]
    oldest = min((b.created_at for b in open_bills), default=None)

    # What needs the owner's attention.
    alerts: list[dict] = []
    for s in reports.handovers(db, bid, p):
        if s["difference"] < 0:
            alerts.append({"tone": "bad", "text": f"{s['staff']} was short KSh {-s['difference']:,} at hand-over"})
    voids = reports.voids_and_discounts(db, bid, p)
    if voids["voids"]:
        alerts.append({"tone": "warn", "text": f"{len(voids['voids'])} items removed after sending (KSh {voids['void_total']:,})"})
    if voids["discounts"]:
        alerts.append({"tone": "warn", "text": f"{len(voids['discounts'])} discounts given (KSh {voids['discount_total']:,})"})
    comps = reports.comps(db, bid, p)
    if comps["items"]:
        alerts.append({"tone": "warn", "text": f"{len(comps['items'])} items given free (KSh {comps['total']:,} at menu price)"})
    if sales["unpaid"]:
        alerts.append({"tone": "warn", "text": f"KSh {sales['unpaid']:,} unpaid, waiters responsible"})
    unprinted = db.scalar(select(func.count(Ticket.id)).join(Bill, Bill.id == Ticket.bill_id).where(
        Ticket.business_id == bid, Ticket.status == PrintStatus.not_printed, Bill.status == BillStatus.open)) or 0
    if unprinted:
        alerts.append({"tone": "warn", "text": f"{unprinted} slips or tickets didn't print"})
    stock = reports.stock_status(db, bid, money=False)
    if stock["check"]:
        alerts.append({"tone": "bad", "text": f"{len(stock['check'])} stock items below zero: count them"})
    if stock["low"]:
        alerts.append({"tone": "warn", "text": f"Low on stock: {', '.join(s['item'] for s in stock['low'][:4])}"
                                              + (f" and {len(stock['low']) - 4} more" if len(stock["low"]) > 4 else "")})

    recent = []
    for bill, total in reversed(today_bills[-6:]):
        methods = sorted({m.value for m in db.scalars(select(Payment.method).where(
            Payment.bill_id == bill.id, Payment.reversed_at.is_(None)))})
        recent.append({"number": bill.number, "place": place(db, bill), "waiter": db.get(Staff, bill.waiter_id).name,
                       "total": total, "closed_at": bill.closed_at.isoformat(),
                       "paid_by": "credit" if bill.status is BillStatus.credit
                       else "unpaid" if bill.status is BillStatus.unpaid_responsible else "+".join(methods) or "cash"})

    out = {
        "day": day.isoformat(),
        "compare_day": week_ago.isoformat(),
        "cutoff_hour": cutoff,
        "now_slot": (at.astimezone(tz).hour - cutoff) % 24,
        "today": {**_summary(today_bills), "items": sum(r["quantity"] for r in items.values())},
        "last_week_so_far": _summary(last_week_so_far),
        "last_week_total": _summary(last_week_all)["sales"],
        "by_hour": {"today": _hours(today_bills, tz, cutoff), "last_week": _hours(last_week_all, tz, cutoff)},
        "payments": {k: sales[k] for k in ("cash", "mpesa", "card", "credit", "unpaid")},
        "best": best,
        "by_category": breakdown["by_category"][:6],
        "by_waiter": breakdown["by_waiter"],
        "live": {"open_bills": len(open_bills), "open_value": open_value, "tables": tables,
                 "tables_in_use": len({b.table_id for b in open_bills if b.table_id}),
                 "oldest_open": oldest.isoformat() if oldest else None, "on_shift": on_shift},
        "alerts": alerts,
        "recent": recent,
        "gross_profit": None,
    }
    if money:
        cost = reports.stock_money(db, bid, p)["cost_of_sales"]
        out["gross_profit"] = {"amount": sales["total"] - cost,
                               "margin": round((sales["total"] - cost) * 100 / sales["total"]) if sales["total"] else None}
    return out

