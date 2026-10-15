import enum
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, Record, str_enum
from app.menu.models import Station

Quantity = Numeric(14, 3)


class StockUnit(enum.StrEnum):
    """The unit stock is counted in. Spirits are kept in ml (with a bottle size, so they
    can be counted as bottles and tenths); beer and sodas in bottles; kitchen items in
    grams, ml or pieces."""

    ml = "ml"
    bottle = "bottle"
    g = "g"
    piece = "piece"


class StockItem(Record, Base):
    """Something kept in stock. Bottle sizes of the same brand are separate items."""

    __tablename__ = "stock_items"

    name: Mapped[str] = mapped_column(String(80))
    station: Mapped[Station] = mapped_column(str_enum(Station, "station"))
    unit: Mapped[StockUnit] = mapped_column(str_enum(StockUnit, "stock_unit"))
    bottle_size: Mapped[int | None] = mapped_column(Integer)  # ml per bottle, for ml items
    pack_name: Mapped[str | None] = mapped_column(String(20))  # "crate", "carton"
    pack_size: Mapped[int | None] = mapped_column(Integer)  # bottles (or units) per pack
    # Buying price per unit (per ml, bottle, g or piece), from the latest delivery.
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0)
    reorder_level: Mapped[Decimal] = mapped_column(Quantity, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class RecipeLine(Record, Base):
    """What one sell option takes out of stock: a beer takes 1 bottle; a single tot
    takes 1 tot of the bottle (the owner's tot size, in ml); a dish takes its
    ingredients."""

    __tablename__ = "recipe_lines"

    sell_option_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sell_options.id"), index=True)
    stock_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stock_items.id"))
    quantity: Mapped[Decimal] = mapped_column(Quantity)
    in_tots: Mapped[bool] = mapped_column(Boolean, default=False)  # quantity is a number of tots


class Supplier(Record, Base):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(20))


class Delivery(Record, Base):
    """Stock received from a supplier. Permanent."""

    __tablename__ = "deliveries"

    supplier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("suppliers.id"))
    note: Mapped[str | None] = mapped_column(String(200))
    business_day: Mapped[date] = mapped_column(Date)


class DeliveryLine(Record, Base):
    __tablename__ = "delivery_lines"

    delivery_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("deliveries.id"), index=True)
    stock_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stock_items.id"))
    quantity: Mapped[Decimal] = mapped_column(Quantity)  # in the item's unit
    cost: Mapped[int | None] = mapped_column(Integer)  # what was paid for this line, if known


class StockTake(Record, Base):
    """A count of some or all stock. The first one at install is the opening stock. Permanent."""

    __tablename__ = "stock_takes"

    note: Mapped[str | None] = mapped_column(String(200))
    business_day: Mapped[date] = mapped_column(Date)


class StockTakeLine(Record, Base):
    __tablename__ = "stock_take_lines"

    stock_take_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stock_takes.id"), index=True)
    stock_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stock_items.id"))
    expected: Mapped[Decimal] = mapped_column(Quantity)  # what Faida thought was there
    counted: Mapped[Decimal] = mapped_column(Quantity)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4))


class MovementKind(enum.StrEnum):
    sale = "sale"  # out, when a round is sent
    sale_return = "sale_return"  # in: a void or cancelled bill, item not prepared
    waste = "waste"  # out: breakage, spillage, or a void/cancel of something already prepared
    delivery = "delivery"  # in
    stock_take = "stock_take"  # in or out: bringing the system in line with the count


class StockMovement(Record, Base):
    """Every stock change, ever. The stock level is the sum of an item's movements.
    Permanent: mistakes are corrected with new movements."""

    __tablename__ = "stock_movements"

    stock_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stock_items.id"), index=True)
    kind: Mapped[MovementKind] = mapped_column(str_enum(MovementKind, "movement_kind"))
    quantity: Mapped[Decimal] = mapped_column(Quantity)  # + in, - out, in the item's unit
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4))  # buying price at the time
    business_day: Mapped[date] = mapped_column(Date, index=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column()  # bill line, delivery or stock take
    note: Mapped[str | None] = mapped_column(String(200))
