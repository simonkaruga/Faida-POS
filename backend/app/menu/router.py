import base64
import re
import time as time_module
import uuid
from datetime import time
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.audit import service as audit
from app.auth.deps import Actor, CurrentActor, Db, require
from app.auth.permissions import Action
from app.db import now
from app.menu import service as menu_service
from app.menu.models import (
    Category, ComboComponent, ItemModifierGroup, MenuItem, ModifierGroup, ModifierOption, PriceRule, SellOption, Station,
)
from app.settings.service import get_settings
from app.stock.models import StockItem

router = APIRouter(prefix="/menu", tags=["menu"])

Owner = Annotated[Actor, Depends(require(Action.manage_business))]
Name = Annotated[str, Field(min_length=1, max_length=80)]
Price = Annotated[int, Field(ge=0, le=1_000_000)]


class OptionOut(BaseModel):
    id: uuid.UUID
    label: str
    price: int
    offer_price: int | None = None  # happy hour price right now
    offer: str | None = None


class ModifierOptionOut(BaseModel):
    id: uuid.UUID
    label: str
    price: int


class ModifierGroupOut(BaseModel):
    id: uuid.UUID
    name: str
    min_select: int
    max_select: int
    options: list[ModifierOptionOut]


class ItemOut(BaseModel):
    id: uuid.UUID
    name: str
    station: Station
    favourite: bool
    available: bool
    image: str | None
    is_combo: bool
    combo_parts: list[str]
    modifier_groups: list[ModifierGroupOut]
    options: list[OptionOut]


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    items: list[ItemOut]


class HappyHourOut(BaseModel):
    name: str
    percent_off: int
    until: str  # "19:00"


class MenuOut(BaseModel):
    categories: list[CategoryOut]
    note_presets: list[str]
    happy_hours: list[HappyHourOut]


def image_url(name: str | None) -> str | None:
    return f"/api/menu/images/{name}" if name else None


def modifier_groups(db: Db, business_id: uuid.UUID, active_only: bool = True) -> dict[uuid.UUID, ModifierGroupOut]:
    groups = db.scalars(select(ModifierGroup).where(ModifierGroup.business_id == business_id,
                                                    *([ModifierGroup.active] if active_only else []))
                        .order_by(ModifierGroup.name))
    out = {g.id: ModifierGroupOut(id=g.id, name=g.name, min_select=g.min_select, max_select=g.max_select, options=[])
           for g in groups}
    for o in db.scalars(select(ModifierOption).where(ModifierOption.business_id == business_id,
                                                     *([ModifierOption.active] if active_only else []))
                        .order_by(ModifierOption.sort_order, ModifierOption.label)):
        if o.group_id in out:
            out[o.group_id].options.append(ModifierOptionOut(id=o.id, label=o.label, price=o.price))
    return out


def item_extras(db: Db, business_id: uuid.UUID, groups: dict[uuid.UUID, ModifierGroupOut]):
    """Each item's modifier groups and combo parts."""
    groups_of: dict[uuid.UUID, list[ModifierGroupOut]] = {}
    for link in db.scalars(select(ItemModifierGroup).where(ItemModifierGroup.business_id == business_id)
                           .order_by(ItemModifierGroup.sort_order)):
        if link.group_id in groups:
            groups_of.setdefault(link.menu_item_id, []).append(groups[link.group_id])
    parts_of: dict[uuid.UUID, list[str]] = {}
    for comp, o, i in db.execute(
        select(ComboComponent, SellOption, MenuItem).join(SellOption, SellOption.id == ComboComponent.sell_option_id)
        .join(MenuItem, MenuItem.id == SellOption.menu_item_id).where(ComboComponent.business_id == business_id)
    ):
        name = f"{i.name} - {o.label}" if o.label else i.name
        parts_of.setdefault(comp.combo_item_id, []).append(f"{comp.quantity} x {name}" if comp.quantity > 1 else name)
    return groups_of, parts_of


@router.get("")
def get_menu(actor: CurrentActor, request: Request, db: Db) -> MenuOut:
    """The counter menu: active categories, items and sell options, in display order, with
    sold-out items marked and any happy hour running now applied to the prices shown."""
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
    tz = request.app.state.tz
    rules = menu_service.rules_on(db, bid, now(), tz)
    category_of = {i.id: i.category_id for i in items}
    by_item: dict[uuid.UUID, list[OptionOut]] = {}
    for o in options:
        rule = menu_service.best_rule(rules, category_of[o.menu_item_id]) if o.menu_item_id in category_of else None
        by_item.setdefault(o.menu_item_id, []).append(OptionOut(
            id=o.id, label=o.label, price=o.price,
            offer_price=menu_service.offer_price(o.price, rule) if rule else None, offer=rule.name if rule else None))
    groups_of, parts_of = item_extras(db, bid, modifier_groups(db, bid))
    by_category: dict[uuid.UUID, list[ItemOut]] = {}
    for i in items:
        if by_item.get(i.id):
            by_category.setdefault(i.category_id, []).append(ItemOut(
                id=i.id, name=i.name, station=i.station, favourite=i.favourite, available=i.available,
                image=image_url(i.image), is_combo=i.is_combo, combo_parts=parts_of.get(i.id, []),
                modifier_groups=groups_of.get(i.id, []), options=by_item[i.id]))
    return MenuOut(
        categories=[CategoryOut(id=c.id, name=c.name, items=by_category.get(c.id, [])) for c in categories],
        note_presets=get_settings(db, bid).note_presets,
        happy_hours=[HappyHourOut(name=r.name, percent_off=r.percent_off, until=r.end_time.strftime("%H:%M")) for r in rules],
    )


class AvailabilityIn(BaseModel):
    available: bool


@router.post("/items/{item_id}/availability", status_code=status.HTTP_204_NO_CONTENT)
def set_availability(
    item_id: uuid.UUID, body: AvailabilityIn,
    actor: Annotated[Actor, Depends(require(Action.mark_sold_out))], db: Db,
) -> None:
    """Sold out tonight ("86"), or back again. Owners and supervisors."""
    item = _own(db, actor, MenuItem, item_id)
    if item.available != body.available:
        item.available = body.available
        audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id,
                     action="menu.back_in" if body.available else "menu.sold_out",
                     entity_type="menu_item", entity_id=item.id, details={"item": item.name})
        db.commit()


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


class ManageOption(BaseModel):
    id: uuid.UUID
    label: str
    price: int
    sort_order: int
    active: bool


class ManageItem(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID
    name: str
    station: Station
    favourite: bool
    available: bool
    active: bool
    sort_order: int
    image: str | None
    is_combo: bool
    combo: list[dict]
    modifier_group_ids: list[uuid.UUID]
    options: list[ManageOption]


class ManageCategory(BaseModel):
    id: uuid.UUID
    name: str
    sort_order: int
    active: bool


class ManageMenu(BaseModel):
    categories: list[ManageCategory]
    items: list[ManageItem]
    modifier_groups: list[dict]
    price_rules: list[dict]


@router.get("/manage")
def manage_menu(actor: Owner, db: Db) -> ManageMenu:
    """Everything the owner edits, including hidden items and options."""
    bid = actor.business_id
    cats = db.scalars(select(Category).where(Category.business_id == bid).order_by(Category.sort_order, Category.name))
    items = db.scalars(select(MenuItem).where(MenuItem.business_id == bid).order_by(MenuItem.sort_order, MenuItem.name)).all()
    opts: dict[uuid.UUID, list[ManageOption]] = {}
    for o in db.scalars(select(SellOption).where(SellOption.business_id == bid).order_by(SellOption.sort_order, SellOption.price)):
        opts.setdefault(o.menu_item_id, []).append(ManageOption.model_validate(o, from_attributes=True))
    links: dict[uuid.UUID, list[uuid.UUID]] = {}
    for l in db.scalars(select(ItemModifierGroup).where(ItemModifierGroup.business_id == bid).order_by(ItemModifierGroup.sort_order)):
        links.setdefault(l.menu_item_id, []).append(l.group_id)
    combos: dict[uuid.UUID, list[dict]] = {}
    for c in db.scalars(select(ComboComponent).where(ComboComponent.business_id == bid)):
        combos.setdefault(c.combo_item_id, []).append({"sell_option_id": str(c.sell_option_id), "quantity": c.quantity})
    groups = [
        {**g.model_dump(mode="json"), "active": True}
        for g in modifier_groups(db, bid, active_only=False).values()
    ]
    for g in groups:
        g["active"] = db.get(ModifierGroup, uuid.UUID(g["id"])).active
    rules = [
        {"id": str(r.id), "name": r.name, "percent_off": r.percent_off, "days": r.days,
         "start_time": r.start_time.strftime("%H:%M"), "end_time": r.end_time.strftime("%H:%M"),
         "category_ids": r.category_ids, "active": r.active}
        for r in db.scalars(select(PriceRule).where(PriceRule.business_id == bid).order_by(PriceRule.start_time))
    ]
    return ManageMenu(
        categories=[ManageCategory.model_validate(c, from_attributes=True) for c in cats],
        items=[ManageItem(id=i.id, category_id=i.category_id, name=i.name, station=i.station, favourite=i.favourite,
                          available=i.available, active=i.active, sort_order=i.sort_order, image=image_url(i.image),
                          is_combo=i.is_combo, combo=combos.get(i.id, []), modifier_group_ids=links.get(i.id, []),
                          options=opts.get(i.id, [])) for i in items],
        modifier_groups=groups,
        price_rules=rules,
    )


# Modifier groups


class GroupIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=40)]
    min_select: Annotated[int, Field(ge=0, le=10)] = 0
    max_select: Annotated[int, Field(ge=1, le=10)] = 1


class GroupPatch(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=40)] | None = None
    min_select: Annotated[int, Field(ge=0, le=10)] | None = None
    max_select: Annotated[int, Field(ge=1, le=10)] | None = None
    active: bool | None = None


class ModOptionIn(BaseModel):
    label: Annotated[str, Field(min_length=1, max_length=40)]
    price: Price = 0
    stock_item_id: uuid.UUID | None = None
    stock_quantity: Annotated[Decimal, Field(gt=0, le=100_000)] | None = None
    sort_order: int = 0


class ModOptionPatch(BaseModel):
    label: Annotated[str, Field(min_length=1, max_length=40)] | None = None
    price: Price | None = None
    stock_item_id: uuid.UUID | None = None
    stock_quantity: Annotated[Decimal, Field(gt=0, le=100_000)] | None = None
    sort_order: int | None = None
    active: bool | None = None


@router.post("/modifier-groups", status_code=status.HTTP_201_CREATED)
def create_group(body: GroupIn, actor: Owner, db: Db) -> dict:
    if body.min_select > body.max_select:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The minimum can't be more than the maximum.")
    row = ModifierGroup(business_id=actor.business_id, created_by=actor.staff.id, **body.model_dump())
    _record(db, actor, row, "menu.modifier_group_created", "modifier_group", body.model_dump())
    db.commit()
    return {"id": row.id}


@router.patch("/modifier-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def update_group(group_id: uuid.UUID, body: GroupPatch, actor: Owner, db: Db) -> None:
    _patch(db, actor, _own(db, actor, ModifierGroup, group_id), body, "menu.modifier_group_updated", "modifier_group")


@router.post("/modifier-groups/{group_id}/options", status_code=status.HTTP_201_CREATED)
def add_modifier_option(group_id: uuid.UUID, body: ModOptionIn, actor: Owner, db: Db) -> dict:
    _own(db, actor, ModifierGroup, group_id)
    if body.stock_item_id:
        _own(db, actor, StockItem, body.stock_item_id)
    row = ModifierOption(business_id=actor.business_id, created_by=actor.staff.id, group_id=group_id, **body.model_dump())
    _record(db, actor, row, "menu.modifier_option_created", "modifier_option", body.model_dump(mode="json"))
    db.commit()
    return {"id": row.id}


@router.patch("/modifier-options/{option_id}", status_code=status.HTTP_204_NO_CONTENT)
def update_modifier_option(option_id: uuid.UUID, body: ModOptionPatch, actor: Owner, db: Db) -> None:
    if body.stock_item_id:
        _own(db, actor, StockItem, body.stock_item_id)
    _patch(db, actor, _own(db, actor, ModifierOption, option_id), body, "menu.modifier_option_updated", "modifier_option")


class ItemGroupsIn(BaseModel):
    group_ids: list[uuid.UUID] = Field(max_length=10)


@router.put("/items/{item_id}/modifier-groups", status_code=status.HTTP_204_NO_CONTENT)
def set_item_groups(item_id: uuid.UUID, body: ItemGroupsIn, actor: Owner, db: Db) -> None:
    item = _own(db, actor, MenuItem, item_id)
    for gid in body.group_ids:
        _own(db, actor, ModifierGroup, gid)
    for old in db.scalars(select(ItemModifierGroup).where(ItemModifierGroup.menu_item_id == item.id)):
        db.delete(old)
    for order, gid in enumerate(body.group_ids):
        db.add(ItemModifierGroup(business_id=actor.business_id, created_by=actor.staff.id, menu_item_id=item.id,
                                 group_id=gid, sort_order=order))
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="menu.item_modifiers_set",
                 entity_type="menu_item", entity_id=item.id, details={"group_ids": [str(g) for g in body.group_ids]})
    db.commit()


# Combos


class ComboPartIn(BaseModel):
    sell_option_id: uuid.UUID
    quantity: Annotated[int, Field(ge=1, le=20)] = 1


class ComboIn(BaseModel):
    parts: list[ComboPartIn] = Field(max_length=10)


@router.put("/items/{item_id}/combo", status_code=status.HTTP_204_NO_CONTENT)
def set_combo(item_id: uuid.UUID, body: ComboIn, actor: Owner, db: Db) -> None:
    """Make an item a combo of other menu items (or, with no parts, a normal item again)."""
    item = _own(db, actor, MenuItem, item_id)
    for part in body.parts:
        option = _own(db, actor, SellOption, part.sell_option_id)
        if option.menu_item_id == item.id or db.get(MenuItem, option.menu_item_id).is_combo:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A combo's parts must be ordinary items.")
    for old in db.scalars(select(ComboComponent).where(ComboComponent.combo_item_id == item.id)):
        db.delete(old)
    for part in body.parts:
        db.add(ComboComponent(business_id=actor.business_id, created_by=actor.staff.id, combo_item_id=item.id,
                              **part.model_dump()))
    item.is_combo = bool(body.parts)
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="menu.combo_set",
                 entity_type="menu_item", entity_id=item.id, details={"parts": [p.model_dump(mode="json") for p in body.parts]})
    db.commit()


# Happy hour


class RuleIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=40)] = "Happy hour"
    percent_off: Annotated[int, Field(ge=1, le=90)]
    days: list[Annotated[int, Field(ge=0, le=6)]] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6], min_length=1)
    start_time: time
    end_time: time
    category_ids: list[uuid.UUID] = Field(default_factory=list)


class RulePatch(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=40)] | None = None
    percent_off: Annotated[int, Field(ge=1, le=90)] | None = None
    days: list[Annotated[int, Field(ge=0, le=6)]] | None = None
    start_time: time | None = None
    end_time: time | None = None
    category_ids: list[uuid.UUID] | None = None
    active: bool | None = None


def _rule_values(actor: Actor, db: Db, body: BaseModel) -> dict:
    values = body.model_dump(exclude_unset=True, exclude_none=True)
    if "category_ids" in values:
        for cid in values["category_ids"]:
            _own(db, actor, Category, cid)
        values["category_ids"] = [str(c) for c in values["category_ids"]]
    if "days" in values:
        values["days"] = sorted(set(values["days"]))
    if values.get("start_time") is not None and values.get("start_time") == values.get("end_time"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Start and end can't be the same time.")
    return values


@router.post("/price-rules", status_code=status.HTTP_201_CREATED)
def create_rule(body: RuleIn, actor: Owner, db: Db) -> dict:
    row = PriceRule(business_id=actor.business_id, created_by=actor.staff.id, **_rule_values(actor, db, body))
    _record(db, actor, row, "menu.price_rule_created", "price_rule", body.model_dump(mode="json"))
    db.commit()
    return {"id": row.id}


@router.patch("/price-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def update_rule(rule_id: uuid.UUID, body: RulePatch, actor: Owner, db: Db) -> None:
    row = _own(db, actor, PriceRule, rule_id)
    values = _rule_values(actor, db, body)
    changes = {}
    for field, new in values.items():
        if getattr(row, field) != new:
            changes[field] = [str(getattr(row, field)), str(new)]
            setattr(row, field, new)
    if changes:
        audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="menu.price_rule_updated",
                     entity_type="price_rule", entity_id=row.id, details=changes)
        db.commit()


# Pictures on menu tiles


class ImageIn(BaseModel):
    data_url: Annotated[str, Field(max_length=3_000_000)]  # data:image/jpeg;base64,...


IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
IMAGE_NAME = re.compile(r"^[0-9a-f-]{36}-\d+\.(jpg|png|webp)$")


def _images(request: Request) -> Path:
    folder = Path(request.app.state.config.state_dir) / "images"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


@router.post("/items/{item_id}/image")
def set_image(item_id: uuid.UUID, body: ImageIn, actor: Owner, request: Request, db: Db) -> dict:
    """A picture for the item's tile (JPEG, PNG or WebP, up to 2 MB). Kept on the counter."""
    item = _own(db, actor, MenuItem, item_id)
    head, _, data = body.data_url.partition(",")
    kind = head.removeprefix("data:").removesuffix(";base64")
    if kind not in IMAGE_TYPES or not head.endswith(";base64"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Use a JPEG, PNG or WebP picture.")
    try:
        raw = base64.b64decode(data, validate=True)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The picture couldn't be read.") from e
    if len(raw) > 2_000_000:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The picture is too big (2 MB at most).")
    name = f"{item.id}-{int(time_module.time())}.{IMAGE_TYPES[kind]}"
    (_images(request) / name).write_bytes(raw)
    item.image = name
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="menu.image_set",
                 entity_type="menu_item", entity_id=item.id, details={"image": name})
    db.commit()
    return {"image": image_url(name)}


@router.delete("/items/{item_id}/image", status_code=status.HTTP_204_NO_CONTENT)
def remove_image(item_id: uuid.UUID, actor: Owner, db: Db) -> None:
    item = _own(db, actor, MenuItem, item_id)
    if item.image:
        item.image = None
        audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="menu.image_removed",
                     entity_type="menu_item", entity_id=item.id)
        db.commit()


@router.get("/images/{name}", include_in_schema=False)
def get_image(name: str, request: Request) -> FileResponse:
    path = _images(request) / name
    if not IMAGE_NAME.match(name) or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such picture.")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})
