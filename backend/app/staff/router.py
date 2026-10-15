import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.audit import service as audit
from app.auth.deps import Actor, Db, require
from app.auth.permissions import Action
from app.auth.pins import WeakPin, check_new_pin, pin_lookup
from app.db import now
from app.staff.models import Role, Staff

router = APIRouter(prefix="/staff", tags=["staff"])

Owner = Annotated[Actor, Depends(require(Action.manage_business))]


class StaffOut(BaseModel):
    id: uuid.UUID
    name: str
    role: Role
    active: bool
    created_at: datetime
    deactivated_at: datetime | None


class StaffIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    role: Role
    pin: str


class StaffPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    role: Role | None = None


class PinIn(BaseModel):
    pin: str


def _out(s: Staff) -> StaffOut:
    return StaffOut.model_validate(s, from_attributes=True)


def _get(db: Db, actor: Actor, staff_id: uuid.UUID) -> Staff:
    staff = db.get(Staff, staff_id)
    if staff is None or staff.business_id != actor.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Staff member not found.")
    return staff


def _checked_lookup(request: Request, db: Db, actor: Actor, pin: str, exclude: uuid.UUID | None = None) -> str:
    try:
        check_new_pin(pin)
    except WeakPin as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    lookup = pin_lookup(request.app.state.config.pin_secret, actor.business_id, pin)
    query = select(Staff.id).where(
        Staff.business_id == actor.business_id, Staff.pin_lookup == lookup, Staff.active
    )
    if exclude:
        query = query.where(Staff.id != exclude)
    if db.scalar(query):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That PIN is already in use. Choose a different one."
        )
    return lookup


def _keep_an_owner(db: Db, staff: Staff) -> None:
    """The business must always have at least one active owner."""
    owners = db.scalar(
        select(func.count()).where(
            Staff.business_id == staff.business_id, Staff.role == Role.owner, Staff.active
        )
    )
    if staff.role is Role.owner and staff.active and owners <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "The business must keep at least one owner.")


class Colleague(BaseModel):
    id: uuid.UUID
    name: str
    role: Role


@router.get("/active")
def active_staff(actor: Annotated[Actor, Depends(require(Action.receive_handover))], db: Db) -> list[Colleague]:
    """Names of active staff, for an Owner or Supervisor giving a float."""
    rows = db.scalars(select(Staff).where(Staff.business_id == actor.business_id, Staff.active).order_by(Staff.name))
    return [Colleague(id=s.id, name=s.name, role=s.role) for s in rows]


@router.get("")
def list_staff(actor: Owner, db: Db) -> list[StaffOut]:
    rows = db.scalars(
        select(Staff)
        .where(Staff.business_id == actor.business_id)
        .order_by(Staff.active.desc(), Staff.name)
    )
    return [_out(s) for s in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_staff(body: StaffIn, actor: Owner, request: Request, db: Db) -> StaffOut:
    staff = Staff(
        business_id=actor.business_id,
        created_by=actor.staff.id,
        name=body.name.strip(),
        role=body.role,
        pin_lookup=_checked_lookup(request, db, actor, body.pin),
    )
    db.add(staff)
    db.flush()
    audit.record(
        db, business_id=actor.business_id, actor_id=actor.staff.id, action="staff.created",
        entity_type="staff", entity_id=staff.id, details={"name": staff.name, "role": staff.role.value},
    )
    db.commit()
    return _out(staff)


@router.patch("/{staff_id}")
def update_staff(staff_id: uuid.UUID, body: StaffPatch, actor: Owner, db: Db) -> StaffOut:
    staff = _get(db, actor, staff_id)
    changes = {}
    if body.role is not None and body.role is not staff.role:
        _keep_an_owner(db, staff)
        changes["role"] = [staff.role.value, body.role.value]
        staff.role = body.role
    if body.name is not None and body.name.strip() != staff.name:
        changes["name"] = [staff.name, body.name.strip()]
        staff.name = body.name.strip()
    if changes:
        audit.record(
            db, business_id=actor.business_id, actor_id=actor.staff.id, action="staff.updated",
            entity_type="staff", entity_id=staff.id, details=changes,
        )
        db.commit()
    return _out(staff)


@router.post("/{staff_id}/pin", status_code=status.HTTP_204_NO_CONTENT)
def reset_pin(staff_id: uuid.UUID, body: PinIn, actor: Owner, request: Request, db: Db) -> None:
    staff = _get(db, actor, staff_id)
    if not staff.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "This staff member has left.")
    staff.pin_lookup = _checked_lookup(request, db, actor, body.pin, exclude=staff.id)
    audit.record(
        db, business_id=actor.business_id, actor_id=actor.staff.id, action="staff.pin_reset",
        entity_type="staff", entity_id=staff.id,
    )
    db.commit()


@router.post("/{staff_id}/deactivate")
def deactivate(staff_id: uuid.UUID, actor: Owner, db: Db) -> StaffOut:
    """A staff member who leaves is deactivated, never deleted. Their PIN stops working
    at once, including any screen they are still logged in on."""
    staff = _get(db, actor, staff_id)
    if staff.active:
        _keep_an_owner(db, staff)
        staff.active = False
        staff.deactivated_at = now()
        audit.record(
            db, business_id=actor.business_id, actor_id=actor.staff.id, action="staff.deactivated",
            entity_type="staff", entity_id=staff.id,
        )
        db.commit()
    return _out(staff)
