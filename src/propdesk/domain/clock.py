"""Session clock helpers. Everything is evaluated in America/New_York."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)


def to_et(ts: datetime) -> datetime:
    """Naive timestamps are interpreted as America/New_York; aware ones are converted."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=ET)
    return ts.astimezone(ET)


def parse_timestamp(value: str | int | float) -> datetime:
    """Parse ISO-8601 (naive = ET) or epoch seconds/milliseconds."""
    if isinstance(value, (int, float)):
        seconds = value / 1000.0 if value > 1e11 else float(value)
        return datetime.fromtimestamp(seconds, tz=ET)
    s = value.strip()
    if s.isdigit():
        return parse_timestamp(int(s))
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return to_et(datetime.fromisoformat(s))


def is_rth(ts: datetime) -> bool:
    t = to_et(ts).timetz().replace(tzinfo=None)
    return RTH_OPEN <= t < RTH_CLOSE


def session_date(ts: datetime) -> date:
    return to_et(ts).date()


def at(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=ET)


def minutes_after_open(ts: datetime) -> float:
    et = to_et(ts)
    return (et - at(et.date(), RTH_OPEN)) / timedelta(minutes=1)


def now_et() -> datetime:
    return datetime.now(tz=ET)
