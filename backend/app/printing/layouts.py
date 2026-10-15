"""The printed layouts (masterplan 9.5). Each returns a document (see document.py)."""

from dataclasses import dataclass
from datetime import datetime

from app.printing.document import Row, cols, rule, text


@dataclass
class Header:
    business: str
    place: str  # "Table 2" or "Tab - Kamau"
    waiter: str
    when: datetime  # already in local time
    bill_number: int


@dataclass
class ItemRow:
    quantity: int
    name: str
    note: str | None
    amount: int  # quantity x unit price


@dataclass
class PaymentRow:
    label: str  # "Cash", "M-Pesa P2QM"
    amount: int
    tendered: int | None = None
    tip: int = 0


def ksh(amount: int) -> str:
    return f"{amount:,}"


def bill_no(number: int) -> str:
    return f"#{number:04d}"


def _time(h: Header) -> str:
    return h.when.strftime("%d/%m/%Y %H:%M")


def _station_ticket(title: str, h: Header, number: int, items: list[ItemRow], big_items: bool) -> list[Row]:
    doc = [
        text(h.place.upper(), size=2, bold=True),
        text(h.waiter, size=2),
        text(f"{title} {number}   {_time(h)}   Bill {bill_no(h.bill_number)}"),
        rule(),
    ]
    for item in items:
        doc.append(text(f"{item.quantity} x {item.name}", size=2 if big_items else 1, bold=True))
        if item.note:
            doc.append(text(f"   >> {item.note}", size=2 if big_items else 1))
    return doc


def bar_slip(h: Header, number: int, items: list[ItemRow]) -> list[Row]:
    return _station_ticket("BAR SLIP", h, number, items, big_items=False)


def kitchen_ticket(h: Header, number: int, items: list[ItemRow]) -> list[Row]:
    return _station_ticket("KITCHEN", h, number, items, big_items=True)


def _items(items: list[ItemRow]) -> list[Row]:
    doc = []
    for item in items:
        doc.append(cols(f"{item.quantity} x {item.name}", ksh(item.amount)))
        if item.note:
            doc.append(text(f"    {item.note}"))
    return doc


def _head(h: Header, title: str) -> list[Row]:
    return [
        text(h.business, size=2, bold=True, align="center"),
        text(title, bold=True, align="center"),
        rule(),
        cols(h.place, f"Bill {bill_no(h.bill_number)}"),
        cols(f"Served by {h.waiter}", _time(h)),
        rule(),
    ]


def _totals(gross: int, discount: int) -> list[Row]:
    rows = [rule()]
    if discount:
        rows += [cols("Subtotal", ksh(gross)), cols("Discount", f"-{ksh(discount)}")]
    return rows + [cols("TOTAL", ksh(gross - discount), size=2, bold=True)]


def bill(h: Header, items: list[ItemRow], gross: int, discount: int, paid: int, till: str | None) -> list[Row]:
    total = gross - discount
    doc = _head(h, "BILL") + _items(items) + _totals(gross, discount)
    if paid:
        doc += [cols("Already paid", ksh(paid)), cols("TO PAY", ksh(total - paid), bold=True)]
    if till:
        doc += [rule(), text("Pay by M-Pesa", bold=True, align="center"),
                text(f"Buy Goods Till No. {till}", size=2, bold=True, align="center")]
    doc.append(text("Not a KRA tax invoice", align="center"))
    return doc


def receipt(
    h: Header, number: int, items: list[ItemRow], gross: int, discount: int, payments: list[PaymentRow], footer: str
) -> list[Row]:
    doc = _head(h, f"RECEIPT No. {number:04d}") + _items(items) + _totals(gross, discount) + [rule()]
    for p in payments:
        doc.append(cols(p.label, ksh(p.amount)))
        if p.tendered is not None and p.tendered != p.amount:
            doc.append(cols("   Given / Change", f"{ksh(p.tendered)} / {ksh(p.tendered - p.amount)}"))
        if p.tip:
            doc.append(cols("   Tip (M-Pesa)", ksh(p.tip)))
    doc += [rule(), text("Not a KRA tax invoice", bold=True, align="center"), text(footer, align="center")]
    return doc


def handover_slip(
    business: str, staff: str, started: datetime, ended: datetime, cash: dict, received: int,
    receiver: str, agrees: bool | None, staff_note: str | None, receiver_note: str | None, forced: bool,
) -> list[Row]:
    """The cash hand-over slip (masterplan 4.6), printed for the waiter and the owner."""
    fmt = "%d/%m/%Y %H:%M"
    rows = [
        text(business, size=2, bold=True, align="center"),
        text("CASH HAND-OVER" + (" (FORCE-CLOSED)" if forced else ""), bold=True, align="center"),
        rule(),
        cols("Staff", staff),
        cols("Shift", f"{started.strftime(fmt)} - {ended.strftime('%H:%M')}"),
        rule(),
        cols(f"Total sales ({cash['bills']} bill{'' if cash['bills'] == 1 else 's'})", ksh(cash["total_sales"])),
        cols("- Paid by M-Pesa", ksh(cash["mpesa"])),
        cols("- Approved credit", ksh(cash["credit"])),
    ]
    if cash["cash_taken_by_others"]:
        rows.append(cols("- Cash taken by others", ksh(cash["cash_taken_by_others"])))
    rows += [
        cols("= Cash due from sales", ksh(cash["cash_due_from_sales"]), bold=True),
        text(f"  of which unpaid - your responsibility: {ksh(cash['unpaid_responsible'])}"),
    ]
    if cash["cash_taken_for_others"]:
        rows.append(cols("+ Cash taken on others' bills", ksh(cash["cash_taken_for_others"])))
    rows += [
        cols("+ Float received at start", ksh(cash["float_amount"])),
        cols("- M-Pesa tips", ksh(cash["mpesa_tips"])),
        cols("HAND OVER", ksh(cash["cash_to_hand_over"]), size=2, bold=True),
        rule(),
        cols("Received", ksh(received), bold=True),
    ]
    difference = received - cash["cash_to_hand_over"]
    result = "BALANCED" if difference == 0 else f"SHORT {ksh(-difference)}" if difference < 0 else f"OVER {ksh(difference)}"
    rows += [text(result, size=2, bold=True, align="center"), rule(), cols("Received by", receiver)]
    if receiver_note:
        rows.append(text(f"Note: {receiver_note}"))
    signed = "NOT PRESENT" if agrees is None else "AGREES" if agrees else "DISAGREES"
    rows.append(cols(staff, signed, bold=True))
    if staff_note:
        rows.append(text(f"Note: {staff_note}"))
    return rows
