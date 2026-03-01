from __future__ import annotations

from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo


# Single source of truth for local timezone
LONDON_TZ = ZoneInfo("Europe/London")


def now_london() -> datetime:
    """Current time as an aware datetime in Europe/London."""
    return datetime.now(LONDON_TZ)


def to_london(dt: datetime) -> datetime:
    """Ensure a datetime is in Europe/London timezone.

    - If `dt` is naive, treat it as Europe/London local time.git 
    - If `dt` is aware, convert to Europe/London.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=LONDON_TZ)
    return dt.astimezone(LONDON_TZ)


def iso_seconds_local(dt: datetime) -> str:
    """ISO string (seconds precision) with Europe/London timezone offset.

    We persist timezone-aware local timestamps so the DB always carries
    explicit London time including DST (+00:00/+01:00).
    """
    return to_london(dt).isoformat(timespec="seconds")


def week_monday_london(dt: datetime) -> datetime:
    """Return Monday 00:00 for the week containing `dt`, in London tz (aware)."""
    dt_l = to_london(dt)
    monday_date = dt_l.date() - timedelta(days=dt_l.weekday())
    return datetime.combine(monday_date, time(0, 0), tzinfo=LONDON_TZ)


def next_monday_10_london(after_dt: datetime) -> datetime:
    """Return the next Sunday 09:00 (London) strictly after `after_dt`."""
    dt_l = to_london(after_dt)
    monday_date = dt_l.date() - timedelta(days=dt_l.weekday())
    next_sunday = datetime.combine(monday_date + timedelta(days=6), time(9, 0), tzinfo=LONDON_TZ)
    if dt_l >= next_sunday:
        next_sunday += timedelta(days=7)
    return next_sunday


def voting_window_london(dt: datetime) -> tuple[datetime, datetime]:
    """Voting window (open, close) for the week containing `dt`, London tz (aware).

    Open: Sunday 09:00
    Close: Tuesday 21:00
    """
    week_monday = week_monday_london(dt)
    # Sunday of this week (Mon + 6 days) at 09:00
    open_start = datetime.combine(week_monday.date() + timedelta(days=6), time(9, 0), tzinfo=LONDON_TZ)
    # Tuesday after Sunday is Monday + 8 days (i.e., next week Tuesday)
    close_end = datetime.combine(week_monday.date() + timedelta(days=8), time(21, 0), tzinfo=LONDON_TZ)
    return open_start, close_end
