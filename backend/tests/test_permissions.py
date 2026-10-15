"""The permission table must match masterplan section 2 exactly."""

import pytest

from app.auth.permissions import MATRIX, Action, Level, can_approve, level, permissions_for
from app.staff.models import Role

O, S, W = Role.owner, Role.supervisor, Role.waiter


def test_every_action_has_a_level_for_every_role():
    for action in Action:
        assert set(MATRIX[action]) == set(Role), action


@pytest.mark.parametrize(
    "action, owner, supervisor, waiter",
    [
        (Action.open_bill, "allow", "allow", "own"),
        (Action.take_payment, "allow", "allow", "own"),
        (Action.view_other_bills, "allow", "allow", "deny"),
        (Action.move_bill_table, "allow", "allow", "own"),
        (Action.hand_over_bill, "allow", "allow", "own"),
        (Action.void_item, "allow", "allow", "approval"),
        (Action.discount, "allow", "allow", "approval"),
        (Action.reprint_receipt, "allow", "allow", "approval"),
        (Action.cancel_paid_bill, "allow", "allow", "approval"),
        (Action.approve_credit, "allow", "allow", "approval"),
        (Action.mark_unpaid_responsible, "deny", "deny", "own"),
        (Action.receive_handover, "allow", "allow", "deny"),
        (Action.force_close_shift, "allow", "deny", "deny"),
        (Action.record_shortage_status, "allow", "deny", "deny"),
        (Action.receive_stock, "allow", "allow", "deny"),
        (Action.record_payout, "allow", "allow", "deny"),
        (Action.record_expense, "allow", "deny", "deny"),
        (Action.view_financials, "allow", "deny", "deny"),
        (Action.manage_business, "allow", "deny", "deny"),
        (Action.run_daily_closing, "allow", "allow", "deny"),
        (Action.phone_view, "allow", "deny", "deny"),
    ],
)
def test_section_2_table(action, owner, supervisor, waiter):
    assert (level(O, action), level(S, action), level(W, action)) == (owner, supervisor, waiter)


def test_only_owner_and_supervisor_approve_and_only_what_waiters_need():
    assert can_approve(O, Action.void_item)
    assert can_approve(S, Action.void_item)
    assert not can_approve(W, Action.void_item)
    # Nobody needs approval to force-close, so it can't be approved: only the owner does it.
    assert not can_approve(O, Action.force_close_shift)


def test_permissions_for_lists_every_action():
    perms = permissions_for(W)
    assert set(perms) == {a.value for a in Action}
    assert perms["void_item"] == Level.approval
