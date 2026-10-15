import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.audit.models import AuditEntry
from app.auth.models import Approval


def record(
    db: Session,
    *,
    business_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    approval: Approval | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEntry:
    """Add an audit entry to the current transaction. The caller commits it together
    with the change it describes, so neither can exist without the other."""
    entry = AuditEntry(
        business_id=business_id,
        created_by=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        approval_id=approval.id if approval else None,
        details=details or {},
    )
    db.add(entry)
    return entry
