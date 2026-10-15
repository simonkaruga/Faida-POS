import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.audit import service as audit
from app.auth import service
from app.auth.deps import CurrentActor, Db, get_business
from app.auth.models import Decision
from app.auth.permissions import Action, permissions_for
from app.settings.models import Business, BusinessSettings
from app.staff.models import Role

router = APIRouter(prefix="/auth", tags=["auth"])

BusinessDep = Annotated[Business, Depends(get_business)]


class PinIn(BaseModel):
    pin: str = Field(min_length=1, max_length=12)


class StaffOut(BaseModel):
    id: uuid.UUID
    name: str
    role: Role


class Me(BaseModel):
    staff: StaffOut
    permissions: dict[str, str]
    auto_lock_seconds: int


class LoginOut(Me):
    token: str


def _me(db: Db, staff) -> Me:
    settings = db.scalar(
        select(BusinessSettings).where(BusinessSettings.business_id == staff.business_id)
    )
    return Me(
        staff=StaffOut(id=staff.id, name=staff.name, role=staff.role),
        permissions=permissions_for(staff.role),
        auto_lock_seconds=settings.auto_lock_seconds,
    )


@router.post("/login")
def login(body: PinIn, request: Request, db: Db, business: BusinessDep) -> LoginOut:
    state = request.app.state
    staff = service.find_staff_by_pin(
        db, state.keypad, state.config.pin_secret, business.id, body.pin
    )
    audit.record(db, business_id=business.id, actor_id=staff.id, action="staff.login")
    db.commit()
    token = state.sessions.start(staff.id, business.id)
    return LoginOut(token=token, **_me(db, staff).model_dump())


@router.get("/me")
def me(actor: CurrentActor, db: Db) -> Me:
    return _me(db, actor.staff)


@router.post("/lock", status_code=status.HTTP_204_NO_CONTENT)
def lock(actor: CurrentActor, request: Request) -> None:
    """End this session: after each send, each payment, or when the screen goes idle."""
    request.app.state.sessions.end(actor.token)


class ApprovalIn(BaseModel):
    action: Action
    approver_pin: str = Field(min_length=1, max_length=12)
    decision: Decision = Decision.approved
    reason: str = Field(min_length=1, max_length=200)
    details: dict[str, Any] = Field(default_factory=dict)


class ApprovalOut(BaseModel):
    id: uuid.UUID
    action: Action
    decision: Decision
    approved_by: StaffOut


@router.post("/approvals", status_code=status.HTTP_201_CREATED)
def create_approval(body: ApprovalIn, actor: CurrentActor, request: Request, db: Db) -> ApprovalOut:
    """The approval pop-up: an Owner or Supervisor types their PIN on the waiter's screen.

    The waiter's session stays as it is; the returned approval id is then sent with
    the action it approves.
    """
    state = request.app.state
    approver = service.find_staff_by_pin(
        db, state.keypad, state.config.pin_secret, actor.business_id, body.approver_pin
    )
    approval = service.decide_approval(
        db, actor, approver, body.action, body.decision, body.reason, body.details
    )
    db.commit()
    return ApprovalOut(
        id=approval.id,
        action=body.action,
        decision=approval.decision,
        approved_by=StaffOut(id=approver.id, name=approver.name, role=approver.role),
    )
