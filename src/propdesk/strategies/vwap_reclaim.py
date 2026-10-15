"""VWAP pullback / reclaim.

Units: `trend_margin`, `min_slope`, `touch_tolerance` and `stop_buffer` are multiples of
ATR(14) of 1-minute bars, so the same numbers work for MNQ and MES.

* VWAP: session VWAP anchored at 09:30 ET (typical price, volume weighted) with sigma bands.
* Trend: the `trend_bars` bars before the current one all closed at least
  trend_margin x ATR on the same side of VWAP, and the VWAP slope over that window is
  at least min_slope x ATR per bar in the same direction.
* Pullback (continuation): in a trend, the bar trades back to VWAP (within
  touch_tolerance x ATR), closes back on the trend side, with a rejection structure
  (close in the trend-side half of the bar) or volume >= volume_mult x average.
* Reclaim (reversal): price was mostly on one side of VWAP, a decisive bar closes
  trend_margin x ATR on the other side with a real body; within `retest_bars` a bar
  retests VWAP and closes on the new side -> entry.
* Stop: beyond VWAP (and the signal bar) plus stop_buffer x ATR.
* Target: nearest of the band_sigma VWAP band or the session high/low that yields at
  least min_rr; otherwise no signal.
* Entries until `entry_end` (15:45 ET).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from propdesk.domain.clock import to_et
from propdesk.domain.models import Bar, Side, Signal
from propdesk.strategies.base import Strategy, StrategyContext, param, parse_hhmm


@dataclass(slots=True)
class VwapReclaimParams:
    trend_bars: int = param(8, label="Barras de tendencia", minimum=3, maximum=30)
    trend_margin: float = param(0.5, label="Margen de tendencia (xATR)", minimum=0.0, maximum=3.0)
    min_slope: float = param(0.05, label="Pendiente mínima (xATR/barra)", minimum=0.0, maximum=1.0)
    touch_tolerance: float = param(0.25, label="Tolerancia de toque (xATR)", minimum=0.0, maximum=2.0)
    volume_mult: float = param(1.0, label="Multiplicador de volumen", minimum=0.0, maximum=5.0)
    retest_bars: int = param(5, label="Barras para el retest", minimum=1, maximum=20)
    stop_buffer: float = param(0.5, label="Buffer del stop (xATR)", minimum=0.0, maximum=3.0)
    band_sigma: float = param(2.0, label="Banda de desviación (sigma)", minimum=0.5, maximum=4.0)
    min_rr: float = param(1.0, label="R mínimo del objetivo", minimum=0.5, maximum=3.0)
    entry_start: str = param("09:45", label="Inicio de entradas (ET)")
    entry_end: str = param("15:45", label="Fin de entradas (ET)")
    max_signals_per_day: int = param(2, label="Señales por día y símbolo", minimum=1, maximum=4)
    cooldown_bars: int = param(15, label="Barras de enfriamiento", minimum=0, maximum=120)


@dataclass(slots=True)
class _VwapState:
    day: date | None = None
    fired: int = 0
    last_signal_idx: int = -10_000
    armed_side: Side | None = None
    armed_idx: int = -1


class VwapReclaimStrategy(Strategy[VwapReclaimParams]):
    strategy_id = "vwap_reclaim"
    display_name = "Pullback / reclaim de VWAP"
    params_cls = VwapReclaimParams

    def reset(self) -> None:
        self._state: dict[str, _VwapState] = {}

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        sess = ctx.session
        if sess.day is None or not sess.bars or sess.bars[-1] is not bar:
            return []
        st = self._state.setdefault(bar.symbol, _VwapState())
        if st.day != sess.day:
            st.day, st.fired, st.last_signal_idx, st.armed_side, st.armed_idx = sess.day, 0, -10_000, None, -1
        n = len(sess.bars)
        idx = n - 1
        atr = ctx.atr
        if atr is None or n <= p.trend_bars + 1:
            return []
        vwap = sess.vwaps[-1]
        prior = range(idx - p.trend_bars, idx)
        margin = p.trend_margin * atr
        above = [sess.bars[i].close - sess.vwaps[i] >= margin for i in prior]
        below = [sess.vwaps[i] - sess.bars[i].close >= margin for i in prior]
        slope = sess.vwap_slope(p.trend_bars) or 0.0
        tol = p.touch_tolerance * atr

        # --- reclaim state machine (arming happens regardless of the entry window)
        frac_below = sum(sess.bars[i].close < sess.vwaps[i] for i in prior) / p.trend_bars
        frac_above = sum(sess.bars[i].close > sess.vwaps[i] for i in prior) / p.trend_bars
        body = abs(bar.close - bar.open)
        decisive = bar.range > 0 and body >= 0.5 * bar.range
        if st.armed_side is None or idx - st.armed_idx > p.retest_bars:
            st.armed_side = None
            if frac_below >= 0.75 and bar.close - vwap >= margin and bar.close > bar.open and decisive:
                st.armed_side, st.armed_idx = Side.LONG, idx
                return []
            if frac_above >= 0.75 and vwap - bar.close >= margin and bar.close < bar.open and decisive:
                st.armed_side, st.armed_idx = Side.SHORT, idx
                return []

        ts = to_et(bar.timestamp)
        if not (parse_hhmm(p.entry_start) <= ts.time() < parse_hhmm(p.entry_end)):
            return []
        if st.fired >= p.max_signals_per_day or idx - st.last_signal_idx < p.cooldown_bars:
            return []

        avg_vol = sess.avg_volume(20)
        vol_ok = avg_vol is not None and bar.volume >= p.volume_mult * avg_vol
        mid = (bar.high + bar.low) / 2

        side: Side | None = None
        mode = ""
        if st.armed_side is not None and idx > st.armed_idx:
            s = st.armed_side
            if s is Side.LONG and bar.low <= vwap + tol and bar.close > vwap:
                side, mode = Side.LONG, "reclaim"
            elif s is Side.SHORT and bar.high >= vwap - tol and bar.close < vwap:
                side, mode = Side.SHORT, "reclaim"
            elif (s is Side.LONG and bar.close < vwap - margin) or (s is Side.SHORT and bar.close > vwap + margin):
                st.armed_side = None
        if side is None:
            if all(above) and slope >= p.min_slope * atr and bar.low <= vwap + tol and bar.close > vwap \
                    and bar.close >= bar.open and (bar.close >= mid or vol_ok):
                side, mode = Side.LONG, "pullback"
            elif all(below) and slope <= -p.min_slope * atr and bar.high >= vwap - tol and bar.close < vwap \
                    and bar.close <= bar.open and (bar.close <= mid or vol_ok):
                side, mode = Side.SHORT, "pullback"
        if side is None:
            return []

        ok, _why = ctx.volatility.check(bar, atr)
        if not ok:
            return []

        entry = bar.close
        std = sess.vwap_stds[-1]
        buf = p.stop_buffer * atr
        if side is Side.LONG:
            stop = min(bar.low, vwap) - buf
            candidates = sorted(c for c in (vwap + p.band_sigma * std, sess.day_high) if c is not None and c > entry)
        else:
            stop = max(bar.high, vwap) + buf
            candidates = sorted((c for c in (vwap - p.band_sigma * std, sess.day_low) if c is not None and c < entry),
                                reverse=True)
        risk = abs(entry - stop)
        if risk <= 0:
            return []
        target = next((c for c in candidates if abs(c - entry) / risk >= p.min_rr), None)
        if target is None:
            return []
        st.fired += 1
        st.last_signal_idx = idx
        st.armed_side = None
        return [Signal(
            strategy_id=self.strategy_id,
            symbol=bar.symbol,
            side=side,
            price=entry,
            timestamp=self.bar_close_time(bar),
            stop=round(stop, 2),
            target=round(target, 2),
            metadata={
                "mode": mode,
                "vwap": round(vwap, 2),
                "vwap_std": round(std, 2),
                "slope_per_bar": round(slope, 3),
                "atr": round(atr, 2),
                "target_kind": "band" if abs(target - (vwap + side.sign * p.band_sigma * std)) < 1e-9 else "session_level",
            },
        )]
