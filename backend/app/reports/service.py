"""Figures for the daily closing, reports and the owner's phone (masterplan 4.9-4.10).

The same functions run at the counter and in the cloud (on the synced copy), so both
always show the same numbers. Everything is by business day (the owner's cut-off).
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.models import AuditEntry
from app.auth.models import Approval
from app.credit.models import CreditCollection, CreditCustomer
from app.credit.service import oldest_unpaid, owed
from app.expenses.models import Expense
from app.floor.models import Bill, BillLine, BillStatus
from app.floor.service import amounts, display_name, place
from app.menu.models import Category, MenuItem, SellOption
from app.payments.models import Method, Payment
from app.settings.service import get_settings
from app.shifts.models import CashMovement, CashMovementKind, Handover, Shift, ShiftStatus, ShortageStatus
from app.staff.models import Staff
from app.stock import service as stock
from app.stock.models import MovementKind, StockItem, StockMovement, StockTake, StockTakeLine

FINISHED = (BillStatus.paid, BillStatus.credit, BillStatus.unpaid_responsible)


@dataclass(frozen=True)
class Period:
    start: date
    end: date  # inclusive


def _name(db: Session, staff_id: uuid.UUID | None) -> str | None:
    return db.get(Staff, staff_id).name if staff_id else None


def finished_bills(db: Session, bid: uuid.UUID, p: Period) -> list[Bill]:
    return list(db.scalars(select(Bill).where(
        Bill.business_id == bid, Bill.status.in_(FINISHED), Bill.business_day.between(p.start, p.end),
    ).order_by(Bill.number)))


def sales(db: Session, bid: uuid.UUID, p: Period) -> dict:
    """Sales and how they were paid. cash + mpesa + credit + unpaid = total."""
    bills = finished_bills(db, bid, p)
    out = dict(bills=len(bills), total=0, cash=0, mpesa=0, credit=0, unpaid=0, discounts=0, tips=0)
    for bill in bills:
        a = amounts(db, bill)
        out["total"] += a.total
        out["discounts"] += a.discount
        if bill.status is BillStatus.credit:
            out["credit"] += bill.credit_amount
        elif bill.status is BillStatus.unpaid_responsible:
            out["unpaid"] += a.balance
    if bills:
        for method, total, tips in db.execute(
            select(Payment.method, func.sum(Payment.amount), func.sum(Payment.tip))
            .where(Payment.bill_id.in_([b.id for b in bills]), Payment.reversed_at.is_(None)).group_by(Payment.method)
        ):
            out["cash" if method is Method.cash else "mpesa"] += total
            out["tips"] += tips
    out["average_bill"] = round(out["total"] / len(bills)) if bills else 0
    return out


def _who(db: Session, entry: AuditEntry | None) -> tuple[str | None, str | None]:
    """(asked by, approved by) for an action that may have needed approval."""
    if entry is None:
        return None, None
    if entry.approval_id:
        approval = db.get(Approval, entry.approval_id)
        return _name(db, approval.created_by), _name(db, approval.approved_by)
    return _name(db, entry.created_by), _name(db, entry.created_by)


def voids_and_discounts(db: Session, bid: uuid.UUID, p: Period) -> dict:
    bill_ids = {b.id: b for b in db.scalars(select(Bill).where(Bill.business_id == bid,
                                                               Bill.business_day.between(p.start, p.end)))}
    voids = []
    for line in db.scalars(select(BillLine).where(BillLine.bill_id.in_(bill_ids), BillLine.voided_at.is_not(None))
                           .order_by(BillLine.voided_at)):
        entry = db.scalar(select(AuditEntry).where(AuditEntry.action == "bill_line.voided", AuditEntry.entity_id == line.id))
        asked, approved = _who(db, entry)
        voids.append(dict(bill=bill_ids[line.bill_id].number, item=display_name(line.item_name, line.option_label),
                          price=line.unit_price, reason=line.void_reason.value, asked_by=asked, approved_by=approved,
                          at=line.voided_at.isoformat()))
    discounts = []
    for bill in bill_ids.values():
        if bill.status not in FINISHED or not bill.discount_value:
            continue
        entry = db.scalar(select(AuditEntry).where(AuditEntry.action == "bill.discounted", AuditEntry.entity_id == bill.id)
                          .order_by(AuditEntry.created_at.desc()).limit(1))
        asked, approved = _who(db, entry)
        discounts.append(dict(bill=bill.number, amount=amounts(db, bill).discount,
                              reason=entry.details.get("reason") if entry else None, asked_by=asked, approved_by=approved))
    cancelled = []
    for bill in bill_ids.values():
        if bill.status is BillStatus.cancelled and bill.cancel_reason:
            entry = db.scalar(select(AuditEntry).where(AuditEntry.action == "bill.cancelled", AuditEntry.entity_id == bill.id))
            asked, approved = _who(db, entry)
            cancelled.append(dict(bill=bill.number, total=entry.details.get("total") if entry else None,
                                  reason=bill.cancel_reason.value, asked_by=asked, approved_by=approved))
    return dict(voids=voids, void_total=sum(v["price"] for v in voids), discounts=sorted(discounts, key=lambda d: d["bill"]),
                discount_total=sum(d["amount"] for d in discounts), cancelled=sorted(cancelled, key=lambda c: c["bill"]))


def stock_money(db: Session, bid: uuid.UUID, p: Period) -> dict:
    """Shillings at buying price: cost of what was sold, waste, and stock-take variance."""
    by_kind = defaultdict(Decimal)
    for kind, worth in db.execute(
        select(StockMovement.kind, func.sum(StockMovement.quantity * StockMovement.unit_cost))
        .where(StockMovement.business_id == bid, StockMovement.business_day.between(p.start, p.end))
        .group_by(StockMovement.kind)
    ):
        by_kind[kind] = worth or Decimal(0)
    whole = lambda d: int(d.quantize(Decimal(1)))  # noqa: E731
    return dict(
        cost_of_sales=whole(-(by_kind[MovementKind.sale] + by_kind[MovementKind.sale_return])),
        waste=whole(-by_kind[MovementKind.waste]),
        variance=whole(by_kind[MovementKind.stock_take]),  # below 0: stock missing
    )


def expenses(db: Session, bid: uuid.UUID, p: Period) -> dict:
    by_category = defaultdict(int)
    for category, total in db.execute(
        select(Expense.category, func.sum(Expense.amount))
        .where(Expense.business_id == bid, Expense.business_day.between(p.start, p.end)).group_by(Expense.category)
    ):
        by_category[category.value] += total
    payouts = -db.scalar(select(func.coalesce(func.sum(CashMovement.amount), 0)).where(
        CashMovement.business_id == bid, CashMovement.kind == CashMovementKind.payout,
        CashMovement.business_day.between(p.start, p.end)))
    if payouts:
        by_category["payouts"] += payouts
    return dict(by_category=dict(sorted(by_category.items(), key=lambda kv: -kv[1])), total=sum(by_category.values()))


def profit(db: Session, bid: uuid.UUID, p: Period) -> dict:
    """Sales - cost of goods sold - waste + variance - expenses = real profit. Pay-outs
    from takings count as expenses. Sales are after discounts."""
    s, m, e = sales(db, bid, p)["total"], stock_money(db, bid, p), expenses(db, bid, p)
    gross = s - m["cost_of_sales"]
    return dict(sales=s, cost_of_sales=m["cost_of_sales"], gross_profit=gross, waste=m["waste"], variance=m["variance"],
                expenses=e["total"], expenses_by_category=e["by_category"],
                real_profit=gross - m["waste"] + m["variance"] - e["total"])


def breakdown(db: Session, bid: uuid.UUID, p: Period, tz: ZoneInfo) -> dict:
    """Sales by item, category, waiter and hour; best and worst sellers. Item amounts are
    before whole-bill discounts; the waiter figures are after."""
    bills = finished_bills(db, bid, p)
    cutoff = get_settings(db, bid).business_day_cutoff.hour
    by_item: dict[str, dict] = {}
    by_category: dict[str, int] = defaultdict(int)
    by_hour: dict[int, int] = defaultdict(int)
    by_waiter: dict[str, dict] = {}
    option_category = {
        o: c for o, c in db.execute(select(SellOption.id, Category.name).join(MenuItem, MenuItem.id == SellOption.menu_item_id)
                                    .join(Category, Category.id == MenuItem.category_id).where(SellOption.business_id == bid))
    }
    for bill in bills:
        name = _name(db, bill.waiter_id)
        w = by_waiter.setdefault(name, dict(waiter=name, bills=0, sales=0))
        w["bills"] += 1
        w["sales"] += amounts(db, bill).total
    if bills:
        for line in db.scalars(select(BillLine).where(BillLine.bill_id.in_([b.id for b in bills]), BillLine.voided_at.is_(None))):
            key = display_name(line.item_name, line.option_label)
            row = by_item.setdefault(key, dict(item=key, quantity=0, sales=0))
            row["quantity"] += 1
            row["sales"] += line.unit_price
            by_category[option_category.get(line.sell_option_id, "Other")] += line.unit_price
            by_hour[line.created_at.astimezone(tz).hour] += line.unit_price
    items = sorted(by_item.values(), key=lambda r: -r["sales"])
    sold = set(by_item)
    never = [display_name(i, o) for o, i in db.execute(
        select(SellOption.label, MenuItem.name).join(MenuItem, MenuItem.id == SellOption.menu_item_id)
        .where(SellOption.business_id == bid, SellOption.active, MenuItem.active)) if display_name(i, o) not in sold]
    return dict(
        by_item=items,
        by_category=[dict(category=c, sales=v) for c, v in sorted(by_category.items(), key=lambda kv: -kv[1])],
        by_waiter=sorted(by_waiter.values(), key=lambda r: -r["sales"]),
        # In business-day order: a bar's night runs past midnight, so 23:00 comes before 00:00.
        by_hour=[dict(hour=h, sales=by_hour[h]) for h in sorted(by_hour, key=lambda h: (h - cutoff) % 24)],
        best=items[:5],
        worst=([dict(item=n, quantity=0, sales=0) for n in sorted(never)] + items[::-1])[:5],
    )


def handovers(db: Session, bid: uuid.UUID, p: Period) -> list[dict]:
    rows = []
    for h, shift in db.execute(select(Handover, Shift).join(Shift, Shift.id == Handover.shift_id)
                               .where(Handover.business_id == bid, Shift.business_day.between(p.start, p.end))
                               .order_by(Handover.created_at)):
        status = db.scalar(select(ShortageStatus.outcome).where(ShortageStatus.handover_id == h.id)
                           .order_by(ShortageStatus.created_at.desc()).limit(1))
        rows.append(dict(staff=_name(db, h.staff_id), day=shift.business_day.isoformat(), expected=h.expected,
                         received=h.received, difference=h.difference, receiver=_name(db, h.created_by),
                         agrees=h.staff_agrees, forced=h.forced, shortage_status=status.value if status else None,
                         cash_up=h.summary))
    return rows


def shortage_history(db: Session, bid: uuid.UUID, p: Period) -> list[dict]:
    per: dict[str, dict] = {}
    for h in handovers(db, bid, p):
        r = per.setdefault(h["staff"], dict(staff=h["staff"], shifts=0, times_short=0, short=0, times_over=0, over=0))
        r["shifts"] += 1
        if h["difference"] < 0:
            r["times_short"] += 1
            r["short"] += -h["difference"]
        elif h["difference"] > 0:
            r["times_over"] += 1
            r["over"] += h["difference"]
    return sorted(per.values(), key=lambda r: -r["short"])


def variance_history(db: Session, bid: uuid.UUID, p: Period, money: bool) -> list[dict]:
    tot = get_settings(db, bid).tot_size_ml
    rows = []
    for line, take, item in db.execute(
        select(StockTakeLine, StockTake, StockItem).join(StockTake, StockTake.id == StockTakeLine.stock_take_id)
        .join(StockItem, StockItem.id == StockTakeLine.stock_item_id)
        .where(StockTake.business_id == bid, StockTake.business_day.between(p.start, p.end))
        .order_by(StockTake.created_at)
    ):
        variance = line.counted - line.expected
        if not variance:
            continue
        rows.append(dict(day=take.business_day.isoformat(), item=item.name,
                         variance=("Missing " if variance < 0 else "Extra ") + stock.describe(item, abs(variance), tot),
                         value=stock.value(variance, line.unit_cost) if money else None))
    return rows


def debtors(db: Session, bid: uuid.UUID) -> list[dict]:
    rows = []
    for c in db.scalars(select(CreditCustomer).where(CreditCustomer.business_id == bid)):
        o = owed(db, c.id)
        if o > 0:
            since = oldest_unpaid(db, c.id)
            rows.append(dict(name=c.name, phone=c.phone, owed=o, limit=c.credit_limit, since=since.isoformat() if since else None))
    return sorted(rows, key=lambda r: r["since"] or "")


def stock_status(db: Session, bid: uuid.UUID, money: bool) -> dict:
    tot = get_settings(db, bid).tot_size_ml
    lv = stock.levels(db, bid)
    low, check, value = [], [], 0
    for item in db.scalars(select(StockItem).where(StockItem.business_id == bid, StockItem.active).order_by(StockItem.name)):
        q = lv.get(item.id, Decimal(0))
        value += stock.value(max(q, Decimal(0)), item.unit_cost)
        row = dict(item=item.name, level=stock.describe(item, q, tot))
        if q < 0:
            check.append(row)
        elif item.reorder_level > 0 and q <= item.reorder_level:
            low.append(row)
    return dict(low=low, check=check, value=value if money else None)


def cash_box(db: Session, bid: uuid.UUID, day: date) -> dict:
    expected = db.scalar(select(func.coalesce(func.sum(CashMovement.amount), 0)).where(CashMovement.business_id == bid))
    by_kind = {k.value: 0 for k in CashMovementKind}
    for kind, total in db.execute(select(CashMovement.kind, func.sum(CashMovement.amount))
                                  .where(CashMovement.business_id == bid, CashMovement.business_day == day)
                                  .group_by(CashMovement.kind)):
        by_kind[kind.value] = total
    payouts = [dict(amount=-m.amount, note=m.note, by=_name(db, m.created_by)) for m in db.scalars(
        select(CashMovement).where(CashMovement.business_id == bid, CashMovement.business_day == day,
                                   CashMovement.kind == CashMovementKind.payout).order_by(CashMovement.created_at))]
    return dict(expected_now=expected, today=by_kind, payouts=payouts)


def credit_collected(db: Session, bid: uuid.UUID, p: Period) -> dict:
    out = dict(cash=0, mpesa=0)
    for method, total in db.execute(select(CreditCollection.method, func.sum(CreditCollection.amount))
                                    .where(CreditCollection.business_id == bid,
                                           CreditCollection.business_day.between(p.start, p.end))
                                    .group_by(CreditCollection.method)):
        out[method.value] = total
    out["total"] = out["cash"] + out["mpesa"]
    return out


def blockers(db: Session, bid: uuid.UUID, day: date) -> dict:
    """What stops the day being closed: shifts not handed over, bills still open."""
    shifts = db.scalars(select(Shift).where(Shift.business_id == bid, Shift.status == ShiftStatus.open,
                                            Shift.business_day <= day))
    bills = db.scalars(select(Bill).where(Bill.business_id == bid, Bill.status == BillStatus.open, Bill.business_day <= day))
    return dict(open_shifts=[_name(db, s.staff_id) for s in shifts],
                open_bills=[dict(bill=b.number, place=place(db, b), waiter=_name(db, b.waiter_id)) for b in bills])


def closing_report(db: Session, bid: uuid.UUID, day: date, tz: ZoneInfo, money: bool) -> dict:
    """The daily closing (masterplan 4.9). Without `money` (a supervisor), profit, buying
    prices and stock values are left out."""
    p = Period(day, day)
    unpaid = [dict(bill=b.number, place=place(db, b), waiter=_name(db, b.waiter_id), amount=amounts(db, b).balance)
              for b in finished_bills(db, bid, p) if b.status is BillStatus.unpaid_responsible]
    shifts = handovers(db, bid, p)
    report = dict(
        day=day.isoformat(),
        sales=sales(db, bid, p),
        credit_collected=credit_collected(db, bid, p),
        cash_box=cash_box(db, bid, day),
        waiters=shifts,
        shortages=[s for s in shifts if s["difference"] < 0],
        overs=[s for s in shifts if s["difference"] > 0],
        **voids_and_discounts(db, bid, p),
        unpaid_bills=unpaid,
        stock_variance=variance_history(db, bid, p, money),
        stock=stock_status(db, bid, money),
        blockers=blockers(db, bid, day),
    )
    if money:
        report["profit"] = profit(db, bid, p)
    return report
