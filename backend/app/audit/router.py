import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.audit.models import AuditEntry
from app.auth.deps import Actor, Db, require
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
    details: dict[str, Any]


@router.get("")
def list_audit(
    actor: Annotated[Actor, Depends(require(Action.view_audit))],
    db: Db,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditOut]:
    rows = db.execute(
        select(AuditEntry, Staff.name)
        .outerjoin(Staff, Staff.id == AuditEntry.created_by)
        .where(AuditEntry.business_id == actor.business_id)
        .order_by(AuditEntry.created_at.desc())
        .limit(limit)
    )
    return [
        AuditOut(
            id=e.id, created_at=e.created_at, action=e.action, by=name,
            entity_type=e.entity_type, entity_id=e.entity_id,
            approval_id=e.approval_id, details=e.details,
        )
        for e, name in rows
    ]
