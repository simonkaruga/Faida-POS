"""Load the client's menu, tables and stock items from a JSON file at install
(masterplan 7.1 step 5). See docs/sample-menu.json for the format.

A simple item has a "price"; an item sold several ways (a spirit) has "options", each
with a "label" and "price". "uses" says what one sale takes from stock: a "quantity" in
the stock item's unit (bottles, ml, g, pieces), or "tots" of a spirit."""

import re
import shutil
import time as clock
import uuid
from datetime import time
from pathlib import Path
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.floor.models import Table
from app.menu.models import (
    Category, ComboComponent, ItemModifierGroup, MenuItem, ModifierGroup, ModifierOption, PriceRule, SellOption, Station,
)
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


class ComboPartFile(BaseModel):
    item: str
    option: str = ""
    quantity: int = 1


class ItemFile(BaseModel):
    name: str
    station: Station
    favourite: bool = False
    price: Price | None = None
    uses: list[UseFile] = []
    options: list[OptionFile] | None = None
    modifier_groups: list[str] = []
    combo: list[ComboPartFile] = []

    @model_validator(mode="after")
    def price_or_options(self):
        if (self.price is None) == (not self.options):
            raise ValueError(f"{self.name}: give either a price or a list of options")
        return self


class ModifierOptionFile(BaseModel):
    label: str
    price: Price = 0
    stock: str | None = None
    quantity: Decimal | None = None


class ModifierGroupFile(BaseModel):
    name: str
    min: int = 0
    max: int = 1
    options: list[ModifierOptionFile]


class PriceRuleFile(BaseModel):
    name: str = "Happy hour"
    percent_off: int
    days: list[int] = [0, 1, 2, 3, 4, 5, 6]
    start: time
    end: time
    categories: list[str] = []


class TableFile(BaseModel):
    name: str
    section: str = "Main"


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
    tables: list[str | TableFile] = []
    tab_section: str | None = None
    note_presets: list[str] | None = None
    tot_size_ml: int | None = None
    stock: list[StockFile] = []
    modifier_groups: list[ModifierGroupFile] = []
    price_rules: list[PriceRuleFile] = []
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

    for order, t in enumerate(menu.tables):
        t = t if isinstance(t, TableFile) else TableFile(name=t)
        db.add(Table(business_id=business_id, name=t.name, section=t.section, sort_order=order))
        counts["tables"] += 1
    groups: dict[str, ModifierGroup] = {}
    for g in menu.modifier_groups:
        group = ModifierGroup(id=uuid.uuid4(), business_id=business_id, name=g.name, min_select=g.min, max_select=g.max)
        db.add(group)
        groups[g.name] = group
        for order, o in enumerate(g.options):
            if o.stock and o.stock not in stock_items:
                raise SystemExit(f"Unknown stock item {o.stock!r}")
            db.add(ModifierOption(business_id=business_id, group_id=group.id, label=o.label, price=o.price, sort_order=order,
                                  stock_item_id=stock_items[o.stock].id if o.stock else None, stock_quantity=o.quantity))
    db.flush()
    option_ids: dict[tuple[str, str], uuid.UUID] = {}
    combos: list[tuple[uuid.UUID, list[ComboPartFile]]] = []
    links: list[ItemModifierGroup] = []  # added once the items they point to are saved
    category_ids: dict[str, uuid.UUID] = {}
    for c_order, cat in enumerate(menu.categories):
        category = Category(id=uuid.uuid4(), business_id=business_id, name=cat.name, sort_order=c_order)
        db.add(category)
        category_ids[cat.name] = category.id
        counts["categories"] += 1
        for i_order, it in enumerate(cat.items):
            item = MenuItem(id=uuid.uuid4(), business_id=business_id, category_id=category.id, name=it.name,
                            station=it.station, favourite=it.favourite, sort_order=i_order, is_combo=bool(it.combo))
            db.add(item)
            counts["items"] += 1
            for g_order, name in enumerate(it.modifier_groups):
                if name not in groups:
                    raise SystemExit(f"Unknown modifier group {name!r}")
                links.append(ItemModifierGroup(business_id=business_id, menu_item_id=item.id, group_id=groups[name].id,
                                               sort_order=g_order))
            if it.combo:
                combos.append((item.id, it.combo))
            options = it.options or [OptionFile(label="", price=it.price, uses=it.uses)]
            for o_order, opt in enumerate(options):
                option = SellOption(id=uuid.uuid4(), business_id=business_id, menu_item_id=item.id, label=opt.label,
                                    price=opt.price, sort_order=o_order)
                db.add(option)
                option_ids[(it.name, opt.label)] = option.id
                uses(option.id, opt.uses)
    db.flush()
    db.add_all(links)
    for combo_id, parts in combos:
        for part in parts:
            if (part.item, part.option) not in option_ids:
                raise SystemExit(f"Unknown combo part {part.item!r} {part.option!r}")
            db.add(ComboComponent(business_id=business_id, combo_item_id=combo_id,
                                  sell_option_id=option_ids[(part.item, part.option)], quantity=part.quantity))
    for r in menu.price_rules:
        db.add(PriceRule(business_id=business_id, name=r.name, percent_off=r.percent_off, days=r.days,
                         start_time=r.start, end_time=r.end, category_ids=[str(category_ids[c]) for c in r.categories]))
    settings = get_settings(db, business_id)
    if menu.note_presets is not None:
        settings.note_presets = menu.note_presets
    if menu.tot_size_ml:
        settings.tot_size_ml = menu.tot_size_ml
    if menu.tab_section:
        settings.tab_section = menu.tab_section
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


PICTURE_TYPES = (".jpg", ".png", ".webp")


def picture_name(item_name: str) -> str:
    """The file name a picture for this item is looked up by: "Nyama choma 1/2 kg" -> nyama-choma-1-2-kg."""
    return re.sub("[^a-z0-9]+", "-", item_name.lower()).strip("-")


def load_images(db: Session, business_id: uuid.UUID, folder: str, images_dir: Path) -> int:
    """Give menu items without a picture the one in `folder` named after them
    (docs/sample-images). Items that already have a picture keep it."""
    source = Path(folder)
    images_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for item in db.scalars(select(MenuItem).where(MenuItem.business_id == business_id, MenuItem.image.is_(None))):
        found = next((source / f"{picture_name(item.name)}{ext}" for ext in PICTURE_TYPES
                      if (source / f"{picture_name(item.name)}{ext}").is_file()), None)
        if found is None:
            continue
        name = f"{item.id}-{int(clock.time())}{found.suffix}"
        shutil.copyfile(found, images_dir / name)
        item.image = name
        audit.record(db, business_id=business_id, actor_id=None, action="menu.image_set",
                     entity_type="menu_item", entity_id=item.id, details={"image": name, "from": found.name})
        count += 1
    db.commit()
    return count
