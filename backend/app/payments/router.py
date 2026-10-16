import re
import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.audit import service as audit
from app.auth import service as auth
from app.auth.deps import Actor, CurrentActor, Db
from app.auth.permissions import Action, Level, level
from app.credit.models import CreditCustomer
from app.db import now
from app.floor.models import Bill, BillStatus
from app.floor.schemas import BillOut, bill_detail
from app.floor.service import Printing, amounts, bill_lines, finish_bill, group_items, load_bill, totals
from app.payments.models import Method, Payment
from app.printing import layouts
from app.printing.models import PrinterName, TicketKind
from app.sequences import next_number
from app.settings.models import MpesaCodeEntry
from app.settings.service import get_settings, today
from app.shifts.service import current_shift

router = APIRouter(tags=["payments"])

DUPLICATE_WINDOW = timedelta(days=7)
CODE_PATTERNS = {MpesaCodeEntry.last4: re.compile(r"^[A-Z0-9]{4}$"), MpesaCodeEntry.full: re.compile(r"^[A-Z0-9]{10}$")}
CODE_HELP = {MpesaCodeEntry.last4: "the last 4 characters", MpesaCodeEntry.full: "the full 10-character code"}

Amount = Annotated[int, Field(ge=1, le=10_000_000)]


class PaymentIn(BaseModel):
    method: Method
    amount: Amount  # what goes towards the bill
    tendered: Amount | None = None  # cash handed over; defaults to the amount
    tip: Annotated[int, Field(ge=0, le=1_000_000)] = 0  # M-Pesa only
    mpesa_code: Annotated[str, Field(max_length=12)] | None = None
    card_ref: Annotated[str, Field(max_length=12)] | None = None  # last 4 of the card slip's reference
    # A repeated M-Pesa code: waiters need an approval; owners and supervisors confirm.
    approval_id: uuid.UUID | None = None
    confirm_duplicate: bool = False


class PaymentResult(BaseModel):
    bill: BillOut
    change: int


def mpesa_ref(mode: MpesaCodeEntry, code: str | None) -> str | None:
    if mode is MpesaCodeEntry.none:
        return None
    code = (code or "").strip().upper()
    if not CODE_PATTERNS[mode].match(code):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Enter {CODE_HELP[mode]} of the M-Pesa code (letters and numbers).")
    return code


def _duplicate_of(db: Db, actor: Actor, ref: str) -> Bill | None:
    """An M-Pesa payment in the last 7 days whose code ends the same way. Compares the
    last 4 characters, so it also works across a change of the code-entry setting."""
    return db.scalar(
        select(Bill).join(Payment, Payment.bill_id == Bill.id)
        .where(Payment.business_id == actor.business_id, Payment.method == Method.mpesa,
               func.right(Payment.mpesa_ref, 4) == ref[-4:],
               Payment.created_at >= now() - DUPLICATE_WINDOW)
        .order_by(Payment.created_at.desc()).limit(1)
    )


@router.post("/bills/{bill_id}/payments", status_code=status.HTTP_201_CREATED)
def take_payment(bill_id: uuid.UUID, body: PaymentIn, actor: CurrentActor, request: Request, db: Db) -> PaymentResult:
    """Record one payment. Several payments (cash and M-Pesa, several people) can share
    a bill; it closes, and the receipt prints twice, when payments equal the total."""
    bill = load_bill(db, actor, bill_id, Action.take_payment)
    total, paid, _ = totals(db, bill)
    if total == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing to pay on this bill.")
    if body.amount > total - paid:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Only {total - paid:,} is left to pay.")

    settings = get_settings(db, actor.business_id)
    tendered, ref, card_ref, approval, duplicate = None, None, None, None, None
    if body.method is Method.card:
        if body.tip:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tips are recorded only for M-Pesa.")
        card_ref = (body.card_ref or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{4,12}", card_ref):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Enter the last 4 characters of the card slip's reference.")
    elif body.method is Method.cash:
        if body.tip:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tips are recorded only for M-Pesa.")
        tendered = body.tendered if body.tendered is not None else body.amount
        if tendered < body.amount:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Cash given is less than the amount.")
    else:
        ref = mpesa_ref(settings.mpesa_code_entry, body.mpesa_code)
        duplicate = _duplicate_of(db, actor, ref) if ref else None
        if duplicate:
            confirmed = level(actor.staff.role, Action.mpesa_duplicate_override) is Level.allow and body.confirm_duplicate
            if not confirmed and not body.approval_id:
                raise HTTPException(status.HTTP_409_CONFLICT, {
                    "code": "mpesa_duplicate",
                    "message": f"These characters were used on bill #{duplicate.number:04d}. Check the customer's message.",
                    "bill_number": duplicate.number,
                })
            approval = auth.authorize(db, actor, Action.mpesa_duplicate_override, body.approval_id)

    tz = request.app.state.tz
    payment = Payment(
        business_id=actor.business_id, created_by=actor.staff.id, bill_id=bill.id, method=body.method,
        amount=body.amount, tendered=tendered, tip=body.tip, mpesa_ref=ref, card_ref=card_ref,
        business_day=today(db, actor.business_id, tz),
        shift_id=current_shift(db, actor.business_id, actor.staff.id, tz).id,
    )
    db.add(payment)
    db.flush()
    if duplicate:
        audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id,
                     action="payment.mpesa_duplicate_accepted", entity_type="payment",
                     entity_id=payment.id, approval=approval,
                     details={"bill": bill.number, "ref": ref, "earlier_bill": duplicate.number})

    receipt = None
    if paid + body.amount == total:
        finish_bill(db, bill, BillStatus.paid, tz)
        receipt = make_receipt(db, actor, bill, Printing(tz), settings.receipt_footer)
    db.commit()

    # Waiters keep the cash they take until hand-over, so the drawer stays shut.
    if receipt:
        request.app.state.printing.print_tickets([receipt])
    return PaymentResult(bill=bill_detail(db, bill), change=tendered - body.amount if tendered is not None else 0)


def make_receipt(db: Db, actor: Actor, bill: Bill, printing: Printing, footer: str):
    """The receipt (customer copy + COUNTER COPY). A bill closed on credit shows the
    credit customer in place of a payment for what is left."""
    lines = [l for l in bill_lines(db, bill) if l.voided_at is None]
    payments = db.scalars(select(Payment).where(Payment.bill_id == bill.id, Payment.reversed_at.is_(None))
                          .order_by(Payment.created_at))
    rows = [
        layouts.PaymentRow(label="Cash", amount=p.amount, tendered=p.tendered) if p.method is Method.cash
        else layouts.PaymentRow(label=f"Card ref {p.card_ref}", amount=p.amount) if p.method is Method.card
        else layouts.PaymentRow(label=f"M-Pesa {p.mpesa_ref or ''}".strip(), amount=p.amount, tip=p.tip)
        for p in payments
    ]
    if bill.status is BillStatus.credit:
        customer = db.get(CreditCustomer, bill.credit_customer_id)
        rows.append(layouts.PaymentRow(label=f"On credit: {customer.name}", amount=bill.credit_amount))
    a = amounts(db, bill)
    number = next_number(db, actor.business_id, "receipt")
    content = layouts.receipt(printing.header(db, bill, now()), number, group_items(lines, for_customer=True),
                              a.gross, a.discount, rows, footer)
    return printing.new_ticket(db, actor, bill, TicketKind.receipt, PrinterName.counter, content,
                               number, copies=[None, "COUNTER COPY"])
