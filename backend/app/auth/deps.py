"""Request dependencies: which business, who is logged in, and permission checks."""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.permissions import Action, Level, level
from app.db import get_db
from app.settings.models import Business
from app.staff.models import Staff

Db = Annotated[Session, Depends(get_db)]


def get_business(db: Db) -> Business:
    """In local mode the counter holds exactly one business."""
    businesses = db.scalars(select(Business).limit(2)).all()
    if len(businesses) != 1:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "This counter is not set up yet.")
    return businesses[0]


@dataclass
class Actor:
    staff: Staff
    token: str

    @property
    def business_id(self) -> uuid.UUID:
        return self.staff.business_id


def current_actor(
    request: Request, db: Db, authorization: Annotated[str | None, Header()] = None
) -> Actor:
    token = (authorization or "").removeprefix("Bearer ").strip()
    session = request.app.state.sessions.touch(token) if token else None
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please enter your PIN.")
    staff = db.get(Staff, session.staff_id)
    if staff is None or not staff.active:
        request.app.state.sessions.end(token)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please enter your PIN.")
    return Actor(staff=staff, token=token)


CurrentActor = Annotated[Actor, Depends(current_actor)]


def require(action: Action):
    """Dependency that rejects roles with no access to `action` at all.

    Roles with `own` or `approval` access get through; the endpoint then checks
    ownership, or calls auth.service.authorize() to check the approval.
    """

    def check(actor: CurrentActor) -> Actor:
        if level(actor.staff.role, action) is Level.deny:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have permission to do this.")
        return actor

    return check
