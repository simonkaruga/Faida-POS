"""Imports every model so the metadata is complete (used by migrations and tests)."""

from app.audit.models import AuditEntry
from app.auth.models import Approval
from app.credit.models import CreditCollection, CreditCustomer
from app.db import Base
from app.floor.models import Bill, BillHandover, BillLine, Table
from app.menu.models import Category, MenuItem, SellOption
from app.payments.models import Payment
from app.printing.models import Ticket
from app.sequences import Sequence
from app.settings.models import Business, BusinessSettings
from app.shifts.models import CashMovement, Handover, Shift, ShortageStatus
from app.staff.models import Staff
from app.stock.models import (
    Delivery, DeliveryLine, RecipeLine, StockItem, StockMovement, StockTake, StockTakeLine, Supplier,
)

__all__ = [
    "Base", "AuditEntry", "Approval", "Bill", "BillHandover", "BillLine", "Business",
    "BusinessSettings", "Category", "MenuItem", "Payment", "SellOption", "Sequence",
    "Staff", "Table", "Ticket", "CreditCustomer", "CreditCollection", "Shift", "Handover",
    "ShortageStatus", "CashMovement", "Delivery", "DeliveryLine", "RecipeLine", "StockItem",
    "StockMovement", "StockTake", "StockTakeLine", "Supplier",
]
