"""Menu rules used when ordering: happy hour prices."""

import uuid
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.menu.models import PriceRule


def rule_is_on(rule: PriceRule, at: datetime, tz: ZoneInfo) -> bool:
    """Whether a happy hour is running at `at`. A window that crosses midnight (22:00 to
    01:00) belongs to the day it started on."""
    local = at.astimezone(tz)
    t = local.time()
    if rule.start_time <= rule.end_time:
        return rule.start_time <= t < rule.end_time and local.weekday() in rule.days
    if t >= rule.start_time:
        return local.weekday() in rule.days
    if t < rule.end_time:
        return (local - timedelta(days=1)).weekday() in rule.days
    return False


def rules_on(db: Session, business_id: uuid.UUID, at: datetime, tz: ZoneInfo) -> list[PriceRule]:
    rules = db.scalars(select(PriceRule).where(PriceRule.business_id == business_id, PriceRule.active))
    return [r for r in rules if rule_is_on(r, at, tz)]


def best_rule(rules: list[PriceRule], category_id: uuid.UUID) -> PriceRule | None:
    """The biggest offer that covers this category (a rule with no categories covers all)."""
    matching = [r for r in rules if not r.category_ids or str(category_id) in r.category_ids]
    return max(matching, key=lambda r: r.percent_off, default=None)


def offer_price(price: int, rule: PriceRule | None) -> int:
    if rule is None:
        return price
    return int((Decimal(price) * (100 - rule.percent_off) / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
