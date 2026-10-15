from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def business_day(at: datetime, cutoff: time, tz: ZoneInfo) -> date:
    """The business day a moment belongs to.

    A bar trades past midnight, so the day ends at the owner's cut-off (default 06:00):
    with that cut-off, 01:30 on Saturday belongs to Friday.
    """
    local = at.astimezone(tz)
    if local.time() < cutoff:
        return local.date() - timedelta(days=1)
    return local.date()
