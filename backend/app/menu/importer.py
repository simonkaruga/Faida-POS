"""Load the client's menu, tables and stock items from a JSON file at install
(masterplan 7.1 step 5). See docs/sample-menu.json for the format.

A simple item has a "price"; an item sold several ways (a spirit) has "options", each
with a "label" and "price". "uses" says what one sale takes from stock: a "quantity" in
the stock item's unit (bottles, ml, g, pieces), or "tots" of a spirit."""

import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.floor.models import Table
from app.menu.models import Category, MenuItem, SellOption, Station
from app.settings.service import get_settings
from app.stock.models import RecipeLine, StockItem, StockUnit
from app.stock.service import factor

Price = Annotated[int, Field(ge=0)]


class UseFile(BaseModel):
    stock: str
    quantity: Decimal | None = None
    tots: Decimal | None = None


class OptionFile(BaseModel):
    label: str
    price: Price
    uses: list[UseFile] = []


class ItemFile(BaseModel):
    name: str
    station: Station
    favourite: bool = False
    price: Price | None = None
    uses: list[UseFile] = []
    options: list[OptionFile] | None = None

    @model_validator(mode="after")
    def price_or_options(self):
        if (self.price is None) == (not self.options):
            raise ValueError(f"{self.name}: give either a price or a list of options")
        return self


class CategoryFile(BaseModel):
    name: str
    items: list[ItemFile]


class StockFile(BaseModel):
    name: str
    station: Station
    unit: StockUnit
    bottle_size: int | None = None
    pack_name: str | None = None
    pack_size: int | None = None
    buying_price: Decimal = Decimal(0)  # per bottle, kg, litre or piece
    reorder_level: Decimal = Decimal(0)  # in the same counting unit


class MenuFile(BaseModel):
    tables: list[str] = []
    note_presets: list[str] | None = None
    tot_size_ml: int | None = None
    stock: list[StockFile] = []
    categories: list[CategoryFile]


def load_menu(db: Session, business_id: uuid.UUID, data: dict) -> dict[str, int]:
    menu = MenuFile.model_validate(data)
    if db.scalar(select(Category.id).where(Category.business_id == business_id).limit(1)):
        raise SystemExit("This business already has a menu. Change it from the owner screens.")
    counts = {"tables": 0, "categories": 0, "items": 0, "stock_items": 0}
    stock_items: dict[str, StockItem] = {}
    for st in menu.stock:
        item = StockItem(id=uuid.uuid4(), business_id=business_id, **st.model_dump(exclude={"buying_price", "reorder_level"}))
        f = factor(item)
        item.unit_cost, item.reorder_level = st.buying_price / f, st.reorder_level * f
        db.add(item)
        stock_items[st.name] = item
        counts["stock_items"] += 1
    db.flush()  # recipe lines below refer to these rows

    def uses(option_id: uuid.UUID, lines: list[UseFile]) -> None:
        for u in lines:
            if u.stock not in stock_items:
                raise SystemExit(f"Unknown stock item {u.stock!r}")
            db.add(RecipeLine(business_id=business_id, sell_option_id=option_id, stock_item_id=stock_items[u.stock].id,
                              quantity=u.tots if u.tots is not None else u.quantity, in_tots=u.tots is not None))

    for order, name in enumerate(menu.tables):
        db.add(Table(business_id=business_id, name=name, sort_order=order))
        counts["tables"] += 1
    for c_order, cat in enumerate(menu.categories):
        category = Category(id=uuid.uuid4(), business_id=business_id, name=cat.name, sort_order=c_order)
        db.add(category)
        counts["categories"] += 1
        for i_order, it in enumerate(cat.items):
            item = MenuItem(id=uuid.uuid4(), business_id=business_id, category_id=category.id, name=it.name,
                            station=it.station, favourite=it.favourite, sort_order=i_order)
            db.add(item)
            counts["items"] += 1
            options = it.options or [OptionFile(label="", price=it.price, uses=it.uses)]
            for o_order, opt in enumerate(options):
                option = SellOption(id=uuid.uuid4(), business_id=business_id, menu_item_id=item.id, label=opt.label,
                                    price=opt.price, sort_order=o_order)
                db.add(option)
                uses(option.id, opt.uses)
    settings = get_settings(db, business_id)
    if menu.note_presets is not None:
        settings.note_presets = menu.note_presets
    if menu.tot_size_ml:
        settings.tot_size_ml = menu.tot_size_ml
    audit.record(db, business_id=business_id, actor_id=None, action="menu.loaded", details=counts)
    db.commit()
    return counts


def load_stock(db: Session, business_id: uuid.UUID, data: dict) -> dict[str, int]:
    """Add the file's stock items, tot size and recipes to a menu that is already loaded.
    Stock items already present (same name) are kept; options that already have a
    recipe are left alone. Menu items are matched by name and option label."""
    menu = MenuFile.model_validate(data)
    existing = {s.name: s for s in db.scalars(select(StockItem).where(StockItem.business_id == business_id))}
    counts = {"stock_items": 0, "recipes": 0}
    for st in menu.stock:
        if st.name in existing:
            continue
        item = StockItem(id=uuid.uuid4(), business_id=business_id, **st.model_dump(exclude={"buying_price", "reorder_level"}))
        f = factor(item)
        item.unit_cost, item.reorder_level = st.buying_price / f, st.reorder_level * f
        db.add(item)
        existing[st.name] = item
        counts["stock_items"] += 1
    db.flush()
    options = {
        (i.name, o.label): o
        for o, i in db.execute(select(SellOption, MenuItem).join(MenuItem, MenuItem.id == SellOption.menu_item_id)
                               .where(SellOption.business_id == business_id))
    }
    has_recipe = set(db.scalars(select(RecipeLine.sell_option_id).where(RecipeLine.business_id == business_id)))
    for cat in menu.categories:
        for it in cat.items:
            for opt in it.options or [OptionFile(label="", price=it.price, uses=it.uses)]:
                option = options.get((it.name, opt.label))
                if option is None or option.id in has_recipe or not opt.uses:
                    continue
                for u in opt.uses:
                    if u.stock not in existing:
                        raise SystemExit(f"Unknown stock item {u.stock!r}")
                    db.add(RecipeLine(business_id=business_id, sell_option_id=option.id, stock_item_id=existing[u.stock].id,
                                      quantity=u.tots if u.tots is not None else u.quantity, in_tots=u.tots is not None))
                counts["recipes"] += 1
    settings = get_settings(db, business_id)
    if menu.tot_size_ml and not settings.tot_size_ml:
        settings.tot_size_ml = menu.tot_size_ml
    audit.record(db, business_id=business_id, actor_id=None, action="stock.loaded", details=counts)
    db.commit()
    return counts
