"""DeskService: owns the TradingEngine, persistence and the live broadcast to dashboards."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from backend.config import Settings
from backend.db import (BarRow, EquityRow, EventRow, KeyValueRow, RiskProfileRow, SignalRow, StrategyConfigRow,
                        TradeRow)
from propdesk.domain.clock import now_et
from propdesk.domain.instruments import CONTRACTS, normalize_symbol
from propdesk.domain.models import Bar
from propdesk.domain.profile import PROFILE_NOTICE_ES, RiskProfile
from propdesk.engine.claude_filter import ClaudeFilter
from propdesk.engine.engine import TradingEngine
from propdesk.feeds.csv_feed import CsvBarFeed
from propdesk.paths import SAMPLE_CSV

log = logging.getLogger("propdesk.backend")

PROFILE_NAME = "eod-trail-50k"


class Broadcaster:
    """Fan-out of small JSON notifications to SSE clients. Thread-safe publish."""

    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[str]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, message: dict[str, Any]) -> None:
        if self._loop is None or not self._queues:
            return
        data = json.dumps(message, default=str)
        for q in list(self._queues):
            self._loop.call_soon_threadsafe(_put_nowait, q, data)

    async def subscribe(self) -> AsyncIterator[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=500)
        self._queues.add(q)
        try:
            while True:
                try:
                    yield await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield json.dumps({"type": "ping"})
        finally:
            self._queues.discard(q)


def _put_nowait(q: asyncio.Queue[str], data: str) -> None:
    try:
        q.put_nowait(data)
    except asyncio.QueueFull:  # slow client: drop, it re-syncs on the next "refresh"
        pass


class DeskService:
    def __init__(self, settings: Settings, session_factory: sessionmaker) -> None:
        self.settings = settings
        self.Session = session_factory
        self.lock = threading.RLock()
        self.broadcaster = Broadcaster()
        self._muted = False
        self._pending_signals: list[dict[str, Any]] = []
        self._pending_events: list[dict[str, Any]] = []
        self._pending_trades: list[dict[str, Any]] = []
        self._persisted_equity = 0
        profile = self._load_profile()
        self.engine = TradingEngine(profile=profile, claude_filter=self._make_filter())
        self._load_strategy_configs()
        self._load_account_state()
        self.engine.add_sink(self._sink)
        self.engine.emit("info", "engine_started",
                         "Motor paper iniciado. Tradovate e IB apagados: ninguna orden sale del proceso.",
                         {"tradovate_enabled_flag": settings.tradovate_enabled, "ib_enabled_flag": settings.ib_enabled})
        self.flush()

    # ---------------------------------------------------------------- loading
    def _make_filter(self) -> ClaudeFilter:
        return ClaudeFilter(api_key=self.settings.anthropic_api_key, model=self.settings.claude_model,
                            timeout_s=self.settings.claude_timeout_s, transport=self.settings.claude_transport)

    def _load_profile(self) -> RiskProfile:
        with self.Session() as s:
            row = s.get(RiskProfileRow, PROFILE_NAME)
            if row is None:
                prof = RiskProfile()
                s.add(RiskProfileRow(name=PROFILE_NAME, data=prof.to_dict()))
                s.commit()
                return prof
            return RiskProfile.from_dict(row.data)

    def _load_strategy_configs(self) -> None:
        with self.Session() as s:
            for sid, strat in self.engine.strategies.items():
                row = s.get(StrategyConfigRow, sid)
                if row is None:
                    s.add(StrategyConfigRow(strategy_id=sid, enabled=strat.enabled, symbols=sorted(strat.symbols),
                                            params=strat.describe()["params"]))
                    continue
                strat.enabled = row.enabled
                strat.symbols = set(row.symbols)
                try:
                    strat.update_params(row.params)
                except ValueError as exc:
                    log.error("stored params for %s are invalid, keeping defaults: %s", sid, exc)
            s.commit()

    def _load_account_state(self) -> None:
        with self.Session() as s:
            row = s.get(KeyValueRow, "account")
            if row is not None:
                self.engine.risk.load_state(row.data)
            self.engine.equity_curve = [
                {"ts": r.ts, "equity": r.equity, "balance": r.balance, "floor": r.floor, "eod": r.eod}
                for r in s.scalars(select(EquityRow).order_by(EquityRow.id.desc()).limit(2000)).all()[::-1]
            ]
            self._persisted_equity = len(self.engine.equity_curve)
            for r in s.scalars(select(SignalRow).order_by(SignalRow.id.desc()).limit(200)).all()[::-1]:
                self.engine.signals.append(r.data)
            for r in s.scalars(select(EventRow).order_by(EventRow.id.desc()).limit(300)).all()[::-1]:
                self.engine.events.append({"id": r.id, "ts": r.ts, "level": r.level, "event": r.event,
                                           "message": r.message, "data": r.data})

    # ------------------------------------------------------------ persistence
    def _sink(self, msg: dict[str, Any]) -> None:
        kind, payload = msg["type"], msg["payload"]
        if kind == "event":
            self._pending_events.append(payload)
        elif kind == "signal":
            self._pending_signals.append(payload)
        elif kind == "trade":
            self._pending_trades.append(payload)
        if not self._muted:
            self.broadcaster.publish(msg)

    def flush(self) -> None:
        with self.Session() as s:
            s.add_all(EventRow(ts=e["ts"], level=e["level"], event=e["event"], message=e["message"],
                               data=e["data"]) for e in self._pending_events)
            s.add_all(SignalRow(ts=x["timestamp"], strategy_id=x["strategy_id"], symbol=x["symbol"], side=x["side"],
                                price=x["price"], stop=x["stop"], target=x["target"], status=x["status"],
                                reason=x["reason"], qty=x["qty"], data=x) for x in self._pending_signals)
            s.add_all(TradeRow(exit_time=t["exit_time"], strategy_id=t["strategy_id"], symbol=t["symbol"],
                               pnl_usd=t["pnl_usd"], data=t) for t in self._pending_trades)
            curve = self.engine.equity_curve
            if self._persisted_equity > len(curve):
                self._persisted_equity = 0
            s.add_all(EquityRow(ts=p["ts"], equity=p["equity"], balance=p["balance"], floor=p["floor"], eod=p["eod"])
                      for p in curve[self._persisted_equity:])
            self._persisted_equity = len(curve)
            self._put_kv(s, "account", self.engine.risk.to_state())
            snap = self.engine.snapshot()
            self._put_kv(s, "state", {"account": snap["account"], "positions": snap["positions"],
                                      "session": snap["session"], "profile": snap["profile"],
                                      "updated_at": now_et().isoformat()})
            s.commit()
        self._pending_events.clear()
        self._pending_signals.clear()
        self._pending_trades.clear()

    @staticmethod
    def _put_kv(s: Session, key: str, data: dict[str, Any]) -> None:
        row = s.get(KeyValueRow, key)
        if row is None:
            s.add(KeyValueRow(key=key, data=data))
        else:
            row.data = data

    # ----------------------------------------------------------------- bars
    def ingest_bar(self, bar: Bar, source: str = "webhook") -> list[dict[str, Any]]:
        with self.lock:
            records = self.engine.process_bar(bar)
            with self.Session() as s:
                s.add(BarRow(symbol=normalize_symbol(bar.symbol), ts=bar.timestamp.isoformat(), open=bar.open,
                             high=bar.high, low=bar.low, close=bar.close, volume=bar.volume, source=source))
                s.commit()
            self.flush()
        self.broadcaster.publish({"type": "refresh"})
        return records

    def replay_sample(self) -> dict[str, Any]:
        """Reset the paper account and replay the sample CSV. Live broadcast muted during the run."""
        bars = CsvBarFeed(SAMPLE_CSV).load()
        with self.lock:
            self._clear_tables()
            self.engine.reset_account(self.engine.profile)
            self._persisted_equity = 0
            self._muted = True
            try:
                self.engine.emit("info", "replay_started", f"Reproduciendo {SAMPLE_CSV.name} ({len(bars)} barras). "
                                 "Cuenta paper reiniciada. Datos sintéticos, no grabación del CME.")
                result = self.engine.replay(bars)
                self.engine.emit("info", "replay_finished",
                                 f"Replay terminado: {result.signals} señales, {result.accepted} aceptadas, "
                                 f"{result.trades} operaciones, equity {result.equity:.2f} USD",
                                 {"bars": result.bars, "signals": result.signals, "accepted": result.accepted,
                                  "trades": result.trades, "equity": round(result.equity, 2)})
            finally:
                self._muted = False
            with self.Session() as s:
                s.add_all(BarRow(symbol=b.symbol, ts=b.timestamp.isoformat(), open=b.open, high=b.high, low=b.low,
                                 close=b.close, volume=b.volume, source="replay") for b in bars)
                s.commit()
            self.flush()
        self.broadcaster.publish({"type": "refresh"})
        return {"bars": result.bars, "signals": result.signals, "accepted": result.accepted,
                "rejected": result.rejected, "trades": result.trades, "equity": round(result.equity, 2),
                "balance": round(result.balance, 2)}

    def reset_simulation(self) -> dict[str, Any]:
        with self.lock:
            self._clear_tables()
            self.engine.reset_account(self.engine.profile)
            self._persisted_equity = 0
            self.engine.emit("info", "sim_reset",
                             f"Simulación reiniciada con saldo {self.engine.profile.starting_balance:.2f} USD")
            self.flush()
        self.broadcaster.publish({"type": "refresh"})
        return self.engine.account_view()

    def _clear_tables(self) -> None:
        with self.Session() as s:
            for model in (SignalRow, EventRow, TradeRow, EquityRow, BarRow):
                s.execute(delete(model))
            s.execute(delete(KeyValueRow).where(KeyValueRow.key == "account"))
            s.commit()
        self._pending_events.clear()
        self._pending_signals.clear()
        self._pending_trades.clear()

    def manual_flatten(self) -> dict[str, Any]:
        with self.lock:
            fills = self.engine.manual_flatten()
            self.flush()
        self.broadcaster.publish({"type": "refresh"})
        return {"fills": len(fills), "positions": self.engine.broker.positions_view()}

    def clock_tick(self, now: datetime | None = None) -> bool:
        with self.lock:
            acted = self.engine.clock_tick(now or now_et())
            if acted:
                self.flush()
        if acted:
            self.broadcaster.publish({"type": "refresh"})
        return acted

    # ------------------------------------------------------------- settings
    def update_strategy(self, sid: str, enabled: bool | None, symbols: list[str] | None,
                        params: dict[str, Any] | None) -> dict[str, Any]:
        with self.lock:
            strat = self.engine.strategies.get(sid)
            if strat is None:
                raise KeyError(sid)
            new_symbols = None
            if symbols is not None:
                new_symbols = {normalize_symbol(x) for x in symbols}
                bad = new_symbols - set(CONTRACTS)
                if bad:
                    raise ValueError(f"unsupported symbols {sorted(bad)}")
            if params:
                strat.update_params(params)  # raises ValueError, nothing applied on error
            if enabled is not None:
                strat.enabled = enabled
            if new_symbols is not None:
                strat.symbols = new_symbols
            with self.Session() as s:
                row = s.get(StrategyConfigRow, sid)
                desc = strat.describe()
                if row is None:
                    s.add(StrategyConfigRow(strategy_id=sid, enabled=strat.enabled, symbols=desc["symbols"],
                                            params=desc["params"]))
                else:
                    row.enabled, row.symbols, row.params = strat.enabled, desc["symbols"], desc["params"]
                s.commit()
            self.engine.emit("info", "strategy_updated",
                             f"{sid}: {'activa' if strat.enabled else 'apagada'} en {', '.join(desc['symbols']) or '-'}",
                             {"strategy_id": sid, "enabled": strat.enabled, "symbols": desc["symbols"],
                              "params": desc["params"]})
            self.flush()
        self.broadcaster.publish({"type": "refresh"})
        return desc

    def update_profile(self, changes: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            prof = self.engine.profile.updated(changes)  # raises ValueError
            self.engine.update_profile(prof)
            with self.Session() as s:
                row = s.get(RiskProfileRow, PROFILE_NAME)
                if row is None:
                    s.add(RiskProfileRow(name=PROFILE_NAME, data=prof.to_dict()))
                else:
                    row.data = prof.to_dict()
                s.commit()
            self.flush()
        self.broadcaster.publish({"type": "refresh"})
        return prof.to_dict()

    # ---------------------------------------------------------------- views
    def meta(self) -> dict[str, Any]:
        return {
            "mode": "paper",
            "tradovate_enabled": self.settings.tradovate_enabled,
            "ib_enabled": self.settings.ib_enabled,
            "live_routing": False,
            "notice": PROFILE_NOTICE_ES,
            "claude_key_present": bool(self.settings.anthropic_api_key),
            "claude_transport": self.settings.claude_transport,
            "claude_model": self.settings.claude_model,
            "sample_csv": SAMPLE_CSV.name,
        }

    def state(self) -> dict[str, Any]:
        with self.lock:
            snap = self.engine.snapshot()
        snap["meta"] = self.meta()
        return snap

    def recent_bars(self, symbol: str, limit: int) -> list[dict[str, Any]]:
        sym = normalize_symbol(symbol)
        with self.Session() as s:
            rows = s.scalars(select(BarRow).where(BarRow.symbol == sym).order_by(BarRow.id.desc()).limit(limit)).all()
        return [{"timestamp": r.ts, "open": r.open, "high": r.high, "low": r.low, "close": r.close,
                 "volume": r.volume, "source": r.source} for r in rows[::-1]]
