"""Time-of-day classification. Everything here is evaluated in the paged
person's local timezone — an 03:00 page in Lagos is after-hours even if it is
mid-afternoon at head office."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.metrics.config import WorkingHours

FALLBACK_TZ = "UTC"


def resolve_timezone(*candidates: str | None) -> str:
    """First usable IANA name wins: user, then team, then org."""
    for name in candidates:
        if name and _is_valid_tz(name):
            return name
    return FALLBACK_TZ


def _is_valid_tz(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def to_local(moment: datetime, tz_name: str) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(ZoneInfo(tz_name))


def is_weekend(moment: datetime, tz_name: str, hours: WorkingHours) -> bool:
    return hours.is_weekend(to_local(moment, tz_name).weekday())


def is_after_hours(moment: datetime, tz_name: str, hours: WorkingHours) -> bool:
    """Weekend pages are after-hours by definition — nobody is on the clock."""
    local = to_local(moment, tz_name)
    if hours.is_weekend(local.weekday()):
        return True
    return not (hours.start <= local.time() < hours.end)
