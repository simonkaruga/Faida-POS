import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, select

from app.audit import service as audit
from app.auth import service as auth
from app.auth.deps import Actor, CurrentActor, Db, require
from app.auth.permissions import Action, Level, level
from app.menu.models import MenuItem, SellOption, Station
from app.settings.service import get_settings, today
from app.staff.models import Staff
from app.stock import service as stock
from app.stock.service import factor
from app.stock.models import (
    Delivery, DeliveryLine, MovementKind, RecipeLine, StockItem, StockMovement, StockTake, StockTakeLine,
    StockUnit, Supplier,
)

router = APIRouter(tags=["stock"])

Owner = Annotated[Actor, Depends(require(Action.manage_business))]
Stockist = Annotated[Actor, Depends(require(Action.receive_stock))]
Qty = Annotated[Decimal, Field(ge=0, le=10_000_000, max_digits=14, decimal_places=3)]

PURCHASE_UNIT = {StockUnit.ml: "litre", StockUnit.g: "kg", StockUnit.bottle: "bottle", StockUnit.piece: "piece"}


def counting_unit(item: StockItem) -> str:
    return "bottle" if item.unit is StockUnit.ml and item.bottle_size else PURCHASE_UNIT[item.unit]


def sees_money(actor: Actor) -> bool:
    return level(actor.staff.role, Action.view_financials) is Level.allow


def _item(db: Db, actor: Actor, item_id: uuid.UUID) -> StockItem:
    item = db.get(StockItem, item_id)
    if item is None or item.business_id != actor.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stock item not found.")
    return item


# Stock items


class ItemOut(BaseModel):
    id: uuid.UUID
    name: str
    station: Station
    unit: StockUnit
    counting_unit: str
    bottle_size: int | None
    pack_name: str | None
    pack_size: int | None
    level: Decimal  # in the stock unit
    level_text: str
    reorder_level: Decimal
    low: bool
    check: bool  # below zero: the system is wrong somewhere; count it
    active: bool
    # Owner only:
    buying_price: Decimal | None  # per counting unit
    value: int | None


def _out(actor: Actor, item: StockItem, qty: Decimal, tot_size: int | None) -> ItemOut:
    money = sees_money(actor)
    return ItemOut(
        id=item.id, name=item.name, station=item.station, unit=item.unit, counting_unit=counting_unit(item),
        bottle_size=item.bottle_size, pack_name=item.pack_name, pack_size=item.pack_size, level=qty,
        level_text=stock.describe(item, qty, tot_size), reorder_level=item.reorder_level,
        low=item.reorder_level > 0 and qty <= item.reorder_level, check=qty < 0, active=item.active,
        buying_price=(item.unit_cost * factor(item)).quantize(Decimal("0.01")) if money else None,
        value=stock.value(max(qty, Decimal(0)), item.unit_cost) if money else None,
    )


@router.get("/stock")
def list_stock(actor: Stockist, db: Db) -> list[ItemOut]:
    lv = stock.levels(db, actor.business_id)
    tot = get_settings(db, actor.business_id).tot_size_ml
    items = db.scalars(select(StockItem).where(StockItem.business_id == actor.business_id)
                       .order_by(StockItem.station, StockItem.name))
    return [_out(actor, i, lv.get(i.id, Decimal(0)), tot) for i in items]


class ItemIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    station: Station
    unit: StockUnit
    bottle_size: Annotated[int, Field(ge=50, le=5000)] | None = None
    pack_name: Annotated[str, Field(max_length=20)] | None = None
    pack_size: Annotated[int, Field(ge=1, le=1000)] | None = None
    buying_price: Qty | None = None  # per counting unit
    reorder_level: Qty = Decimal(0)  # in counting units

    @model_validator(mode="after")
    def bottle(self):
        if self.bottle_size and self.unit is not StockUnit.ml:
            raise ValueError("Only items kept in ml have a bottle size.")
        return self


class ItemPatch(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    pack_name: Annotated[str, Field(max_length=20)] | None = None
    pack_size: Annotated[int, Field(ge=1, le=1000)] | None = None
    buying_price: Qty | None = None
    reorder_level: Qty | None = None
    active: bool | None = None


@router.post("/stock/items", status_code=status.HTTP_201_CREATED)
def create_item(body: ItemIn, actor: Owner, db: Db) -> ItemOut:
    item = StockItem(business_id=actor.business_id, created_by=actor.staff.id,
                     **body.model_dump(exclude={"buying_price", "reorder_level"}))
    f = factor(item)
    item.unit_cost = (body.buying_price or Decimal(0)) / f
    item.reorder_level = body.reorder_level * f
    db.add(item)
    db.flush()
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="stock.item_created",
                 entity_type="stock_item", entity_id=item.id, details=body.model_dump(mode="json"))
    db.commit()
    return _out(actor, item, Decimal(0), get_settings(db, actor.business_id).tot_size_ml)


@router.patch("/stock/items/{item_id}")
def update_item(item_id: uuid.UUID, body: ItemPatch, actor: Owner, db: Db) -> ItemOut:
    item = _item(db, actor, item_id)
    f = factor(item)
    changes = {}
    for field, new in body.model_dump(exclude_unset=True).items():
        if new is None:
            continue
        if field == "buying_price":
            field, new = "unit_cost", new / f
        elif field == "reorder_level":
            new = new * f
        if getattr(item, field) != new:
            changes[field] = [str(getattr(item, field)), str(new)]
            setattr(item, field, new)
    if changes:
        audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="stock.item_updated",
                     entity_type="stock_item", entity_id=item.id, details=changes)
        db.commit()
    return _out(actor, item, stock.level(db, item), get_settings(db, actor.business_id).tot_size_ml)


class MovementOut(BaseModel):
    kind: MovementKind
    quantity: Decimal
    text: str
    note: str | None
    by: str | None
    at: datetime


@router.get("/stock/items/{item_id}/movements")
def movements(item_id: uuid.UUID, actor: Stockist, db: Db) -> list[MovementOut]:
    item = _item(db, actor, item_id)
    tot = get_settings(db, actor.business_id).tot_size_ml
    rows = db.execute(
        select(StockMovement, Staff.name).outerjoin(Staff, Staff.id == StockMovement.created_by)
        .where(StockMovement.stock_item_id == item.id).order_by(StockMovement.created_at.desc()).limit(200)
    )
    return [MovementOut(kind=m.kind, quantity=m.quantity, text=stock.describe(item, m.quantity, tot), note=m.note,
                        by=name, at=m.created_at) for m, name in rows]


# Recipes: what each sell option takes out of stock


class RecipeLineIn(BaseModel):
    stock_item_id: uuid.UUID
    quantity: Annotated[Decimal, Field(gt=0, le=100_000, max_digits=14, decimal_places=3)]
    in_tots: bool = False  # quantity is a number of tots (the owner's tot size)


class RecipeLineOut(RecipeLineIn):
    stock_item: str
    text: str


class RecipeOut(BaseModel):
    sell_option_id: uuid.UUID
    item_name: str
    option_label: str
    station: Station
    lines: list[RecipeLineOut]


def _recipe(db: Db, option: SellOption, tot: int | None) -> RecipeOut:
    item = db.get(MenuItem, option.menu_item_id)
    lines = []
    for r in db.scalars(select(RecipeLine).where(RecipeLine.sell_option_id == option.id)):
        s = db.get(StockItem, r.stock_item_id)
        text = f"{r.quantity.normalize():f} tot{'s' if r.quantity != 1 else ''}" if r.in_tots else stock.describe(s, r.quantity, None)
        lines.append(RecipeLineOut(stock_item_id=s.id, quantity=r.quantity, in_tots=r.in_tots, stock_item=s.name, text=text))
    return RecipeOut(sell_option_id=option.id, item_name=item.name, option_label=option.label, station=item.station, lines=lines)


@router.get("/stock/recipes")
def recipes(actor: Owner, db: Db) -> list[RecipeOut]:
    """Every active sell option and what it takes from stock (empty: not tracked)."""
    tot = get_settings(db, actor.business_id).tot_size_ml
    options = db.scalars(
        select(SellOption).join(MenuItem, MenuItem.id == SellOption.menu_item_id)
        .where(SellOption.business_id == actor.business_id, SellOption.active, MenuItem.active)
        .order_by(MenuItem.station, MenuItem.name, SellOption.sort_order)
    )
    return [_recipe(db, o, tot) for o in options]


class RecipeIn(BaseModel):
    lines: list[RecipeLineIn] = Field(max_length=30)


@router.put("/stock/recipes/{option_id}")
def set_recipe(option_id: uuid.UUID, body: RecipeIn, actor: Owner, db: Db) -> RecipeOut:
    """Replace what a sell option takes from stock. Only later sales use the new recipe."""
    option = db.get(SellOption, option_id)
    if option is None or option.business_id != actor.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu option not found.")
    tot = get_settings(db, actor.business_id).tot_size_ml
    for line in body.lines:
        s = _item(db, actor, line.stock_item_id)
        if line.in_tots and not (s.unit is StockUnit.ml and tot):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Tots need the tot size set in settings, and an item kept in ml.")
    db.execute(delete(RecipeLine).where(RecipeLine.sell_option_id == option.id))
    for line in body.lines:
        db.add(RecipeLine(business_id=actor.business_id, created_by=actor.staff.id, sell_option_id=option.id,
                          **line.model_dump()))
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="stock.recipe_set",
                 entity_type="sell_option", entity_id=option.id,
                 details={"lines": [l.model_dump(mode="json") for l in body.lines]})
    db.commit()
    return _recipe(db, option, tot)


# Suppliers and deliveries


class SupplierIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    phone: Annotated[str, Field(max_length=20)] | None = None


class SupplierOut(SupplierIn):
    id: uuid.UUID


@router.get("/stock/suppliers")
def suppliers(actor: Stockist, db: Db) -> list[SupplierOut]:
    rows = db.scalars(select(Supplier).where(Supplier.business_id == actor.business_id).order_by(Supplier.name))
    return [SupplierOut(id=s.id, name=s.name, phone=s.phone) for s in rows]


@router.post("/stock/suppliers", status_code=status.HTTP_201_CREATED)
def add_supplier(body: SupplierIn, actor: Stockist, db: Db) -> SupplierOut:
    s = Supplier(business_id=actor.business_id, created_by=actor.staff.id, **body.model_dump())
    db.add(s)
    db.commit()
    return SupplierOut(id=s.id, name=s.name, phone=s.phone)


class DeliveryLineIn(BaseModel):
    stock_item_id: uuid.UUID
    packs: Annotated[int, Field(ge=0, le=10_000)] = 0  # crates or cartons
    units: Qty = Decimal(0)  # loose bottles, kg, litres or pieces
    cost: Annotated[int, Field(ge=0, le=100_000_000)] | None = None  # paid for this line, from the invoice


class DeliveryIn(BaseModel):
    supplier_id: uuid.UUID | None = None
    note: Annotated[str, Field(max_length=200)] | None = None
    lines: list[DeliveryLineIn] = Field(min_length=1, max_length=100)


class DeliveryOut(BaseModel):
    id: uuid.UUID
    lines: list[str]


@router.post("/stock/deliveries", status_code=status.HTTP_201_CREATED)
def receive_delivery(body: DeliveryIn, actor: Stockist, request: Request, db: Db) -> DeliveryOut:
    """Stock in, by crate or carton and loose units. A cost from the invoice becomes the
    item's buying price (what profit and stock value use from now on)."""
    if body.supplier_id:
        supplier = db.get(Supplier, body.supplier_id)
        if supplier is None or supplier.business_id != actor.business_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Supplier not found.")
    day = today(db, actor.business_id, request.app.state.tz)
    tot = get_settings(db, actor.business_id).tot_size_ml
    delivery = Delivery(business_id=actor.business_id, created_by=actor.staff.id, supplier_id=body.supplier_id,
                        note=body.note, business_day=day)
    db.add(delivery)
    db.flush()
    summary = []
    for line in body.lines:
        item = _item(db, actor, line.stock_item_id)
        if line.packs and not item.pack_size:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{item.name} has no pack size set.")
        quantity = (line.packs * (item.pack_size or 0) + line.units) * factor(item)
        if quantity <= 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Enter how much {item.name} came in.")
        if line.cost is not None:
            item.unit_cost = Decimal(line.cost) / quantity
        db.add(DeliveryLine(business_id=actor.business_id, created_by=actor.staff.id, delivery_id=delivery.id,
                            stock_item_id=item.id, quantity=quantity, cost=line.cost))
        stock.move(db, item, MovementKind.delivery, quantity, actor_id=actor.staff.id, day=day,
                   reference_id=delivery.id, note=body.note)
        summary.append(f"{item.name}: +{stock.describe(item, quantity, tot)}")
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="stock.delivery",
                 entity_type="delivery", entity_id=delivery.id, details={"lines": summary})
    db.commit()
    return DeliveryOut(id=delivery.id, lines=summary)


# Waste


class WasteIn(BaseModel):
    stock_item_id: uuid.UUID
    quantity: Qty = Decimal(0)  # in counting units: bottles, kg, litres, pieces
    tots: Annotated[int, Field(ge=0, le=1000)] = 0
    reason: Annotated[str, Field(min_length=1, max_length=200)]
    approval_id: uuid.UUID | None = None


@router.post("/stock/waste", status_code=status.HTTP_201_CREATED)
def record_waste(body: WasteIn, actor: CurrentActor, request: Request, db: Db) -> ItemOut:
    """Breakage or spillage, with a reason. A waiter needs an Owner or Supervisor PIN."""
    item = _item(db, actor, body.stock_item_id)
    tot = get_settings(db, actor.business_id).tot_size_ml
    if body.tots and not (item.unit is StockUnit.ml and tot):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tots need the tot size set, and an item kept in ml.")
    quantity = body.quantity * factor(item) + body.tots * (tot or 0)
    if quantity <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter how much was wasted.")
    approval = auth.authorize(db, actor, Action.record_waste, body.approval_id)
    day = today(db, actor.business_id, request.app.state.tz)
    m = stock.move(db, item, MovementKind.waste, -quantity, actor_id=actor.staff.id, day=day, note=body.reason)
    db.flush()
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="stock.waste",
                 entity_type="stock_item", entity_id=item.id, approval=approval,
                 details={"item": item.name, "quantity": str(quantity), "text": stock.describe(item, quantity, tot),
                          "value": stock.value(quantity, item.unit_cost), "reason": body.reason, "movement": str(m.id)})
    db.commit()
    return _out(actor, item, stock.level(db, item), tot)


# Stock take


class CountIn(BaseModel):
    stock_item_id: uuid.UUID
    full: Qty  # sealed bottles, kg, litres or pieces
    open_tenths: Annotated[int, Field(ge=0, le=9)] = 0  # the open bottle, in tenths (bottled spirits)


class StockTakeIn(BaseModel):
    note: Annotated[str, Field(max_length=200)] | None = None
    counts: list[CountIn] = Field(min_length=1, max_length=500)


class VarianceOut(BaseModel):
    stock_item_id: uuid.UUID
    name: str
    expected_text: str
    counted_text: str
    variance: Decimal
    message: str  # "Missing 0.6 bottles ≈ 18 tots ≈ KSh 2,700"
    value: int | None  # owner only; negative = missing


class StockTakeOut(BaseModel):
    id: uuid.UUID
    lines: list[VarianceOut]
    total_value: int | None


@router.post("/stock/takes", status_code=status.HTTP_201_CREATED)
def stock_take(body: StockTakeIn, actor: Stockist, request: Request, db: Db) -> StockTakeOut:
    """Count some or all items. Faida compares each count with what it expected, shows the
    variance in units (and shillings for the owner), then sets stock to the count."""
    day = today(db, actor.business_id, request.app.state.tz)
    tot = get_settings(db, actor.business_id).tot_size_ml
    money = sees_money(actor)
    take = StockTake(business_id=actor.business_id, created_by=actor.staff.id, note=body.note, business_day=day)
    db.add(take)
    db.flush()
    out, total = [], 0
    for c in body.counts:
        item = _item(db, actor, c.stock_item_id)
        if c.open_tenths and not (item.unit is StockUnit.ml and item.bottle_size):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{item.name} isn't counted by the open bottle.")
        counted = c.full * factor(item) + Decimal(c.open_tenths * (item.bottle_size or 0)) / 10
        expected = stock.level(db, item)
        variance = counted - expected
        db.add(StockTakeLine(business_id=actor.business_id, created_by=actor.staff.id, stock_take_id=take.id,
                             stock_item_id=item.id, expected=expected, counted=counted, unit_cost=item.unit_cost))
        if variance:
            stock.move(db, item, MovementKind.stock_take, variance, actor_id=actor.staff.id, day=day,
                       reference_id=take.id, note=body.note)
        worth = stock.value(variance, item.unit_cost)
        total += worth
        word = "Missing" if variance < 0 else "Extra" if variance > 0 else "Correct"
        message = word if not variance else f"{word} {stock.describe(item, abs(variance), tot)}"
        if variance and money:
            message += f" ≈ KSh {abs(worth):,}"
        out.append(VarianceOut(stock_item_id=item.id, name=item.name, expected_text=stock.describe(item, expected, tot),
                               counted_text=stock.describe(item, counted, tot), variance=variance, message=message,
                               value=worth if money else None))
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="stock.take",
                 entity_type="stock_take", entity_id=take.id,
                 details={"items": len(out), "value": total, "missing": [o.message for o in out if o.variance < 0]})
    db.commit()
    return StockTakeOut(id=take.id, lines=out, total_value=total if money else None)
