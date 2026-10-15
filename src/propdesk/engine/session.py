"""Per-symbol RTH session state: VWAP (anchored 09:30 ET), bands, ATR, opening range, swings, levels."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from propdesk.domain.clock import RTH_OPEN, at, is_rth, session_date, to_et
from propdesk.domain.models import Bar

ATR_PERIOD = 14


@dataclass(slots=True)
class Swing:
    index: int
    price: float
    kind: str  # "high" | "low"


@dataclass
class SymbolSession:
    symbol: str
    day: date | None = None
    bars: list[Bar] = field(default_factory=list)
    vwaps: list[float] = field(default_factory=list)
    vwap_stds: list[float] = field(default_factory=list)
    atrs: list[float] = field(default_factory=list)
    cum_v: float = 0.0
    cum_pv: float = 0.0
    cum_pv2: float = 0.0
    atr: float | None = None
    _atr_seed: list[float] = field(default_factory=list)
    prev_day_high: float | None = None
    prev_day_low: float | None = None
    prev_close: float | None = None
    last_sweep: dict[str, Any] | None = None
    history: deque[Bar] = field(default_factory=lambda: deque(maxlen=2000))

    # ----------------------------------------------------------------- update
    def _roll_day(self, day: date) -> None:
        if self.bars:
            self.prev_day_high = max(b.high for b in self.bars)
            self.prev_day_low = min(b.low for b in self.bars)
            self.prev_close = self.bars[-1].close
        self.day = day
        self.bars = []
        self.vwaps = []
        self.vwap_stds = []
        self.atrs = []
        self.cum_v = self.cum_pv = self.cum_pv2 = 0.0
        self.last_sweep = None

    def update(self, bar: Bar) -> None:
        day = session_date(bar.timestamp)
        if self.day != day:
            self._roll_day(day)
        if self.bars and bar.timestamp <= self.bars[-1].timestamp:
            raise ValueError(f"out-of-order bar for {self.symbol}: {bar.timestamp} <= {self.bars[-1].timestamp}")
        prev = self.bars[-1] if self.bars else None
        tr = bar.range if prev is None else max(bar.range, abs(bar.high - prev.close), abs(bar.low - prev.close))
        if self.atr is None or len(self._atr_seed) < ATR_PERIOD:
            self._atr_seed.append(tr)
            self.atr = sum(self._atr_seed) / len(self._atr_seed)
        else:
            self.atr = (self.atr * (ATR_PERIOD - 1) + tr) / ATR_PERIOD
        typical = (bar.high + bar.low + bar.close) / 3.0
        vol = max(bar.volume, 1e-9)
        self.cum_v += vol
        self.cum_pv += typical * vol
        self.cum_pv2 += typical * typical * vol
        vwap = self.cum_pv / self.cum_v
        var = max(self.cum_pv2 / self.cum_v - vwap * vwap, 0.0)
        self.bars.append(bar)
        self.vwaps.append(vwap)
        self.vwap_stds.append(math.sqrt(var))
        self.atrs.append(self.atr)
        self.history.append(bar)

    # ---------------------------------------------------------------- queries
    @property
    def vwap(self) -> float | None:
        return self.vwaps[-1] if self.vwaps else None

    @property
    def vwap_std(self) -> float | None:
        return self.vwap_stds[-1] if self.vwap_stds else None

    @property
    def day_high(self) -> float | None:
        return max(b.high for b in self.bars) if self.bars else None

    @property
    def day_low(self) -> float | None:
        return min(b.low for b in self.bars) if self.bars else None

    def opening_range(self, minutes: int) -> tuple[float, float] | None:
        """(high, low) of bars opening in [09:30, 09:30+minutes). None until complete."""
        if not self.bars or self.day is None:
            return None
        start = at(self.day, RTH_OPEN)
        end = start + timedelta(minutes=minutes)
        if self.bars[-1].timestamp < end - timedelta(minutes=1):
            return None
        rng = [b for b in self.bars if start <= b.timestamp < end]
        if not rng:
            return None
        return max(b.high for b in rng), min(b.low for b in rng)

    def opening_range_volume(self, minutes: int) -> float | None:
        if self.day is None:
            return None
        start = at(self.day, RTH_OPEN)
        end = start + timedelta(minutes=minutes)
        rng = [b.volume for b in self.bars if start <= b.timestamp < end]
        return sum(rng) / len(rng) if rng else None

    def avg_volume(self, n: int = 20, exclude_last: bool = True) -> float | None:
        src = self.bars[:-1] if exclude_last else self.bars
        window = src[-n:]
        return sum(b.volume for b in window) / len(window) if window else None

    def vwap_slope(self, n: int) -> float | None:
        """VWAP change per bar over the last n bars."""
        if len(self.vwaps) <= n:
            return None
        return (self.vwaps[-1] - self.vwaps[-1 - n]) / n

    def confirmed_swings(self, k: int) -> list[Swing]:
        """Fractal swings: a high (low) strictly above (below) the k bars on each side, confirmed."""
        out: list[Swing] = []
        bars = self.bars
        for i in range(k, len(bars) - k):
            hi = bars[i].high
            lo = bars[i].low
            neigh = bars[i - k:i] + bars[i + 1:i + 1 + k]
            if all(hi > b.high for b in neigh):
                out.append(Swing(i, hi, "high"))
            if all(lo < b.low for b in neigh):
                out.append(Swing(i, lo, "low"))
        return out

    def context_dict(self, range_minutes: int = 15) -> dict[str, Any]:
        orng = self.opening_range(range_minutes)
        last = self.bars[-1] if self.bars else None
        std = self.vwap_std or 0.0
        return {
            "symbol": self.symbol,
            "day": self.day.isoformat() if self.day else None,
            "bars": len(self.bars),
            "last_time": last.timestamp.isoformat() if last else None,
            "last_close": last.close if last else None,
            "vwap": None if self.vwap is None else round(self.vwap, 2),
            "vwap_upper_2sd": None if self.vwap is None else round(self.vwap + 2 * std, 2),
            "vwap_lower_2sd": None if self.vwap is None else round(self.vwap - 2 * std, 2),
            "atr": None if self.atr is None else round(self.atr, 2),
            "orb_minutes": range_minutes,
            "orb_high": orng[0] if orng else None,
            "orb_low": orng[1] if orng else None,
            "day_high": self.day_high,
            "day_low": self.day_low,
            "prev_day_high": self.prev_day_high,
            "prev_day_low": self.prev_day_low,
            "last_sweep": self.last_sweep,
        }


class SessionTracker:
    """Holds a SymbolSession per symbol. Only RTH bars update the session."""

    def __init__(self) -> None:
        self.sessions: dict[str, SymbolSession] = {}

    def get(self, symbol: str) -> SymbolSession:
        if symbol not in self.sessions:
            self.sessions[symbol] = SymbolSession(symbol)
        return self.sessions[symbol]

    def update(self, bar: Bar) -> SymbolSession | None:
        if not is_rth(bar.timestamp):
            return None
        sess = self.get(bar.symbol)
        sess.update(bar)
        return sess

    def reset(self) -> None:
        self.sessions.clear()

    def snapshot(self, range_minutes: int = 15) -> dict[str, Any]:
        return {sym: s.context_dict(range_minutes) for sym, s in sorted(self.sessions.items())}


def bar_time(bar: Bar):  # noqa: ANN201 - tiny helper
    return to_et(bar.timestamp).time()
