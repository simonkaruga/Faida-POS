import enum
import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, Record, str_enum


class Decision(enum.StrEnum):
    approved = "approved"
    rejected = "rejected"


class Approval(Record, Base):
    """An Owner or Supervisor PIN approving (or rejecting) one sensitive action.

    `created_by` is the person who asked; `approved_by` is the person who decided.
    Like the audit log, approvals can never be edited or deleted.
    """

    __tablename__ = "approvals"

    action: Mapped[str] = mapped_column(String(60))
    approved_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("staff.id"))
    decision: Mapped[Decision] = mapped_column(str_enum(Decision, "approval_decision"))
    reason: Mapped[str] = mapped_column(String(200))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
