import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select

from app.audit import service as audit
from app.auth import service as auth
from app.auth.deps import Actor, CurrentActor, Db, require
from app.auth.permissions import Action, Level, level
from app.menu.models import Category, MenuItem, SellOption, Station
from app.settings.service import get_settings, today
from app.staff.models import Staff
from app.stock import service as stock
from app.stock.service import factor
from app.stock.models import (
    Delivery, DeliveryLine, MovementKind, RecipeLine, StockItem, StockMovement, StockTake, StockTakeLine,
    StockUnit, Supplier, TakeKind,
)
from app.shifts.models import Shift
from app.shifts.service import current_shift, open_shift

router = APIRouter(tags=["stock"])

Owner = Annotated[Actor, Depends(require(Action.manage_business))]
Stockist = Annotated[Actor, Depends(require(Action.receive_stock))]
Qty = Annotated[Decimal, Field(ge=0, le=10_000_000, max_digits=14, decimal_places=3)]
Price = Annotated[int, Field(ge=0, le=1_000_000)]  # whole shillings, as on the menu

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


class SellingOut(BaseModel):
    """A menu option that takes this item from stock, and what it sells for."""
    option_id: uuid.UUID
    name: str  # the menu item, with the option's label: "Jameson · Single tot"
    price: int


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
    selling: list[SellingOut] = []
    # Owner only:
    buying_price: Decimal | None  # per counting unit
    value: int | None


def _selling(db: Db, business_id: uuid.UUID, stock_item_id: uuid.UUID | None = None) -> dict[uuid.UUID, list[SellingOut]]:
    """Selling prices by stock item: the active menu options whose recipe uses it."""
    q = (select(RecipeLine.stock_item_id, SellOption, MenuItem.name)
         .join(SellOption, SellOption.id == RecipeLine.sell_option_id)
         .join(MenuItem, MenuItem.id == SellOption.menu_item_id)
         .where(RecipeLine.business_id == business_id, SellOption.active, MenuItem.active)
         .order_by(MenuItem.name, SellOption.sort_order))
    if stock_item_id:
        q = q.where(RecipeLine.stock_item_id == stock_item_id)
    out: dict[uuid.UUID, list[SellingOut]] = {}
    for sid, option, name in db.execute(q):
        out.setdefault(sid, []).append(SellingOut(option_id=option.id, price=option.price,
                                                  name=f"{name} · {option.label}" if option.label else name))
    return out


def _out(actor: Actor, item: StockItem, qty: Decimal, tot_size: int | None, selling: list[SellingOut] = ()) -> ItemOut:
    money = sees_money(actor)
    return ItemOut(
        id=item.id, name=item.name, station=item.station, unit=item.unit, counting_unit=counting_unit(item),
        bottle_size=item.bottle_size, pack_name=item.pack_name, pack_size=item.pack_size, level=qty,
        level_text=stock.describe(item, qty, tot_size), reorder_level=item.reorder_level,
        low=item.reorder_level > 0 and qty <= item.reorder_level, check=qty < 0, active=item.active, selling=list(selling),
        buying_price=stock.buying_price(item) if money else None,
        value=stock.value(max(qty, Decimal(0)), item.unit_cost) if money else None,
    )


@router.get("/stock")
def list_stock(actor: Stockist, db: Db) -> list[ItemOut]:
    lv = stock.levels(db, actor.business_id)
    tot = get_settings(db, actor.business_id).tot_size_ml
    items = db.scalars(select(StockItem).where(StockItem.business_id == actor.business_id)
                       .order_by(StockItem.station, StockItem.name))
    selling = _selling(db, actor.business_id)
    return [_out(actor, i, lv.get(i.id, Decimal(0)), tot, selling.get(i.id, [])) for i in items]


class SellIn(BaseModel):
    """Put a new stock item on the menu: a menu item of the same name whose sales take it
    from stock. Price per counting unit (a bottle, a piece, a kg), and per tot for a spirit."""
    category_id: uuid.UUID
    price: Price | None = None
    tot_price: Price | None = None

    @model_validator(mode="after")
    def priced(self):
        if self.price is None and self.tot_price is None:
            raise ValueError("Give a selling price.")
        return self


class ItemIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    station: Station
    unit: StockUnit
    bottle_size: Annotated[int, Field(ge=50, le=5000)] | None = None
    pack_name: Annotated[str, Field(max_length=20)] | None = None
    pack_size: Annotated[int, Field(ge=1, le=1000)] | None = None
    buying_price: Qty | None = None  # per counting unit
    reorder_level: Qty = Decimal(0)  # in counting units
    sell: SellIn | None = None  # also put it on the menu

    @model_validator(mode="after")
    def bottle(self):
        if self.bottle_size and self.unit is not StockUnit.ml:
            raise ValueError("Only items kept in ml have a bottle size.")
        if self.sell and self.sell.tot_price is not None and not self.bottle_size:
            raise ValueError("Only a spirit (ml, with a bottle size) sells by the tot.")
        return self


class ItemPatch(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    bottle_size: Annotated[int, Field(ge=50, le=5000)] | None = None  # ml in one bottle (spirits)
    pack_name: Annotated[str, Field(max_length=20)] | None = None
    pack_size: Annotated[int, Field(ge=1, le=1000)] | None = None
    buying_price: Qty | None = None
    reorder_level: Qty | None = None
    active: bool | None = None


@router.post("/stock/items", status_code=status.HTTP_201_CREATED)
def create_item(body: ItemIn, actor: Owner, db: Db) -> ItemOut:
    tot = get_settings(db, actor.business_id).tot_size_ml
    if body.sell:
        category = db.get(Category, body.sell.category_id)
        if category is None or category.business_id != actor.business_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu category not found.")
        if body.sell.tot_price is not None and not tot:
            raise HTTPException(status.HTTP_409_CONFLICT, "Set the tot size in settings before selling by the tot.")
    item = StockItem(business_id=actor.business_id, created_by=actor.staff.id,
                     **body.model_dump(exclude={"buying_price", "reorder_level", "sell"}))
    f = factor(item)
    item.unit_cost = (body.buying_price or Decimal(0)) / f
    item.reorder_level = body.reorder_level * f
    db.add(item)
    db.flush()
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="stock.item_created",
                 entity_type="stock_item", entity_id=item.id, details=body.model_dump(mode="json"))
    if body.sell:
        menu_item = MenuItem(business_id=actor.business_id, created_by=actor.staff.id,
                             category_id=body.sell.category_id, name=body.name, station=body.station)
        db.add(menu_item)
        db.flush()
        # (label, price, quantity, in tots): a tot of the spirit, and one counting unit.
        sold = [("Single tot", body.sell.tot_price, Decimal(1), True)] if body.sell.tot_price is not None else []
        if body.sell.price is not None:
            sold.append(("Bottle" if sold else "", body.sell.price, Decimal(f), False))
        for order, (label, price, quantity, in_tots) in enumerate(sold):
            option = SellOption(business_id=actor.business_id, created_by=actor.staff.id, menu_item_id=menu_item.id,
                                label=label, price=price, sort_order=order)
            db.add(option)
            db.flush()
            db.add(RecipeLine(business_id=actor.business_id, created_by=actor.staff.id, sell_option_id=option.id,
                              stock_item_id=item.id, quantity=quantity, in_tots=in_tots))
        audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="menu.item_created",
                     entity_type="menu_item", entity_id=menu_item.id,
                     details={"name": menu_item.name, "options": [{"label": l, "price": p} for l, p, _, _ in sold]})
    db.commit()
    return _out(actor, item, Decimal(0), tot, _selling(db, actor.business_id, item.id).get(item.id, []))


@router.patch("/stock/items/{item_id}")
def update_item(item_id: uuid.UUID, body: ItemPatch, actor: Owner, db: Db) -> ItemOut:
    item = _item(db, actor, item_id)
    changes = {}
    if body.bottle_size and body.bottle_size != item.bottle_size:
        if item.unit is not StockUnit.ml:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Only items kept in ml have a bottle size.")
        # Same buying price and reorder level per bottle; stock stays in ml (count it again).
        old = factor(item)
        price, reorder = item.unit_cost * old, item.reorder_level / old
        changes["bottle_size"] = [str(item.bottle_size), str(body.bottle_size)]
        item.bottle_size = body.bottle_size
        item.unit_cost, item.reorder_level = price / body.bottle_size, reorder * body.bottle_size
    f = factor(item)
    for field, new in body.model_dump(exclude_unset=True, exclude={"bottle_size"}).items():
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
    return _out(actor, item, stock.level(db, item), get_settings(db, actor.business_id).tot_size_ml,
                _selling(db, actor.business_id, item.id).get(item.id, []))


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
    for old in db.scalars(select(RecipeLine).where(RecipeLine.sell_option_id == option.id)):
        db.delete(old)
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
    open_ml: Qty | None = None  # or what is left in it in ml, measured (then tenths are ignored)


class StockTakeIn(BaseModel):
    note: Annotated[str, Field(max_length=200)] | None = None
    kind: TakeKind = TakeKind.count
    staff_id: uuid.UUID | None = None  # whose shift an opening or closing count is for
    counts: list[CountIn] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def whose(self):
        if self.kind is not TakeKind.count and not self.staff_id:
            raise ValueError("Say whose shift this count is for.")
        return self


class VarianceOut(BaseModel):
    stock_item_id: uuid.UUID
    name: str
    expected_text: str
    counted_text: str
    variance: Decimal
    message: str  # "Missing 0.6 bottles ≈ 18 tots ≈ KSh 2,700"
    value: int | None  # owner only; negative = missing
    # The stock sheet since the last count of this item (None: never counted before)
    since: datetime | None
    opening_text: str | None
    received_text: str
    sold_text: str
    waste_text: str


class StockTakeOut(BaseModel):
    id: uuid.UUID
    kind: TakeKind
    staff: str | None  # whose shift
    by: str | None
    at: datetime
    lines: list[VarianceOut]
    total_value: int | None


def _since_last_count(db: Db, item: StockItem, before: datetime | None = None) -> dict:
    """Opening stock (the last count), and what came in, was sold and wasted since: the
    daily stock sheet. Opening + received - sold - waste = what Faida expects now.
    `before`: as it was for a count made then (to show a saved count again)."""
    q = select(StockTakeLine.counted, StockTakeLine.created_at).where(StockTakeLine.stock_item_id == item.id)
    if before:
        q = q.where(StockTakeLine.created_at < before)
    last = db.execute(q.order_by(StockTakeLine.created_at.desc()).limit(1)).first()
    q = select(StockMovement.kind, func.coalesce(func.sum(StockMovement.quantity), 0)).where(
        StockMovement.stock_item_id == item.id)
    if last:
        q = q.where(StockMovement.created_at > last.created_at)
    if before:
        q = q.where(StockMovement.created_at < before)
    by_kind = {kind: total for kind, total in db.execute(q.group_by(StockMovement.kind))}
    return {
        "since": last.created_at if last else None,
        "opening": last.counted if last else Decimal(0),
        "received": by_kind.get(MovementKind.delivery, Decimal(0)),
        "sold": -(by_kind.get(MovementKind.sale, Decimal(0)) + by_kind.get(MovementKind.sale_return, Decimal(0))),
        "waste": -by_kind.get(MovementKind.waste, Decimal(0)),
    }


def _variance(db: Db, item: StockItem, expected: Decimal, counted: Decimal, unit_cost: Decimal, tot: int | None,
              money: bool, before: datetime | None = None) -> VarianceOut:
    sheet = _since_last_count(db, item, before)
    variance = counted - expected
    worth = stock.value(variance, unit_cost)
    word = "Missing" if variance < 0 else "Extra" if variance > 0 else "Correct"
    message = word if not variance else f"{word} {stock.describe(item, abs(variance), tot)}"
    if variance and money:
        message += f" ≈ KSh {abs(worth):,}"
    return VarianceOut(stock_item_id=item.id, name=item.name, expected_text=stock.describe(item, expected, tot),
                       counted_text=stock.describe(item, counted, tot), variance=variance, message=message,
                       value=worth if money else None, since=sheet["since"],
                       opening_text=stock.describe(item, sheet["opening"], tot) if sheet["since"] else None,
                       received_text=stock.describe(item, sheet["received"], tot),
                       sold_text=stock.describe(item, sheet["sold"], tot),
                       waste_text=stock.describe(item, sheet["waste"], tot))


def _take_out(db: Db, take: StockTake, lines: list[VarianceOut], money: bool) -> StockTakeOut:
    shift = db.get(Shift, take.shift_id) if take.shift_id else None
    by = db.get(Staff, take.created_by) if take.created_by else None
    return StockTakeOut(id=take.id, kind=take.kind, staff=db.get(Staff, shift.staff_id).name if shift else None,
                        by=by.name if by else None, at=take.created_at, lines=lines,
                        total_value=sum(l.value or 0 for l in lines) if money else None)


def _shift_for(db: Db, actor: Actor, body: StockTakeIn, tz) -> Shift | None:
    """An opening count starts the person's shift if it hasn't started; a closing count
    needs it open (it is made before the cash hand-over)."""
    if body.kind is TakeKind.count:
        return None
    staff = db.get(Staff, body.staff_id)
    if staff is None or staff.business_id != actor.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Staff member not found.")
    if body.kind is TakeKind.opening:
        return current_shift(db, actor.business_id, staff.id, tz)
    shift = open_shift(db, actor.business_id, staff.id)
    if shift is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{staff.name} has no shift open to close.")
    return shift


@router.post("/stock/takes", status_code=status.HTTP_201_CREATED)
def stock_take(body: StockTakeIn, actor: Stockist, request: Request, db: Db) -> StockTakeOut:
    """Count some or all items. Faida compares each count with what it expected, shows the
    variance in units (and shillings for the owner), then sets stock to the count. An
    opening or closing count is for someone's shift: the closing count at one hand-over
    is the opening stock of whoever counts next."""
    tz = request.app.state.tz
    day = today(db, actor.business_id, tz)
    tot = get_settings(db, actor.business_id).tot_size_ml
    money = sees_money(actor)
    shift = _shift_for(db, actor, body, tz)
    take = StockTake(business_id=actor.business_id, created_by=actor.staff.id, note=body.note, business_day=day,
                     kind=body.kind, shift_id=shift.id if shift else None)
    db.add(take)
    db.flush()
    out = []
    for c in body.counts:
        item = _item(db, actor, c.stock_item_id)
        if (c.open_tenths or c.open_ml) and not (item.unit is StockUnit.ml and item.bottle_size):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{item.name} isn't counted by the open bottle.")
        if c.open_ml is not None and c.open_ml > (item.bottle_size or 0):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"{item.name}: the open bottle holds at most {item.bottle_size} ml.")
        open_part = c.open_ml if c.open_ml is not None else Decimal(c.open_tenths * (item.bottle_size or 0)) / 10
        counted = c.full * factor(item) + open_part
        expected = stock.level(db, item)
        out.append(_variance(db, item, expected, counted, item.unit_cost, tot, money))
        db.add(StockTakeLine(business_id=actor.business_id, created_by=actor.staff.id, stock_take_id=take.id,
                             stock_item_id=item.id, expected=expected, counted=counted, unit_cost=item.unit_cost))
        if counted != expected:
            stock.move(db, item, MovementKind.stock_take, counted - expected, actor_id=actor.staff.id, day=day,
                       reference_id=take.id, note=body.note)
    result = _take_out(db, take, out, money)
    audit.record(db, business_id=actor.business_id, actor_id=actor.staff.id, action="stock.take",
                 entity_type="stock_take", entity_id=take.id,
                 details={"kind": body.kind.value, "staff": result.staff, "items": len(out), "value": result.total_value,
                          "missing": [o.message for o in out if o.variance < 0]})
    db.commit()
    return result


@router.get("/stock/takes/{take_id}")
def get_stock_take(take_id: uuid.UUID, actor: Stockist, db: Db) -> StockTakeOut:
    """A saved count's stock sheet, as it was when it was counted."""
    take = db.get(StockTake, take_id)
    if take is None or take.business_id != actor.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stock count not found.")
    tot = get_settings(db, actor.business_id).tot_size_ml
    money = sees_money(actor)
    lines = [_variance(db, item, line.expected, line.counted, line.unit_cost, tot, money, before=line.created_at)
             for line, item in db.execute(select(StockTakeLine, StockItem)
                                          .join(StockItem, StockItem.id == StockTakeLine.stock_item_id)
                                          .where(StockTakeLine.stock_take_id == take.id)
                                          .order_by(StockItem.station, StockItem.name))]
    return _take_out(db, take, lines, money)
