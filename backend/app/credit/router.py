import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.audit import service as audit
from app.auth import service as auth
from app.auth.deps import Actor, CurrentActor, Db, require
from app.auth.permissions import Action
from app.credit.models import CreditCollection, CreditCustomer
from app.db import now
from app.floor.models import Bill, BillStatus
from app.floor.schemas import BillOut, bill_detail
from app.floor.service import Printing, amounts, finish_bill, load_bill
from app.payments.models import Method
from app.payments.router import make_receipt, mpesa_ref
from app.settings.service import get_settings, today
from app.shifts.models import CashMovement, CashMovementKind
from app.staff.models import Role, Staff

router = APIRouter(tags=["credit"])

Owner = Annotated[Actor, Depends(require(Action.manage_business))]
Collector = Annotated[Actor, Depends(require(Action.collect_credit_payment))]


def owed(db: Db, customer_id: uuid.UUID) -> int:
    credited = db.scalar(select(func.coalesce(func.sum(Bill.credit_amount), 0))
                         .where(Bill.credit_customer_id == customer_id, Bill.status == BillStatus.credit))
    collected = db.scalar(select(func.coalesce(func.sum(CreditCollection.amount), 0))
                          .where(CreditCollection.customer_id == customer_id))
    return credited - collected


def oldest_unpaid(db: Db, customer_id: uuid.UUID) -> datetime | None:
    """When the oldest credit still not paid off was given. Payments clear the oldest first."""
    collected = db.scalar(select(func.coalesce(func.sum(CreditCollection.amount), 0))
                          .where(CreditCollection.customer_id == customer_id))
    for closed_at, amount in db.execute(
        select(Bill.closed_at, Bill.credit_amount)
        .where(Bill.credit_customer_id == customer_id, Bill.status == BillStatus.credit)
        .order_by(Bill.closed_at)
    ):
        if collected < amount:
            return closed_at
        collected -= amount
    return None


class CustomerOut(BaseModel):
    id: uuid.UUID
    name: str
    phone: str | None
    credit_limit: int
    owed: int
    available: int
    oldest_unpaid: datetime | None


def _out(db: Db, c: CreditCustomer) -> CustomerOut:
    o = owed(db, c.id)
    return CustomerOut(id=c.id, name=c.name, phone=c.phone, credit_limit=c.credit_limit, owed=o,
                       available=max(c.credit_limit - o, 0), oldest_unpaid=oldest_unpaid(db, c.id) if o > 0 else None)


def _customer(db: Db, actor: Actor, customer_id: uuid.UUID) -> CreditCustomer:
    c = db.get(CreditCustomer, customer_id)
    if c is None or c.business_id != actor.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found.")
    return c


@router.get("/credit/customers")
def list_customers(actor: CurrentActor, db: Db) -> list[CustomerOut]:
    rows = db.scalars(select(CreditCustomer).where(CreditCustomer.business_id == actor.business_id,
                                                   CreditCustomer.active).order_by(CreditCustomer.name))
    return [_out(db, c) for c in rows]


@router.get("/credit/debtors")
def debtors(actor: Collector, db: Db) -> list[CustomerOut]:
    """Who owes, how much and since when, oldest first."""
    rows = [_out(db, c) for c in db.scalars(select(CreditCustomer).where(CreditCustomer.business_id == actor.business_id))]
    owing = [r for r in rows if r.owed > 0]
    return sorted(owing, key=lambda r: r.oldest_unpaid or now())


class CustomerIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    phone: Annotated[str, Field(max_length=20)] | None = None
    credit_limit: Annotated[int, Field(ge=0, le=10_000_000)]


class CustomerPatch(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    phone: Annotated[str, Field(max_length=20)] | None = None
    credit_limit: Annotated[int, Field(ge=0, le=10_000_000)] | None = None
    active: bool | None = None


@router.post("/credit/customers", status_code=status.HTTP_201_CREATED)
def create_customer(body: CustomerIn, actor: Owner, db: Db) -> CustomerOut:
    c = CreditCustomer(business_id=actor.business_id, created_by=actor.staff.id, **body.model_dump())
    db.add(c)
    db.flush()
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="credit.customer_created",
                 entity_type="credit_customer", entity_id=c.id, details=body.model_dump())
    db.commit()
    return _out(db, c)


@router.patch("/credit/customers/{customer_id}")
def update_customer(customer_id: uuid.UUID, body: CustomerPatch, actor: Owner, db: Db) -> CustomerOut:
    c = _customer(db, actor, customer_id)
    changes = {}
    for field, new in body.model_dump(exclude_unset=True).items():
        if new is not None and getattr(c, field) != new:
            changes[field] = [str(getattr(c, field)), str(new)]
            setattr(c, field, new)
    if changes:
        audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="credit.customer_updated",
                     entity_type="credit_customer", entity_id=c.id, details=changes)
        db.commit()
    return _out(db, c)


class CreditIn(BaseModel):
    customer_id: uuid.UUID
    approval_id: uuid.UUID | None = None


@router.post("/bills/{bill_id}/credit")
def put_on_credit(bill_id: uuid.UUID, body: CreditIn, actor: CurrentActor, request: Request, db: Db) -> BillOut:
    """Approved credit: what is left to pay moves to a named customer's account and out
    of the waiter's cash-up. Waiters ask; an Owner or Supervisor approves with their PIN.
    A supervisor may approve only within the customer's limit; the owner may go over."""
    bill = load_bill(db, actor, bill_id, Action.approve_credit)
    customer = _customer(db, actor, body.customer_id)
    if not customer.active:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{customer.name} can no longer take credit.")
    balance = amounts(db, bill).balance
    if balance <= 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing left to pay on this bill.")
    approval = auth.authorize(db, actor, Action.approve_credit, body.approval_id)
    decider = db.get(Staff, approval.approved_by) if approval else actor.staff
    already = owed(db, customer.id)
    over_limit = already + balance > customer.credit_limit
    if over_limit and decider.role is not Role.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"Over {customer.name}'s limit: owes {already:,} of {customer.credit_limit:,}. "
                            "Only the owner can approve this.")
    tz = request.app.state.tz
    bill.credit_customer_id, bill.credit_amount = customer.id, balance
    finish_bill(db, bill, BillStatus.credit, tz)
    audit.record(
        db, business_id=actor.business_id, actor_id=actor.staff.id, action="bill.credit",
        entity_type="bill", entity_id=bill.id, approval=approval,
        details={"bill": bill.number, "customer": customer.name, "amount": balance,
                 "approved_by": decider.name, "over_limit": over_limit},
    )
    receipt = make_receipt(db, actor, bill, Printing(tz), get_settings(db, actor.business_id).receipt_footer)
    db.commit()
    request.app.state.printing.print_tickets([receipt])
    return bill_detail(db, bill)


@router.post("/bills/{bill_id}/unpaid")
def mark_unpaid(bill_id: uuid.UUID, actor: CurrentActor, request: Request, db: Db) -> BillOut:
    """Walk-out or credit nobody approved: the waiter marks the bill "Unpaid - I am
    responsible", and what is left to pay stays in the cash they owe at hand-over."""
    bill = load_bill(db, actor, bill_id, Action.mark_unpaid_responsible)
    balance = amounts(db, bill).balance
    if balance <= 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing left to pay on this bill.")
    finish_bill(db, bill, BillStatus.unpaid_responsible, request.app.state.tz)
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="bill.unpaid_responsible",
                 entity_type="bill", entity_id=bill.id, details={"bill": bill.number, "amount": balance})
    db.commit()
    return bill_detail(db, bill)


class CollectionIn(BaseModel):
    amount: Annotated[int, Field(ge=1, le=10_000_000)]
    method: Method
    mpesa_code: Annotated[str, Field(max_length=12)] | None = None


@router.post("/credit/customers/{customer_id}/collections", status_code=status.HTTP_201_CREATED)
def collect(customer_id: uuid.UUID, body: CollectionIn, actor: Collector, request: Request, db: Db) -> CustomerOut:
    """A credit customer paying what they owe. Cash goes into the counter cash box."""
    customer = _customer(db, actor, customer_id)
    if body.amount > owed(db, customer.id):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{customer.name} owes only {owed(db, customer.id):,}.")
    ref = None
    if body.method is Method.mpesa:
        ref = mpesa_ref(get_settings(db, actor.business_id).mpesa_code_entry, body.mpesa_code)
    day = today(db, actor.business_id, request.app.state.tz)
    collection = CreditCollection(business_id=actor.business_id, created_by=actor.staff.id, customer_id=customer.id,
                                  amount=body.amount, method=body.method, mpesa_ref=ref, business_day=day)
    db.add(collection)
    db.flush()
    if body.method is Method.cash:
        db.add(CashMovement(business_id=actor.business_id, created_by=actor.staff.id,
                            kind=CashMovementKind.credit_collected, amount=body.amount, business_day=day,
                            reference_id=collection.id, note=customer.name))
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="credit.collected",
                 entity_type="credit_customer", entity_id=customer.id,
                 details={"customer": customer.name, "amount": body.amount, "method": body.method.value, "ref": ref})
    db.commit()
    if body.method is Method.cash:
        request.app.state.printing.open_drawer()
    return _out(db, customer)
