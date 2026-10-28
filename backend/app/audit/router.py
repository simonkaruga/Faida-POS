import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import aliased

from app.audit.models import AuditEntry
from app.auth.deps import Actor, Db, require
from app.auth.models import Approval
from app.auth.permissions import Action
from app.staff.models import Staff

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    action: str
    by: str | None
    entity_type: str | None
    entity_id: uuid.UUID | None
    approval_id: uuid.UUID | None
    approved_by: str | None
    reason: str | None
    details: dict[str, Any]


@router.get("")
def list_audit(
    actor: Annotated[Actor, Depends(require(Action.view_audit))],
    db: Db,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    before: datetime | None = None,
    logins: bool = True,
) -> list[AuditOut]:
    """Newest first. `before` pages back through older entries; `logins=false` hides the
    PIN logins, which otherwise fill the list."""
    approver = aliased(Staff)
    query = (
        select(AuditEntry, Staff.name, approver.name, Approval.reason)
        .outerjoin(Staff, Staff.id == AuditEntry.created_by)
        .outerjoin(Approval, Approval.id == AuditEntry.approval_id)
        .outerjoin(approver, approver.id == Approval.approved_by)
        .where(AuditEntry.business_id == actor.business_id)
    )
    if before is not None:
        query = query.where(AuditEntry.created_at < before)
    if not logins:
        query = query.where(AuditEntry.action != "staff.login")
    rows = db.execute(query.order_by(AuditEntry.created_at.desc()).limit(limit))
    return [
        AuditOut(
            id=e.id, created_at=e.created_at, action=e.action, by=name,
            entity_type=e.entity_type, entity_id=e.entity_id,
            approval_id=e.approval_id, approved_by=approved_by, reason=reason, details=e.details,
        )
        for e, name, approved_by, reason in rows
    ]
