"""Owner printouts for the counter's receipt printer (80 mm): the day's closing (or the
day so far), a blank stock count sheet, and the debtors list. They are reports, not
money documents, so they print straight away and aren't kept as tickets."""

from datetime import datetime

from app.printing.document import Row, cols, rule, text
from app.printing.layouts import ksh

FMT = "%d/%m/%Y %H:%M"


def _head(business: str, title: str, printed_by: str, when: datetime, *subtitles: str) -> list[Row]:
    rows = [text(business, size=2, bold=True, align="center"), text(title, bold=True, align="center")]
    rows += [text(line, align="center") for line in subtitles]
    return rows + [text(f"Printed {when.strftime(FMT)} by {printed_by}", align="center"), rule()]


def closing_slip(business: str, report: dict, closed: str | None, printed_by: str, when: datetime) -> list[Row]:
    """The daily closing, or the day so far when it isn't closed yet (an "X report")."""
    day = datetime.fromisoformat(report["day"]).strftime("%a %d/%m/%Y")
    title = "DAILY CLOSING" if closed else "TODAY SO FAR (NOT CLOSED)"
    rows = _head(business, title, printed_by, when, f"Business day {day}", *([f"Closed by {closed}"] if closed else []))
    s = report["sales"]
    rows += [
        text("SALES", bold=True),
        cols(f"Total sales ({s['bills']} bills)", ksh(s["total"]), bold=True),
        cols("  Cash", ksh(s["cash"])),
        cols("  M-Pesa", ksh(s["mpesa"])),
        cols("  Card", ksh(s["card"])),
        cols("  Credit", ksh(s["credit"])),
    ]
    if s["unpaid"]:
        rows.append(cols("  Unpaid (waiter responsible)", ksh(s["unpaid"])))
    rows += [cols("Average bill", ksh(s["average_bill"])), cols("Discounts given", ksh(s["discounts"])),
             cols("M-Pesa tips (not sales)", ksh(s["tips"]))]
    if report["credit_collected"]["total"]:
        rows.append(cols("Credit collected", ksh(report["credit_collected"]["total"])))
    for section in report["sections"]:
        rows.append(cols(f"  {section['section']}", ksh(section["sales"])))

    rows += [rule(), text("WAITERS (HAND-OVERS)", bold=True)]
    for w in report["waiters"]:
        d = w["difference"]
        result = "OK" if d == 0 else f"SHORT {ksh(-d)}" if d < 0 else f"OVER {ksh(d)}"
        rows += [cols(w["staff"], result, bold=d != 0), cols("  Expected / received", f"{ksh(w['expected'])} / {ksh(w['received'])}")]
    if not report["waiters"]:
        rows.append(text("No hand-overs yet."))
    open_shifts = report["blockers"]["open_shifts"]
    if open_shifts:
        rows.append(text(f"Still on shift: {', '.join(open_shifts)}"))
    if report["blockers"]["open_bills"]:
        rows.append(text(f"Open orders: {len(report['blockers']['open_bills'])}"))

    rows += [rule(), text("CONTROL", bold=True),
             cols(f"Items removed ({len(report['voids'])})", ksh(report["void_total"])),
             cols(f"Free items ({len(report['comps']['items'])})", ksh(report["comps"]["total"])),
             cols("Cancelled bills", str(len(report["cancelled"])))]
    for b in report["unpaid_bills"]:
        rows.append(cols(f"  Unpaid #{b['bill']:04d} {b['waiter']}", ksh(b["amount"])))

    box = report["cash_box"]
    rows += [rule(), text("CASH BOX", bold=True), cols("Expected in the box now", ksh(box["expected_now"]), bold=True)]
    for p in box["payouts"]:
        rows.append(cols(f"  Pay-out: {p['note'] or ''}"[:36], ksh(p["amount"])))

    stock = report["stock"]
    rows += [rule(), text("STOCK", bold=True), cols("Low stock items", str(len(stock["low"])))]
    for item in stock["low"][:12]:
        rows.append(text(f"  {item['item']}: {item['level']}"))
    if stock["check"]:
        rows.append(cols("Below zero (count these)", str(len(stock["check"]))))

    if "profit" in report:
        p = report["profit"]
        rows += [rule(), text("PROFIT (OWNER)", bold=True), cols("Sales", ksh(p["sales"])),
                 cols("- Cost of goods sold", ksh(p["cost_of_sales"])), cols("= Gross profit", ksh(p["gross_profit"]), bold=True),
                 cols("- Waste", ksh(p["waste"])), cols("- Expenses", ksh(p["expenses"])),
                 cols("= REAL PROFIT", ksh(p["real_profit"]), bold=True)]
    return rows + [rule(), text("End of report", align="center")]


def stock_sheet(business: str, items: list[tuple[str, str, str]], printed_by: str, when: datetime) -> list[Row]:
    """A blank count sheet: (station, item, counting unit). No system figures on it, so
    the count is honest; the numbers are typed into Stock take afterwards."""
    rows = _head(business, "STOCK COUNT SHEET", printed_by, when, "Count sealed bottles, plus the open one in tenths")
    station = None
    for st, name, unit in items:
        if st != station:
            station = st
            rows += [text(st.upper(), bold=True), rule()]
        rows.append(cols(f"{name} ({unit})", "_______"))
    if not items:
        rows.append(text("No stock items set up."))
    return rows + [rule(), cols("Counted by", "____________"), cols("Checked by", "____________")]


def debtors_slip(business: str, debtors: list[dict], printed_by: str, when: datetime) -> list[Row]:
    """Who owes, how much and since when, oldest first."""
    rows = _head(business, "DEBTORS (CREDIT)", printed_by, when)
    for d in debtors:
        since = d["since"].strftime("%d/%m/%Y") if d["since"] else ""
        rows += [cols(d["name"], ksh(d["owed"]), bold=True), text(f"  {d['phone'] or 'No phone'} · since {since}")]
    if not debtors:
        rows.append(text("Nobody owes anything."))
    return rows + [rule(), cols(f"TOTAL OWED ({len(debtors)})", ksh(sum(d["owed"] for d in debtors)), bold=True)]
