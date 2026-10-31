"""Stock levels and movements (masterplan 4.7-4.8).

A sale never waits for stock: if the system says there is none, the sale still goes
through and the item shows as "check" in the stock list. Stock data can be wrong;
a customer should never be refused because of it.
"""

import uuid
from collections.abc import Iterable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.floor.models import BillLine, VoidReason
from app.menu.models import ModifierOption
from app.stock.models import MovementKind, RecipeLine, StockItem, StockMovement, StockUnit


def factor(item: StockItem) -> int:
    """Stock units in one counting unit: a bottle of a spirit (its size in ml), a kg,
    a litre, a bottle, a piece. Prices and counts are entered per counting unit."""
    if item.unit is StockUnit.ml and item.bottle_size:
        return item.bottle_size
    return 1000 if item.unit in (StockUnit.ml, StockUnit.g) else 1


def buying_price(item: StockItem) -> Decimal:
    """What one counting unit (a bottle, a kg) cost. Kept per ml or g, 1,150 for 750 ml
    comes back as 1,149.98: prices are whole shillings, so it is shown as 1,150."""
    per_unit = item.unit_cost * factor(item)
    whole = per_unit.quantize(Decimal(1))
    return whole if abs(per_unit - whole) < Decimal("0.05") else per_unit.quantize(Decimal("0.01"))


def levels(db: Session, business_id: uuid.UUID) -> dict[uuid.UUID, Decimal]:
    rows = db.execute(
        select(StockMovement.stock_item_id, func.sum(StockMovement.quantity))
        .where(StockMovement.business_id == business_id).group_by(StockMovement.stock_item_id)
    )
    return {item_id: total for item_id, total in rows}


def level(db: Session, item: StockItem) -> Decimal:
    return db.scalar(select(func.coalesce(func.sum(StockMovement.quantity), 0))
                     .where(StockMovement.stock_item_id == item.id))


def move(
    db: Session, item: StockItem, kind: MovementKind, quantity: Decimal, *, actor_id: uuid.UUID | None,
    day: date, reference_id: uuid.UUID | None = None, note: str | None = None,
) -> StockMovement:
    m = StockMovement(business_id=item.business_id, created_by=actor_id, stock_item_id=item.id, kind=kind,
                      quantity=quantity, unit_cost=item.unit_cost, business_day=day,
                      reference_id=reference_id, note=note)
    db.add(m)
    return m


def record_sale(db: Session, lines: Iterable[BillLine], *, tot_size: int | None, actor_id: uuid.UUID, day: date) -> None:
    """Take each sent line's recipe out of stock. Options with no recipe aren't tracked."""
    lines = list(lines)
    modifier_ids = {uuid.UUID(m["id"]) for l in lines for m in (l.modifiers or [])}
    modifier_stock = {
        m.id: m for m in db.scalars(select(ModifierOption).where(ModifierOption.id.in_(modifier_ids),
                                                                 ModifierOption.stock_item_id.is_not(None)))
    } if modifier_ids else {}
    recipes: dict[uuid.UUID, list[RecipeLine]] = {}
    for r in db.scalars(select(RecipeLine).where(RecipeLine.sell_option_id.in_({l.sell_option_id for l in lines}))):
        recipes.setdefault(r.sell_option_id, []).append(r)
    items = {}
    for line in lines:
        for r in recipes.get(line.sell_option_id, []):
            item = items.get(r.stock_item_id) or items.setdefault(r.stock_item_id, db.get(StockItem, r.stock_item_id))
            quantity = r.quantity * (tot_size or 0) if r.in_tots else r.quantity
            move(db, item, MovementKind.sale, -quantity, actor_id=actor_id, day=day, reference_id=line.id,
                 note=line.item_name if not line.option_label else f"{line.item_name} - {line.option_label}")
        for m in line.modifiers or []:
            option = modifier_stock.get(uuid.UUID(m["id"]))
            if option:
                item = items.get(option.stock_item_id) or items.setdefault(option.stock_item_id, db.get(StockItem, option.stock_item_id))
                move(db, item, MovementKind.sale, -(option.stock_quantity or 1), actor_id=actor_id, day=day,
                     reference_id=line.id, note=f"{line.item_name} + {option.label}")


def reverse_sale(db: Session, line: BillLine, reason: VoidReason, *, actor_id: uuid.UUID, day: date, note: str) -> None:
    """A void or a cancelled bill. Not prepared: what the sale took goes back to stock.
    Already prepared: it goes back as a sale, then out again as waste, so the stock
    stays reduced and the loss is visible."""
    for sale in db.scalars(select(StockMovement).where(StockMovement.reference_id == line.id,
                                                       StockMovement.kind == MovementKind.sale)):
        item = db.get(StockItem, sale.stock_item_id)
        move(db, item, MovementKind.sale_return, -sale.quantity, actor_id=actor_id, day=day,
             reference_id=line.id, note=note)
        if reason is VoidReason.already_prepared:
            move(db, item, MovementKind.waste, sale.quantity, actor_id=actor_id, day=day,
                 reference_id=line.id, note=note)


def _fmt(n: Decimal, places: int = 1) -> str:
    q = n.quantize(Decimal(1) / (10 ** places), rounding=ROUND_HALF_UP)
    return f"{q:,.{places}f}".rstrip("0").rstrip(".") if places else f"{q:,.0f}"


def _counted(n: Decimal, places: int, one: str, many: str) -> str:
    text = _fmt(n, places)
    return f"{text} {one if text == '1' else many}"


def describe(item: StockItem, quantity: Decimal, tot_size: int | None) -> str:
    """A quantity as people count it: "1.4 bottles ≈ 42 tots", "24 bottles", "2.5 kg"."""
    q = Decimal(quantity)
    if item.unit is StockUnit.ml and item.bottle_size:
        if q and abs(q / item.bottle_size) < Decimal("0.05"):  # less than a tenth of a bottle: "1 tot", not "0 bottles"
            return _counted(q / tot_size, 0, "tot", "tots") + f" ({_fmt(q, 0)} ml)" if tot_size else f"{_fmt(q, 0)} ml"
        text = _counted(q / item.bottle_size, 1, "bottle", "bottles")
        if tot_size:
            text += f" ≈ {_counted(q / tot_size, 0, 'tot', 'tots')}"
        return text
    if item.unit is StockUnit.g:
        return f"{_fmt(q / 1000, 2)} kg"
    if item.unit is StockUnit.ml:
        return f"{_fmt(q / 1000, 2)} litres"
    return _counted(q, 1, "bottle", "bottles") if item.unit is StockUnit.bottle else f"{_fmt(q, 1)} pcs"


def value(quantity: Decimal, unit_cost: Decimal) -> int:
    return int((Decimal(quantity) * unit_cost).quantize(Decimal(1), rounding=ROUND_HALF_UP))
