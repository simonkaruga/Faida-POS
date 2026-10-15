import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.credit.models import CreditCollection
from app.floor.models import Bill, BillStatus


def owed(db: Session, customer_id: uuid.UUID) -> int:
    credited = db.scalar(select(func.coalesce(func.sum(Bill.credit_amount), 0))
                         .where(Bill.credit_customer_id == customer_id, Bill.status == BillStatus.credit))
    collected = db.scalar(select(func.coalesce(func.sum(CreditCollection.amount), 0))
                          .where(CreditCollection.customer_id == customer_id))
    return credited - collected


def oldest_unpaid(db: Session, customer_id: uuid.UUID) -> datetime | None:
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
