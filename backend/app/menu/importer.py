"""Load the client's menu and tables from a JSON file at install (masterplan 7.1 step 5).
See docs/sample-menu.json for the format. A simple item has a "price"; an item sold
several ways (a spirit) has "options", each with a "label" and "price"."""

import uuid
from typing import Annotated

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.floor.models import Table
from app.menu.models import Category, MenuItem, SellOption, Station
from app.settings.service import get_settings

Price = Annotated[int, Field(ge=0)]


class OptionFile(BaseModel):
    label: str
    price: Price


class ItemFile(BaseModel):
    name: str
    station: Station
    favourite: bool = False
    price: Price | None = None
    options: list[OptionFile] | None = None

    @model_validator(mode="after")
    def price_or_options(self):
        if (self.price is None) == (not self.options):
            raise ValueError(f"{self.name}: give either a price or a list of options")
        return self


class CategoryFile(BaseModel):
    name: str
    items: list[ItemFile]


class MenuFile(BaseModel):
    tables: list[str] = []
    note_presets: list[str] | None = None
    categories: list[CategoryFile]


def load_menu(db: Session, business_id: uuid.UUID, data: dict) -> dict[str, int]:
    menu = MenuFile.model_validate(data)
    if db.scalar(select(Category.id).where(Category.business_id == business_id).limit(1)):
        raise SystemExit("This business already has a menu. Change it from the owner screens.")
    counts = {"tables": 0, "categories": 0, "items": 0}
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
            options = it.options or [OptionFile(label="", price=it.price)]
            for o_order, opt in enumerate(options):
                db.add(SellOption(business_id=business_id, menu_item_id=item.id, label=opt.label,
                                  price=opt.price, sort_order=o_order))
    if menu.note_presets is not None:
        get_settings(db, business_id).note_presets = menu.note_presets
    audit.record(db, business_id=business_id, actor_id=None, action="menu.loaded", details=counts)
    db.commit()
    return counts
