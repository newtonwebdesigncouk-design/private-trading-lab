"""Explicit expected-date calendars for data-quality diagnostics."""

from collections.abc import Collection
from datetime import UTC, date, datetime, timedelta

from app.models.enums import AssetClass


def expected_daily_close_timestamps(
    start: date,
    end: date,
    *,
    asset_class: AssetClass,
    holidays: Collection[date] = (),
) -> tuple[datetime, ...]:
    """Return conservative next-day UTC availability timestamps for expected sessions."""
    if start > end:
        raise ValueError("calendar start must not follow end")
    closures = set(holidays)
    values: list[datetime] = []
    current = start
    while current <= end:
        weekday_session = current.weekday() < 5
        expected = asset_class is AssetClass.CRYPTOCURRENCY or weekday_session
        if expected and current not in closures:
            values.append(datetime.combine(current + timedelta(days=1), datetime.min.time(), UTC))
        current += timedelta(days=1)
    return tuple(values)
