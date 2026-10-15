"""Trading engine: bar -> strategy -> risk -> optional Claude filter -> paper execution.

Session clock (America/New_York):
  * Only RTH bars (09:30-16:00) feed strategies.
  * At the first bar opening at/after `flatten_time` (15:55) - or on `clock_tick` from the
    backend's wall-clock task - every position is flattened, working orders are cancelled,
    and the day is marked EOD: day P&L moves into the balance, counters reset and the trail
    follows a new EOD peak if there is one.
  * No entry is accepted at or after the flatten cut-off.
"""

from __future__ import annotations

import itertools
import logging
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from propdesk.brokers.paper import BrokerError, PaperBroker
from propdesk.domain.clock import is_rth, now_et, session_date, to_et
from propdesk.domain.instruments import normalize_symbol
from propdesk.domain.models import Bar, Fill, Signal, Trade
from propdesk.domain.profile import RiskProfile
from propdesk.engine.claude_filter import ClaudeFilter
from propdesk.engine.risk import RiskManager
from propdesk.engine.session import SessionTracker
from propdesk.strategies import LiquiditySweepStrategy, Strategy, StrategyContext, build_default_strategies
from propdesk.strategies.filters import VolatilityFilter

log = logging.getLogger("propdesk.engine")

EventSink = Callable[[dict[str, Any]], None]


@dataclass(slots=True)
class ReplayResult:
    bars: int
    signals: int
    accepted: int
    rejected: int
    trades: int
    equity: float
    balance: float


class TradingEngine:
    def __init__(self, profile: RiskProfile | None = None, strategies: dict[str, Strategy] | None = None,
                 broker: PaperBroker | None = None, claude_filter: ClaudeFilter | None = None,
                 volatility: VolatilityFilter | None = None, max_events: int = 2000) -> None:
        self.profile = profile or RiskProfile()
        self.risk = RiskManager(self.profile)
        self.broker = broker or PaperBroker()
        self.strategies: dict[str, Strategy] = strategies if strategies is not None else build_default_strategies()
        self.claude_filter = claude_filter or ClaudeFilter()
        self.volatility = volatility or VolatilityFilter()
        self.tracker = SessionTracker()
        self._sinks: list[EventSink] = []
        self._max_events = max_events
        self.broker.add_fill_listener(self._on_fill)
        self.reset_account()

    # ------------------------------------------------------------- lifecycle
    def reset_account(self, profile: RiskProfile | None = None) -> None:
        if profile is not None:
            self.profile = profile
        self.risk.reset(self.profile)
        self.broker.reset()
        self.tracker.reset()
        for s in self.strategies.values():
            s.reset()
        self._seq = itertools.count(1)
        self.signals: deque[dict[str, Any]] = deque(maxlen=1000)
        self.events: deque[dict[str, Any]] = deque(maxlen=self._max_events)
        self.equity_curve: list[dict[str, Any]] = []
        self.current_day: date | None = None
        self.last_bar_time: datetime | None = None
        self.flattened_day: date | None = None
        self.eod_marked_day: date | None = None
        self.bars_processed = 0

    def add_sink(self, sink: EventSink) -> None:
        self._sinks.append(sink)

    def update_profile(self, profile: RiskProfile) -> None:
        self.profile = profile
        self.risk.update_profile(profile)
        self.emit("info", "profile_updated", "Reglas de riesgo actualizadas", profile.to_dict())

    # ---------------------------------------------------------------- events
    def emit(self, level: str, event: str, message: str, data: dict[str, Any] | None = None,
             ts: datetime | None = None) -> dict[str, Any]:
        rec = {
            "id": next(self._seq),
            "ts": (ts or self.last_bar_time or now_et()).isoformat(),
            "level": level,
            "event": event,
            "message": message,
            "data": data or {},
        }
        self.events.append(rec)
        getattr(log, "error" if level == "error" else "warning" if level == "warning" else "info")(
            "%s %s %s", event, message, rec["data"])
        for sink in self._sinks:
            sink({"type": "event", "payload": rec})
        return rec

    def _on_fill(self, fill: Fill, realized: float, trade: Trade | None) -> None:
        self.risk.record_realized(realized)
        self.emit("info", "order_filled",
                  f"{fill.role} {fill.side.value} {fill.qty} {fill.symbol} @ {fill.price:.2f}",
                  {"order_id": fill.order_id, "symbol": fill.symbol, "side": fill.side.value, "qty": fill.qty,
                   "price": fill.price, "role": fill.role, "strategy_id": fill.strategy_id,
                   "realized_usd": round(realized, 2)}, ts=fill.timestamp)
        if trade is not None:
            self.emit("info", "trade_closed",
                      f"{trade.strategy_id} {trade.symbol} {trade.side.value} P&L {trade.pnl_usd:.2f} USD",
                      trade.to_dict(), ts=trade.exit_time)
            for sink in self._sinks:
                sink({"type": "trade", "payload": trade.to_dict()})

    # ------------------------------------------------------------- bar loop
    def process_bar(self, bar: Bar) -> list[dict[str, Any]]:
        bar = self._normalized(bar)
        ts = to_et(bar.timestamp)
        if not is_rth(ts):
            return []
        day = session_date(ts)
        if self.current_day is not None and day < self.current_day:
            raise ValueError(f"bar from a past session ({day}) after {self.current_day}")
        if self.current_day != day:
            self._roll_to(day)
        self.bars_processed += 1
        bar_close = ts + timedelta(minutes=1)
        self.last_bar_time = max(self.last_bar_time or bar_close, bar_close)

        if ts.time() >= self.profile.flatten_clock:
            # Flatten at this bar's open (= previous close), then mark EOD. No more entries today.
            self.broker.marks[bar.symbol] = bar.open
            if self.flattened_day != day:
                self.flatten_all("eod_flatten", ts)
            if self.eod_marked_day != day:
                self.mark_eod(day, ts)
            self.tracker.update(bar)
            self.broker.marks[bar.symbol] = bar.close
            return []

        self.tracker.update(bar)
        self.broker.on_bar(bar)
        unreal = self.broker.unrealized()
        breach = self.risk.check_intraday(unreal)
        if breach is not None:
            self.emit("warning", breach,
                      "Pérdida diaria máxima alcanzada: se aplana y se bloquea el día" if breach == "daily_loss_limit"
                      else "Equity tocó el piso del trail: cuenta bloqueada", self.risk.snapshot(unreal), ts=bar_close)
            self.flatten_all(breach, bar_close)

        records: list[dict[str, Any]] = []
        sess = self.tracker.get(bar.symbol)
        ctx = StrategyContext(session=sess, volatility=self.volatility, now=bar_close)
        for strat in self.strategies.values():
            if not strat.enabled or bar.symbol not in strat.symbols:
                continue
            try:
                signals = strat.on_bar(bar, ctx)
            except Exception as exc:  # noqa: BLE001 - surfaced as an explicit error event
                self.emit("error", "strategy_error", f"{strat.strategy_id} failed on {bar.symbol}: {exc!r}",
                          {"strategy_id": strat.strategy_id}, ts=bar_close)
                continue
            for sig in signals:
                records.append(self.handle_signal(sig, sess.context_dict()))
        self._record_equity(bar_close)
        return records

    def _normalized(self, bar: Bar) -> Bar:
        sym = normalize_symbol(bar.symbol)
        if sym == bar.symbol and bar.timestamp.tzinfo is not None:
            return bar
        return Bar(sym, to_et(bar.timestamp), bar.open, bar.high, bar.low, bar.close, bar.volume, bar.timeframe)

    def _roll_to(self, day: date) -> None:
        prev = self.current_day
        if prev is not None and self.eod_marked_day != prev:
            ts = self.last_bar_time or now_et()
            if self.broker.positions:
                self.flatten_all("session_rollover", ts)
            self.mark_eod(prev, ts)
        self.current_day = day
        self.risk.start_day(day)
        self.emit("info", "session_start", f"Sesión {day.isoformat()}", {"day": day.isoformat()})

    # --------------------------------------------------------------- signals
    def handle_signal(self, sig: Signal, session_ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        rec: dict[str, Any] = {
            "id": None, **sig.to_dict(), "status": "rejected", "reason": "", "qty": 0, "order_ids": [],
        }
        try:
            sig.validate()
        except ValueError as exc:
            return self._finish_signal(rec, False, f"invalid_signal: {exc}")
        unreal = self.broker.unrealized()
        decision = self.risk.evaluate_entry(sig, sig.timestamp, self.broker.open_contracts(),
                                            self.broker.open_symbols(), unreal)
        rec["risk"] = decision.details
        if not decision.accepted:
            return self._finish_signal(rec, False, decision.reason)
        if self.profile.claude_filter_enabled:
            ctx = {"signal": sig.to_dict(), "session": session_ctx or {}, "risk": decision.details}
            fd = self.claude_filter.evaluate(ctx)
            rec["claude"] = {"approved": fd.approved, "reason": fd.reason, **fd.details}
            self.emit("info" if fd.approved else "warning", "claude_filter", fd.reason,
                      {"strategy_id": sig.strategy_id, "symbol": sig.symbol, "approved": fd.approved,
                       "transport": fd.transport}, ts=sig.timestamp)
            if not fd.approved:
                return self._finish_signal(rec, False, fd.reason)
        try:
            br = self.broker.submit_bracket(sig.symbol, sig.side, decision.qty, sig.stop, sig.target, sig.timestamp,
                                            strategy_id=sig.strategy_id, entry_price=sig.price)
        except BrokerError as exc:
            self.emit("error", "order_rejected", f"Paper broker rechazó la orden: {exc}",
                      {"strategy_id": sig.strategy_id, "symbol": sig.symbol}, ts=sig.timestamp)
            return self._finish_signal(rec, False, f"broker_error: {exc}")
        self.risk.record_entry()
        rec["qty"] = decision.qty
        rec["order_ids"] = [br.parent.id, br.stop.id, br.target.id]
        return self._finish_signal(rec, True, "ok")

    def _finish_signal(self, rec: dict[str, Any], accepted: bool, reason: str) -> dict[str, Any]:
        rec["id"] = next(self._seq)
        rec["status"] = "accepted" if accepted else "rejected"
        rec["reason"] = reason
        self.signals.append(rec)
        self.emit("info" if accepted else "warning", "signal_accepted" if accepted else "signal_rejected",
                  f"{rec['strategy_id']} {rec['symbol']} {rec['side']} @ {rec['price']:.2f}"
                  + ("" if accepted else f" -> {reason}"),
                  {k: rec[k] for k in ("strategy_id", "symbol", "side", "price", "stop", "target", "qty", "reason")},
                  ts=datetime.fromisoformat(rec["timestamp"]))
        for sink in self._sinks:
            sink({"type": "signal", "payload": rec})
        return rec

    # ---------------------------------------------------------- flatten/EOD
    def flatten_all(self, reason: str, ts: datetime) -> list[Fill]:
        had = {s: p.qty for s, p in self.broker.positions.items()}
        fills = self.broker.flatten(ts, reason)
        day = session_date(ts)
        if reason == "eod_flatten":
            self.flattened_day = day
        self.emit("warning" if had else "info", "flatten",
                  f"Aplanado ({reason}): " + (", ".join(f"{s} x{q}" for s, q in had.items()) or "sin posiciones"),
                  {"reason": reason, "closed": had, "fills": len(fills)}, ts=ts)
        self._record_equity(ts)
        return fills

    def mark_eod(self, day: date, ts: datetime) -> None:
        if self.broker.positions:
            raise RuntimeError("mark_eod requires a flat book; flatten first")
        rec = self.risk.mark_eod(day)
        self.eod_marked_day = day
        self.emit("info", "eod_marked",
                  f"EOD {day.isoformat()}: día {rec.day_pnl:+.2f} USD, saldo {rec.balance:.2f}, "
                  f"pico {rec.peak:.2f}, piso {rec.floor:.2f}" + (" (trail bloqueado)" if rec.locked else ""),
                  rec.to_dict(), ts=ts)
        self._record_equity(ts, eod=True)

    def clock_tick(self, now: datetime) -> bool:
        """Wall-clock driven flatten for live webhook sessions without a 15:55 bar. Returns True if acted."""
        now = to_et(now)
        day = now.date()
        if self.current_day != day or now.time() < self.profile.flatten_clock:
            return False
        acted = False
        if self.flattened_day != day:
            self.flatten_all("eod_flatten", now)
            acted = True
        if self.eod_marked_day != day:
            self.mark_eod(day, now)
            acted = True
        return acted

    def manual_flatten(self, now: datetime | None = None) -> list[Fill]:
        ts = to_et(now) if now else (self.last_bar_time or now_et())
        return self.flatten_all("manual", ts)

    # ------------------------------------------------------------- replay
    def replay(self, bars: Iterable[Bar]) -> ReplayResult:
        n = 0
        for bar in bars:
            self.process_bar(bar)
            n += 1
        sigs = list(self.signals)
        acc = sum(1 for s in sigs if s["status"] == "accepted")
        return ReplayResult(n, len(sigs), acc, len(sigs) - acc, len(self.broker.trades),
                            self.risk.equity(self.broker.unrealized()), self.risk.balance)

    # -------------------------------------------------------------- views
    def _record_equity(self, ts: datetime, eod: bool = False) -> None:
        unreal = self.broker.unrealized()
        point = {"ts": ts.isoformat(), "equity": round(self.risk.equity(unreal), 2),
                 "balance": round(self.risk.balance, 2), "floor": round(self.risk.trail_floor, 2), "eod": eod}
        if self.equity_curve and self.equity_curve[-1]["ts"] == point["ts"] and not self.equity_curve[-1]["eod"]:
            self.equity_curve[-1] = point
        else:
            self.equity_curve.append(point)

    def session_context(self) -> dict[str, Any]:
        out = self.tracker.snapshot()
        sweep = next((s for s in self.strategies.values() if isinstance(s, LiquiditySweepStrategy)), None)
        for sym, ctx in out.items():
            sess = self.tracker.get(sym)
            orb = self.strategies.get("orb")
            rm = getattr(getattr(orb, "params", None), "range_minutes", 15)
            orng = sess.opening_range(rm)
            ctx["orb_minutes"] = rm
            ctx["orb_high"], ctx["orb_low"] = (orng if orng else (None, None))
            ctx["liquidity_levels"] = sweep.liquidity_levels(sess) if sweep and sess.bars else []
        return out

    def account_view(self) -> dict[str, Any]:
        unreal = self.broker.unrealized()
        snap = self.risk.snapshot(unreal)
        snap["open_contracts"] = self.broker.open_contracts()
        snap["flattened_today"] = self.flattened_day == self.current_day and self.current_day is not None
        snap["eod_marked_today"] = self.eod_marked_day == self.current_day and self.current_day is not None
        return snap

    def snapshot(self) -> dict[str, Any]:
        return {
            "account": self.account_view(),
            "positions": self.broker.positions_view(),
            "working_orders": [o.to_dict() for o in self.broker.working_orders()],
            "strategies": [s.describe() for s in self.strategies.values()],
            "signals": list(self.signals)[-100:][::-1],
            "events": list(self.events)[-200:][::-1],
            "trades": [t.to_dict() for t in self.broker.trades][-100:][::-1],
            "equity_curve": self.equity_curve[-2000:],
            "session": self.session_context(),
            "profile": self.profile.to_dict(),
            "volatility_thresholds": self.volatility.describe(),
            "bars_processed": self.bars_processed,
            "last_bar_time": self.last_bar_time.isoformat() if self.last_bar_time else None,
        }
