from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from propdesk.domain.clock import ET
from propdesk.domain.models import Bar


def et(d: date, hh: int, mm: int) -> datetime:
    return datetime.combine(d, time(hh, mm), tzinfo=ET)


def make_bar(symbol: str, ts: datetime, o: float, h: float, l: float, c: float, v: float = 1000) -> Bar:  # noqa: E741
    return Bar(symbol, ts, o, h, l, c, v)


def flat_day(symbol: str, d: date, price: float, start=(9, 30), end=(16, 0), step: float = 0.0,
             wiggle: float = 2.0) -> list[Bar]:
    """Simple deterministic RTH bars, gently drifting by `step` per bar."""
    out = []
    t = et(d, *start)
    stop = et(d, *end)
    p = price
    while t < stop:
        o, c = p, p + step
        out.append(Bar(symbol, t, o, max(o, c) + wiggle, min(o, c) - wiggle, c, 1000))
        p = c
        t += timedelta(minutes=1)
    return out


@pytest.fixture
def day() -> date:
    return date(2026, 10, 5)


@pytest.fixture(scope="session")
def sample_engine():
    from propdesk.engine.engine import TradingEngine
    from propdesk.feeds import CsvBarFeed
    from propdesk.paths import SAMPLE_CSV

    eng = TradingEngine()
    eng.replay(CsvBarFeed(SAMPLE_CSV))
    return eng
