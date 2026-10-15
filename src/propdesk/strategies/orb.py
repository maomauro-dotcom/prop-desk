"""Opening Range Breakout (ORB).

* Range: bars opening 09:30 ET up to 09:30 + range_minutes (default 15, configurable 5-15).
* Entry: first 1-minute bar that CLOSES outside the range, between the end of the range
  and `entry_end` (11:00 ET), confirmed by volume (bar volume >= volume_mult x average of
  the previous 20 bars) or a minimum ATR, depending on `filter_mode`.
* Stop: opposite extreme of the range. Target: target_r x risk (1.5R default, up to 2R).
* Optional VWAP bias: longs only above VWAP, shorts only below.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from propdesk.domain.clock import RTH_OPEN, at, to_et
from propdesk.domain.models import Bar, Side, Signal
from propdesk.strategies.base import Strategy, StrategyContext, param, parse_hhmm


@dataclass(slots=True)
class OrbParams:
    range_minutes: int = param(15, label="Minutos del rango", minimum=5, maximum=15)
    entry_end: str = param("11:00", label="Fin de entradas (ET)")
    volume_mult: float = param(1.2, label="Multiplicador de volumen", minimum=0.0, maximum=5.0)
    filter_mode: str = param("volume", label="Confirmación", choices=("volume", "atr", "either"))
    min_atr: float = param(0.0, label="ATR mínimo (puntos)", minimum=0.0, maximum=100.0)
    target_r: float = param(1.5, label="Objetivo (R)", minimum=1.0, maximum=2.0)
    use_vwap_bias: bool = param(False, label="Sesgo VWAP")
    max_trades_per_day: int = param(1, label="Señales por día y símbolo", minimum=1, maximum=2)


@dataclass(slots=True)
class _OrbDay:
    day: date | None = None
    fired: int = 0
    sides: set[Side] = field(default_factory=set)


class OrbStrategy(Strategy[OrbParams]):
    strategy_id = "orb"
    display_name = "Ruptura del rango de apertura (ORB)"
    params_cls = OrbParams

    def reset(self) -> None:
        self._state: dict[str, _OrbDay] = {}

    def validate_params(self, params: OrbParams) -> list[str]:
        errs = []
        if params.filter_mode == "atr" and params.min_atr <= 0:
            errs.append("filter_mode=atr requires min_atr > 0")
        return errs

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        sess = ctx.session
        if sess.day is None or not sess.bars or sess.bars[-1] is not bar:
            return []
        st = self._state.setdefault(bar.symbol, _OrbDay())
        if st.day != sess.day:
            st.day, st.fired, st.sides = sess.day, 0, set()
        if st.fired >= p.max_trades_per_day:
            return []

        orng = sess.opening_range(p.range_minutes)
        if orng is None:
            return []
        hi, lo = orng
        start = at(sess.day, RTH_OPEN) + timedelta(minutes=p.range_minutes)
        end = at(sess.day, parse_hhmm(p.entry_end))
        ts = to_et(bar.timestamp)
        if ts < start or ts >= end:
            return []

        if bar.close > hi:
            side = Side.LONG
        elif bar.close < lo:
            side = Side.SHORT
        else:
            return []
        if side in st.sides:
            return []

        avg_vol = sess.avg_volume(20)
        vol_ok = avg_vol is not None and bar.volume >= p.volume_mult * avg_vol
        atr_ok = p.min_atr > 0 and ctx.atr is not None and ctx.atr >= p.min_atr
        confirmed = {"volume": vol_ok, "atr": atr_ok, "either": vol_ok or atr_ok}[p.filter_mode]
        if not confirmed:
            return []
        if p.use_vwap_bias and sess.vwap is not None:
            if (side is Side.LONG and bar.close <= sess.vwap) or (side is Side.SHORT and bar.close >= sess.vwap):
                return []
        ok, _why = ctx.volatility.check(bar, ctx.atr)
        if not ok:
            return []

        entry = bar.close
        stop = lo if side is Side.LONG else hi
        risk = abs(entry - stop)
        if risk <= 0:
            return []
        target = entry + side.sign * p.target_r * risk
        st.fired += 1
        st.sides.add(side)
        return [Signal(
            strategy_id=self.strategy_id,
            symbol=bar.symbol,
            side=side,
            price=entry,
            timestamp=self.bar_close_time(bar),
            stop=stop,
            target=round(target, 2),
            metadata={
                "orb_high": hi,
                "orb_low": lo,
                "range_minutes": p.range_minutes,
                "bar_volume": bar.volume,
                "avg_volume": None if avg_vol is None else round(avg_vol, 1),
                "atr": None if ctx.atr is None else round(ctx.atr, 2),
                "vwap": None if sess.vwap is None else round(sess.vwap, 2),
                "target_r": p.target_r,
            },
        )]
