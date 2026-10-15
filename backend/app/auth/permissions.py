"""Who may do what. This is masterplan section 2, the single source of truth.

The backend checks every request against this table; the frontend only uses it to
decide which buttons to show.
"""

import enum

from app.staff.models import Role


class Action(enum.StrEnum):
    # Floor and ordering
    open_bill = "open_bill"  # open tables or tabs, add items, send slips, print bills
    take_payment = "take_payment"
    view_other_bills = "view_other_bills"
    move_bill_table = "move_bill_table"
    hand_over_bill = "hand_over_bill"
    void_item = "void_item"
    discount = "discount"
    reprint_receipt = "reprint_receipt"
    cancel_paid_bill = "cancel_paid_bill"
    mpesa_duplicate_override = "mpesa_duplicate_override"  # 4.3
    approve_credit = "approve_credit"
    mark_unpaid_responsible = "mark_unpaid_responsible"
    # Shifts and cash
    receive_handover = "receive_handover"  # receive cash, close a waiter's shift
    force_close_shift = "force_close_shift"
    record_shortage_status = "record_shortage_status"
    collect_credit_payment = "collect_credit_payment"  # 4.5
    record_payout = "record_payout"
    record_expense = "record_expense"
    run_daily_closing = "run_daily_closing"
    # Stock
    receive_stock = "receive_stock"  # deliveries and stock takes
    record_waste = "record_waste"  # 4.7
    # Owner only
    view_financials = "view_financials"  # profit, buying prices, stock value, reports
    manage_business = "manage_business"  # menu, prices, recipes, staff, PINs, settings
    view_audit = "view_audit"
    phone_view = "phone_view"


class Level(enum.StrEnum):
    allow = "allow"
    own = "own"  # allowed on the staff member's own bills only
    approval = "approval"  # allowed once an Owner or Supervisor approves with their PIN
    deny = "deny"


O, S, W = Role.owner, Role.supervisor, Role.waiter
A, OWN, APP, X = Level.allow, Level.own, Level.approval, Level.deny

#                                  Owner  Supervisor  Waiter
MATRIX: dict[Action, dict[Role, Level]] = {
    Action.open_bill:                {O: A, S: A,   W: OWN},
    Action.take_payment:             {O: A, S: A,   W: OWN},
    Action.view_other_bills:         {O: A, S: A,   W: X},
    Action.move_bill_table:          {O: A, S: A,   W: OWN},
    # A waiter hand-over also needs the receiving waiter's PIN (checked in floor/).
    Action.hand_over_bill:           {O: A, S: A,   W: OWN},
    Action.void_item:                {O: A, S: A,   W: APP},
    Action.discount:                 {O: A, S: A,   W: APP},
    Action.reprint_receipt:          {O: A, S: A,   W: APP},
    Action.cancel_paid_bill:         {O: A, S: A,   W: APP},
    Action.mpesa_duplicate_override: {O: A, S: A,   W: APP},
    # Supervisors approve only within the customer's limit (checked in credit/).
    Action.approve_credit:           {O: A, S: A,   W: APP},
    Action.mark_unpaid_responsible:  {O: X, S: X,   W: OWN},
    Action.receive_handover:         {O: A, S: A,   W: X},
    Action.force_close_shift:        {O: A, S: X,   W: X},
    Action.record_shortage_status:   {O: A, S: X,   W: X},
    Action.collect_credit_payment:   {O: A, S: A,   W: X},
    Action.record_payout:            {O: A, S: A,   W: X},
    Action.record_expense:           {O: A, S: X,   W: X},
    Action.run_daily_closing:        {O: A, S: A,   W: X},
    Action.receive_stock:            {O: A, S: A,   W: X},
    Action.record_waste:             {O: A, S: A,   W: APP},
    Action.view_financials:          {O: A, S: X,   W: X},
    Action.manage_business:          {O: A, S: X,   W: X},
    Action.view_audit:               {O: A, S: X,   W: X},
    Action.phone_view:               {O: A, S: X,   W: X},
}


def level(role: Role, action: Action) -> Level:
    return MATRIX[action][role]


def can_approve(role: Role, action: Action) -> bool:
    """Only actions a waiter needs approval for can be approved, and only by a role
    that is allowed to do the action outright."""
    return Level.approval in MATRIX[action].values() and level(role, action) is Level.allow


def permissions_for(role: Role) -> dict[str, str]:
    return {action.value: level(role, action).value for action in Action}
