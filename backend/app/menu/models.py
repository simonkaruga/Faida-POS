import enum
import uuid
from datetime import time
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Time
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, Record, str_enum


class Station(enum.StrEnum):
    """Where SEND routes an item: drinks to the bar slip, food to the kitchen ticket."""

    bar = "bar"
    kitchen = "kitchen"


class Category(Record, Base):
    __tablename__ = "menu_categories"

    name: Mapped[str] = mapped_column(String(60))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MenuItem(Record, Base):
    __tablename__ = "menu_items"

    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("menu_categories.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    station: Mapped[Station] = mapped_column(str_enum(Station, "station"))
    favourite: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)  # off: removed from the menu
    # Sold out tonight ("86"): still on the menu, but it can't be ordered until it's back.
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    image: Mapped[str | None] = mapped_column(String(80))  # file name of the tile picture
    # A combo is sold at its own price and sends its components to their stations.
    is_combo: Mapped[bool] = mapped_column(Boolean, default=False)


class SellOption(Record, Base):
    """What is actually sold and priced: "Bottle", or "Single tot" / "Double" / "Bottle"
    for a spirit. An item with one option is added with one tap; more open a choice.
    Phase 4 links each option to the stock it uses."""

    __tablename__ = "sell_options"

    menu_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("menu_items.id"), index=True)
    label: Mapped[str] = mapped_column(String(40))
    price: Mapped[int] = mapped_column(Integer)  # whole shillings
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ComboComponent(Record, Base):
    """One part of a combo, e.g. "Chicken & chips" in "Chicken & chips + Soda". The part
    is sent to its own station and taken from stock by its own recipe."""

    __tablename__ = "combo_components"

    combo_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("menu_items.id"), index=True)
    sell_option_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sell_options.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)


class ModifierGroup(Record, Base):
    """A choice made when ordering: "Mixer", "Side", "How cooked". `min_select` 1 makes it
    required; `max_select` limits how many options can be picked."""

    __tablename__ = "modifier_groups"

    name: Mapped[str] = mapped_column(String(40))
    min_select: Mapped[int] = mapped_column(Integer, default=0)
    max_select: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ModifierOption(Record, Base):
    """One option in a group, with an extra price (often 0) and, optionally, what it takes
    from stock (a Coke mixer takes one bottle of Coke)."""

    __tablename__ = "modifier_options"

    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("modifier_groups.id"), index=True)
    label: Mapped[str] = mapped_column(String(40))
    price: Mapped[int] = mapped_column(Integer, default=0)
    stock_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stock_items.id"))
    stock_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ItemModifierGroup(Record, Base):
    """Which modifier groups an item asks for."""

    __tablename__ = "item_modifier_groups"

    menu_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("menu_items.id"), index=True)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("modifier_groups.id"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class PriceRule(Record, Base):
    """Happy hour: a percentage off chosen categories (all, if none are chosen) on chosen
    days between two times. Applied when a round is sent, so the price on the bill is
    the price at order time."""

    __tablename__ = "price_rules"

    name: Mapped[str] = mapped_column(String(40))
    percent_off: Mapped[int] = mapped_column(Integer)
    days: Mapped[list[int]] = mapped_column(JSONB, default=lambda: [0, 1, 2, 3, 4, 5, 6])  # Monday = 0
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)  # may be past midnight (start > end)
    category_ids: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
