import enum
import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
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
    active: Mapped[bool] = mapped_column(Boolean, default=True)


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
