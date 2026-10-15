"""Liquidity sweep (stop run + fast rejection).

Units: `min_penetration` and `stop_buffer` are multiples of ATR(14) of 1-minute bars.

* Levels: confirmed fractal swings of the session (`swing_k` bars each side), previous
  day high/low, and the opening range extremes (`range_minutes`).
* A level is live until a bar CLOSES beyond it or it gets swept.
* Sweep: a bar trades beyond the level by at least min_penetration x ATR.
* Rejection: that bar or one of the next `reject_bars` closes back inside the level -> entry
  against the sweep at the close.
* Stop: beyond the sweep extreme + stop_buffer x ATR.
* Target: opposite liquidity (nearest level on the other side) when it gives between
  target_r and max_r; otherwise target_r x risk.
* Entries between `entry_start` and `entry_end` (15:45 ET).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from propdesk.domain.clock import to_et
from propdesk.domain.models import Bar, Side, Signal
from propdesk.engine.session import SymbolSession
from propdesk.strategies.base import Strategy, StrategyContext, param, parse_hhmm


@dataclass(slots=True)
class LiquiditySweepParams:
    swing_k: int = param(2, label="Swing k (barras a cada lado)", minimum=1, maximum=5)
    swing_lookback: int = param(90, label="Swings: barras hacia atrás", minimum=10, maximum=390)
    range_minutes: int = param(15, label="Minutos del rango de apertura", minimum=5, maximum=30)
    min_penetration: float = param(0.25, label="Penetración mínima (xATR)", minimum=0.0, maximum=3.0)
    reject_bars: int = param(2, label="Barras para el rechazo", minimum=0, maximum=5)
    stop_buffer: float = param(0.5, label="Buffer del stop (xATR)", minimum=0.0, maximum=3.0)
    target_r: float = param(1.5, label="Objetivo (R)", minimum=1.0, maximum=2.0)
    max_r: float = param(2.0, label="R máximo con liquidez opuesta", minimum=1.0, maximum=4.0)
    use_opposite_liquidity: bool = param(True, label="Objetivo en liquidez opuesta")
    use_prev_day: bool = param(True, label="Usar high/low del día previo")
    use_opening_range: bool = param(True, label="Usar extremos del rango de apertura")
    use_swings: bool = param(True, label="Usar swings recientes")
    entry_start: str = param("09:35", label="Inicio de entradas (ET)")
    entry_end: str = param("15:45", label="Fin de entradas (ET)")
    max_signals_per_day: int = param(2, label="Señales por día y símbolo", minimum=1, maximum=4)


@dataclass(slots=True)
class _Level:
    kind: str  # "high" | "low"
    price: float
    source: str  # swing | prev_day | opening_range
    since_idx: int  # first bar index at which the level is known

    @property
    def key(self) -> tuple[str, str, float]:
        return (self.kind, self.source, round(self.price, 4))


@dataclass(slots=True)
class _Pending:
    level: _Level
    extreme: float
    idx: int


@dataclass(slots=True)
class _SweepState:
    day: date | None = None
    fired: int = 0
    consumed: set[tuple[str, str, float]] = field(default_factory=set)
    pending: list[_Pending] = field(default_factory=list)


class LiquiditySweepStrategy(Strategy[LiquiditySweepParams]):
    strategy_id = "liquidity_sweep"
    display_name = "Barrido de liquidez (sweep)"
    params_cls = LiquiditySweepParams

    def reset(self) -> None:
        self._state: dict[str, _SweepState] = {}

    # ---------------------------------------------------------------- levels
    def levels(self, sess: SymbolSession) -> list[_Level]:
        p = self.params
        n = len(sess.bars)
        out: list[_Level] = []
        if p.use_prev_day and sess.prev_day_high is not None and sess.prev_day_low is not None:
            out.append(_Level("high", sess.prev_day_high, "prev_day", 0))
            out.append(_Level("low", sess.prev_day_low, "prev_day", 0))
        if p.use_opening_range:
            orng = sess.opening_range(p.range_minutes)
            if orng is not None:
                out.append(_Level("high", orng[0], "opening_range", p.range_minutes))
                out.append(_Level("low", orng[1], "opening_range", p.range_minutes))
        if p.use_swings:
            # Only swings confirmed before the current bar.
            for sw in sess.confirmed_swings(p.swing_k):
                if sw.index + p.swing_k <= n - 2 and sw.index >= n - 1 - p.swing_lookback:
                    out.append(_Level(sw.kind, sw.price, "swing", sw.index + p.swing_k + 1))
        live = []
        for lv in out:
            closes = [b.close for b in sess.bars[lv.since_idx:n - 1]]
            if lv.kind == "high" and any(c > lv.price for c in closes):
                continue
            if lv.kind == "low" and any(c < lv.price for c in closes):
                continue
            live.append(lv)
        return live

    def liquidity_levels(self, sess: SymbolSession) -> list[dict[str, Any]]:
        return [{"kind": lv.kind, "price": lv.price, "source": lv.source} for lv in self.levels(sess)]

    # ---------------------------------------------------------------- on_bar
    def on_bar(self, bar: Bar, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        sess = ctx.session
        if sess.day is None or not sess.bars or sess.bars[-1] is not bar:
            return []
        st = self._state.setdefault(bar.symbol, _SweepState())
        if st.day != sess.day:
            st.day, st.fired, st.consumed, st.pending = sess.day, 0, set(), []
        atr = ctx.atr
        if atr is None:
            return []
        idx = len(sess.bars) - 1
        pen = p.min_penetration * atr

        # New sweeps on this bar.
        levels = [lv for lv in self.levels(sess) if lv.key not in st.consumed]
        for lv in levels:
            if lv.kind == "high" and bar.high >= lv.price + pen:
                st.consumed.add(lv.key)
                st.pending.append(_Pending(lv, bar.high, idx))
            elif lv.kind == "low" and bar.low <= lv.price - pen:
                st.consumed.add(lv.key)
                st.pending.append(_Pending(lv, bar.low, idx))

        # Update / resolve pending sweeps.
        triggered: list[_Pending] = []
        still: list[_Pending] = []
        for pd in st.pending:
            if idx > pd.idx:
                pd.extreme = max(pd.extreme, bar.high) if pd.level.kind == "high" else min(pd.extreme, bar.low)
            rejected = (bar.close < pd.level.price) if pd.level.kind == "high" else (bar.close > pd.level.price)
            if rejected:
                triggered.append(pd)
            elif idx - pd.idx < p.reject_bars:
                still.append(pd)
        st.pending = still
        if not triggered:
            return []

        # Most significant sweep wins: the furthest level from the close.
        best = max(triggered, key=lambda pd: abs(pd.level.price - bar.close))
        sess.last_sweep = {
            "time": to_et(bar.timestamp).isoformat(),
            "kind": best.level.kind,
            "source": best.level.source,
            "level": best.level.price,
            "extreme": best.extreme,
        }

        ts = to_et(bar.timestamp)
        if not (parse_hhmm(p.entry_start) <= ts.time() < parse_hhmm(p.entry_end)):
            return []
        if st.fired >= p.max_signals_per_day:
            return []
        ok, _why = ctx.volatility.check(bar, atr)
        if not ok:
            return []

        side = Side.SHORT if best.level.kind == "high" else Side.LONG
        entry = bar.close
        stop = best.extreme + p.stop_buffer * atr if side is Side.SHORT else best.extreme - p.stop_buffer * atr
        risk = abs(entry - stop)
        if risk <= 0:
            return []
        target = entry + side.sign * p.target_r * risk
        target_kind = "r_multiple"
        if p.use_opposite_liquidity:
            opp_kind = "low" if side is Side.SHORT else "high"
            opp = [lv.price for lv in self.levels(sess) if lv.kind == opp_kind
                   and (lv.price < entry if side is Side.SHORT else lv.price > entry)]
            opp.sort(key=lambda x: abs(x - entry))
            for price in opp:
                r = abs(price - entry) / risk
                if p.target_r <= r <= p.max_r:
                    target, target_kind = price, "opposite_liquidity"
                    break
        st.fired += 1
        return [Signal(
            strategy_id=self.strategy_id,
            symbol=bar.symbol,
            side=side,
            price=entry,
            timestamp=self.bar_close_time(bar),
            stop=round(stop, 2),
            target=round(target, 2),
            metadata={
                "swept_level": best.level.price,
                "level_source": best.level.source,
                "sweep_extreme": best.extreme,
                "atr": round(atr, 2),
                "target_kind": target_kind,
            },
        )]
