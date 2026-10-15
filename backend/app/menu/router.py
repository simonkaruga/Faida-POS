import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.audit import service as audit
from app.auth.deps import Actor, CurrentActor, Db, require
from app.auth.permissions import Action
from app.menu.models import Category, MenuItem, SellOption, Station
from app.settings.service import get_settings

router = APIRouter(prefix="/menu", tags=["menu"])

Owner = Annotated[Actor, Depends(require(Action.manage_business))]
Name = Annotated[str, Field(min_length=1, max_length=80)]
Price = Annotated[int, Field(ge=0, le=1_000_000)]


class OptionOut(BaseModel):
    id: uuid.UUID
    label: str
    price: int


class ItemOut(BaseModel):
    id: uuid.UUID
    name: str
    station: Station
    favourite: bool
    options: list[OptionOut]


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    items: list[ItemOut]


class MenuOut(BaseModel):
    categories: list[CategoryOut]
    note_presets: list[str]


@router.get("")
def get_menu(actor: CurrentActor, db: Db) -> MenuOut:
    """The counter menu: active categories, items and sell options, in display order."""
    bid = actor.business_id
    categories = db.scalars(
        select(Category).where(Category.business_id == bid, Category.active)
        .order_by(Category.sort_order, Category.name)
    ).all()
    items = db.scalars(
        select(MenuItem).where(MenuItem.business_id == bid, MenuItem.active)
        .order_by(MenuItem.sort_order, MenuItem.name)
    ).all()
    options = db.scalars(
        select(SellOption).where(SellOption.business_id == bid, SellOption.active)
        .order_by(SellOption.sort_order, SellOption.price)
    ).all()
    by_item: dict[uuid.UUID, list[OptionOut]] = {}
    for o in options:
        by_item.setdefault(o.menu_item_id, []).append(OptionOut(id=o.id, label=o.label, price=o.price))
    by_category: dict[uuid.UUID, list[ItemOut]] = {}
    for i in items:
        if by_item.get(i.id):
            by_category.setdefault(i.category_id, []).append(
                ItemOut(id=i.id, name=i.name, station=i.station, favourite=i.favourite, options=by_item[i.id])
            )
    return MenuOut(
        categories=[CategoryOut(id=c.id, name=c.name, items=by_category.get(c.id, [])) for c in categories],
        note_presets=get_settings(db, bid).note_presets,
    )


# Owner editing. Every change is logged; price changes never affect bills already sent.


class CategoryIn(BaseModel):
    name: Name
    sort_order: int = 0


class CategoryPatch(BaseModel):
    name: Name | None = None
    sort_order: int | None = None
    active: bool | None = None


class OptionIn(BaseModel):
    label: Annotated[str, Field(max_length=40)] = ""
    price: Price
    sort_order: int = 0


class OptionPatch(BaseModel):
    label: Annotated[str, Field(max_length=40)] | None = None
    price: Price | None = None
    sort_order: int | None = None
    active: bool | None = None


class ItemIn(BaseModel):
    category_id: uuid.UUID
    name: Name
    station: Station
    favourite: bool = False
    sort_order: int = 0
    options: list[OptionIn] = Field(min_length=1, max_length=10)


class ItemPatch(BaseModel):
    category_id: uuid.UUID | None = None
    name: Name | None = None
    station: Station | None = None
    favourite: bool | None = None
    sort_order: int | None = None
    active: bool | None = None


def _own(db: Db, actor: Actor, model, id: uuid.UUID):
    row = db.get(model, id)
    if row is None or row.business_id != actor.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    return row


def _patch(db: Db, actor: Actor, row, body: BaseModel, action: str, entity_type: str) -> None:
    changes = {}
    for field, new in body.model_dump(exclude_unset=True).items():
        old = getattr(row, field)
        if new is not None and old != new:
            changes[field] = [str(old), str(new)]
            setattr(row, field, new)
    if changes:
        audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action=action,
                     entity_type=entity_type, entity_id=row.id, details=changes)
        db.commit()


def _record(db: Db, actor: Actor, row, action: str, entity_type: str, details: dict) -> None:
    db.add(row)
    db.flush()
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action=action,
                 entity_type=entity_type, entity_id=row.id, details=details)


@router.post("/categories", status_code=status.HTTP_201_CREATED)
def create_category(body: CategoryIn, actor: Owner, db: Db) -> dict:
    row = Category(business_id=actor.business_id, created_by=actor.staff.id, **body.model_dump())
    _record(db, actor, row, "menu.category_created", "menu_category", {"name": row.name})
    db.commit()
    return {"id": row.id}


@router.patch("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def update_category(category_id: uuid.UUID, body: CategoryPatch, actor: Owner, db: Db) -> None:
    _patch(db, actor, _own(db, actor, Category, category_id), body, "menu.category_updated", "menu_category")


@router.post("/items", status_code=status.HTTP_201_CREATED)
def create_item(body: ItemIn, actor: Owner, db: Db) -> dict:
    _own(db, actor, Category, body.category_id)
    item = MenuItem(
        business_id=actor.business_id, created_by=actor.staff.id,
        **body.model_dump(exclude={"options"}),
    )
    _record(db, actor, item, "menu.item_created", "menu_item",
            {"name": item.name, "options": [o.model_dump() for o in body.options]})
    for o in body.options:
        db.add(SellOption(business_id=actor.business_id, created_by=actor.staff.id,
                          menu_item_id=item.id, **o.model_dump()))
    db.commit()
    return {"id": item.id}


@router.patch("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def update_item(item_id: uuid.UUID, body: ItemPatch, actor: Owner, db: Db) -> None:
    if body.category_id:
        _own(db, actor, Category, body.category_id)
    _patch(db, actor, _own(db, actor, MenuItem, item_id), body, "menu.item_updated", "menu_item")


@router.post("/items/{item_id}/options", status_code=status.HTTP_201_CREATED)
def add_option(item_id: uuid.UUID, body: OptionIn, actor: Owner, db: Db) -> dict:
    _own(db, actor, MenuItem, item_id)
    row = SellOption(business_id=actor.business_id, created_by=actor.staff.id,
                     menu_item_id=item_id, **body.model_dump())
    _record(db, actor, row, "menu.option_created", "sell_option", body.model_dump())
    db.commit()
    return {"id": row.id}


@router.patch("/options/{option_id}", status_code=status.HTTP_204_NO_CONTENT)
def update_option(option_id: uuid.UUID, body: OptionPatch, actor: Owner, db: Db) -> None:
    row = _own(db, actor, SellOption, option_id)
    action = "menu.price_changed" if body.price is not None and body.price != row.price else "menu.option_updated"
    _patch(db, actor, row, body, action, "sell_option")
