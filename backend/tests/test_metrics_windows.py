from datetime import UTC, datetime, time

import pytest

from app.metrics.config import WorkingHours
from app.metrics.windows import is_after_hours, is_weekend, resolve_timezone

HOURS = WorkingHours(
    start=time(9, 0), end=time(18, 0), weekend_days=frozenset({"saturday", "sunday"})
)

# 2026-09-09 is a Wednesday.
WEDNESDAY_NOON_UTC = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def test_midday_on_a_weekday_is_working_hours():
    assert is_after_hours(WEDNESDAY_NOON_UTC, "UTC", HOURS) is False


def test_start_of_the_working_day_is_inside_hours():
    at_nine = datetime(2026, 9, 9, 9, 0, tzinfo=UTC)
    assert is_after_hours(at_nine, "UTC", HOURS) is False


def test_end_of_the_working_day_is_outside_hours():
    """18:00 is the boundary — the day is over, so a page then is after-hours."""
    at_six = datetime(2026, 9, 9, 18, 0, tzinfo=UTC)
    assert is_after_hours(at_six, "UTC", HOURS) is True


def test_one_minute_before_close_is_still_working_hours():
    assert is_after_hours(datetime(2026, 9, 9, 17, 59, tzinfo=UTC), "UTC", HOURS) is False


@pytest.mark.parametrize(
    ("tz_name", "local_hour", "expected_after_hours"),
    [
        ("UTC", 12, False),
        ("America/New_York", 8, True),  # before the working day starts
        ("Asia/Tokyo", 21, True),
        ("Australia/Sydney", 22, True),
    ],
)
def test_classification_follows_the_persons_timezone(tz_name, local_hour, expected_after_hours):
    """Same instant, different people: the burden lands where they are, not
    where the incident was filed."""
    assert is_after_hours(WEDNESDAY_NOON_UTC, tz_name, HOURS) is expected_after_hours


def test_weekend_pages_count_as_after_hours():
    saturday_noon = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    assert is_weekend(saturday_noon, "UTC", HOURS) is True
    assert is_after_hours(saturday_noon, "UTC", HOURS) is True


def test_weekend_is_evaluated_locally_not_in_utc():
    """Friday 23:00 in New York is already Saturday in UTC — the person is not
    on weekend duty yet."""
    friday_late_ny = datetime(2026, 9, 12, 3, 0, tzinfo=UTC)  # Fri 23:00 EDT
    assert is_weekend(friday_late_ny, "America/New_York", HOURS) is False
    assert is_weekend(friday_late_ny, "UTC", HOURS) is True


def test_dst_shift_is_handled():
    """US clocks moved on 2026-03-08. 13:00 UTC is 09:00 EDT after the shift and
    08:00 EST before it."""
    after_dst = datetime(2026, 3, 9, 13, 0, tzinfo=UTC)
    before_dst = datetime(2026, 3, 6, 13, 0, tzinfo=UTC)
    assert is_after_hours(after_dst, "America/New_York", HOURS) is False
    assert is_after_hours(before_dst, "America/New_York", HOURS) is True


def test_naive_timestamps_are_treated_as_utc():
    naive = datetime(2026, 9, 9, 12, 0)
    assert is_after_hours(naive, "UTC", HOURS) is False


def test_custom_weekend_days_are_respected():
    """Fri/Sat weekends are the norm in much of the Middle East."""
    hours = WorkingHours(
        start=time(9, 0), end=time(18, 0), weekend_days=frozenset({"friday", "saturday"})
    )
    friday = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
    sunday = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    assert is_weekend(friday, "UTC", hours) is True
    assert is_weekend(sunday, "UTC", hours) is False


def test_timezone_resolution_prefers_the_first_usable_name():
    assert resolve_timezone(None, "Europe/London", "UTC") == "Europe/London"
    assert resolve_timezone("Asia/Tokyo", "Europe/London", "UTC") == "Asia/Tokyo"


def test_timezone_resolution_skips_garbage_and_falls_back():
    assert resolve_timezone("Mars/Olympus", None, "Europe/Lisbon") == "Europe/Lisbon"
    assert resolve_timezone(None, None, None) == "UTC"
