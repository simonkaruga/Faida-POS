import uuid
from datetime import timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.audit.models import AuditEntry
from app.auth.deps import Actor
from app.auth.models import Approval, Decision
from app.auth.permissions import Action, Level, can_approve, level
from app.auth.pins import pin_lookup
from app.auth.sessions import KeypadGuard
from app.db import now
from app.staff.models import Staff

# An approval must be used straight away, for the action it was given for.
APPROVAL_VALID_FOR = timedelta(minutes=2)


def find_staff_by_pin(
    db: Session, guard: KeypadGuard, secret: str, business_id: uuid.UUID, pin: str
) -> Staff:
    """Identify an active staff member from a typed PIN, applying the keypad lockout."""
    if wait := guard.seconds_locked():
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many wrong PINs. Try again in {wait} seconds.",
        )
    staff = db.scalar(
        select(Staff).where(
            Staff.business_id == business_id,
            Staff.pin_lookup == pin_lookup(secret, business_id, pin),
            Staff.active,
        )
    )
    if staff is None:
        guard.failed()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong PIN.")
    guard.succeeded()
    return staff


def decide_approval(
    db: Session,
    requester: Actor,
    approver: Staff,
    action: Action,
    decision: Decision,
    reason: str,
    details: dict[str, Any],
) -> Approval:
    if level(requester.staff.role, action) is not Level.approval:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This action doesn't need approval.")
    if not can_approve(approver.role, action):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"{approver.name} can't approve this.")
    approval = Approval(
        business_id=requester.business_id,
        created_by=requester.staff.id,
        action=action.value,
        approved_by=approver.id,
        decision=decision,
        reason=reason,
        details=details,
    )
    db.add(approval)
    db.flush()
    audit.record(
        db,
        business_id=requester.business_id,
        actor_id=approver.id,
        action=f"approval.{decision.value}",
        entity_type="approval",
        entity_id=approval.id,
        details={"for_action": action.value, "requested_by": str(requester.staff.id), "reason": reason},
    )
    return approval


def authorize(
    db: Session, actor: Actor, action: Action, approval_id: uuid.UUID | None = None
) -> Approval | None:
    """Check `actor` may do `action` now.

    Returns the approval to pass to audit.record() when one was needed (that audit
    entry is what marks the approval as used), or None when the role is allowed
    outright. Ownership (`own` level) is the caller's to check.
    """
    match level(actor.staff.role, action):
        case Level.deny:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have permission to do this.")
        case Level.allow | Level.own:
            return None

    approval = db.get(Approval, approval_id) if approval_id else None
    if (
        approval is None
        or approval.business_id != actor.business_id
        or approval.action != action.value
        or approval.created_by != actor.staff.id
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This needs an Owner or Supervisor PIN.")
    if approval.decision is not Decision.approved:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This was rejected.")
    if now() - approval.created_at > APPROVAL_VALID_FOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The approval has expired. Ask again.")
    used = db.scalar(select(AuditEntry.id).where(AuditEntry.approval_id == approval.id))
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, "This approval has already been used.")
    return approval
