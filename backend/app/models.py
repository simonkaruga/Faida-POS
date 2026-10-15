"""Imports every model so the metadata is complete (used by migrations and tests)."""

from app.audit.models import AuditEntry
from app.auth.models import Approval
from app.db import Base
from app.settings.models import Business, BusinessSettings
from app.staff.models import Staff

__all__ = ["Base", "AuditEntry", "Approval", "Business", "BusinessSettings", "Staff"]
