import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, Record


class AuditEntry(Record, Base):
    """Permanent log of who did what. A database trigger refuses any update or delete
    (only the sync status may change), so corrections are always new entries.

    `created_by` is the person who did the action.
    """

    __tablename__ = "audit_entries"
    __table_args__ = (
        # An approval can be used for exactly one action.
        Index(
            "uq_audit_entries_approval_id",
            "approval_id",
            unique=True,
            postgresql_where=text("approval_id IS NOT NULL"),
        ),
    )

    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("approvals.id"))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
