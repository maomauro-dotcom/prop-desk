"""MCP tool implementations. They read the running backend (HTTP) or, failing that, its SQLite file.

Configuration (environment):
  PROPDESK_API_URL   e.g. http://localhost:8000  (uses DASHBOARD_TOKEN as Bearer)
  DASHBOARD_TOKEN    token for the backend API
  DATABASE_URL       sqlite:///./propdesk.db  (same as the backend; read-only access)

Nothing here fabricates data: if neither source is reachable the tool raises ToolError.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from propdesk.domain.instruments import normalize_symbol
from propdesk.engine.claude_prompt import (EXAMPLE_PROMPT, EXAMPLE_SIGNAL_CONTEXT, SYSTEM_PROMPT, ClaudeCallError,
                                           build_prompt, call_claude)


class ToolError(RuntimeError):
    pass


def _sqlite_path() -> Path | None:
    url = os.environ.get("DATABASE_URL", "sqlite:///./propdesk.db")
    if not url.startswith("sqlite:///"):
        return None
    p = Path(url[len("sqlite:///"):])
    return p if p.exists() else None


class StateSource:
    def __init__(self) -> None:
        self.api_url = os.environ.get("PROPDESK_API_URL", "").rstrip("/")
        self.token = os.environ.get("DASHBOARD_TOKEN", "")

    # -- HTTP
    def _api(self, path: str) -> Any:
        import httpx

        r = httpx.get(f"{self.api_url}{path}", headers={"Authorization": f"Bearer {self.token}"}, timeout=5.0)
        if r.status_code != 200:
            raise ToolError(f"backend {path} -> HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    # -- SQLite
    def _db(self) -> sqlite3.Connection:
        p = _sqlite_path()
        if p is None:
            raise ToolError("no backend reachable (PROPDESK_API_URL) and no SQLite file found (DATABASE_URL)")
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def state(self) -> tuple[dict[str, Any], str, str | None]:
        api_error = None
        if self.api_url:
            try:
                return self._api("/api/state"), "api", None
            except Exception as exc:  # noqa: BLE001 - reported to the caller
                api_error = str(exc)
        try:
            conn = self._db()
        except ToolError as exc:
            raise ToolError(f"{exc}" + (f"; api error: {api_error}" if api_error else "")) from None
        with conn:
            row = conn.execute("SELECT data FROM kv WHERE key = 'state'").fetchone()
        if row is None:
            raise ToolError("SQLite has no engine snapshot yet (start the backend or run a replay)"
                            + (f"; api error: {api_error}" if api_error else ""))
        return json.loads(row["data"]), "sqlite", api_error

    def bars(self, symbol: str, limit: int) -> tuple[list[dict[str, Any]], str]:
        if self.api_url:
            try:
                return self._api(f"/api/bars/{symbol}?limit={limit}"), "api"
            except Exception:  # noqa: BLE001 - fall back to SQLite below
                pass
        with self._db() as conn:
            rows = conn.execute("SELECT ts, open, high, low, close, volume, source FROM bars WHERE symbol = ? "
                                "ORDER BY id DESC LIMIT ?", (symbol, limit)).fetchall()
        return [{"timestamp": r["ts"], "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"],
                 "volume": r["volume"], "source": r["source"]} for r in rows[::-1]], "sqlite"


def _sym(symbol: str) -> str:
    try:
        return normalize_symbol(symbol)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


def _session(state: dict[str, Any], sym: str) -> dict[str, Any]:
    sess = (state.get("session") or {}).get(sym)
    if not sess:
        raise ToolError(f"no session data for {sym} yet")
    return sess


def get_current_market_state(symbol: str) -> dict[str, Any]:
    sym = _sym(symbol)
    src = StateSource()
    state, source, api_error = src.state()
    sess = _session(state, sym)
    positions = [p for p in state.get("positions", []) if p.get("symbol") == sym]
    acc = state.get("account", {})
    return {"symbol": sym, "source": source, "api_error": api_error, "session": sess, "positions": positions,
            "account": {k: acc.get(k) for k in ("equity", "day_pnl", "cushion_usd", "trail_floor", "can_open")}}


def get_vwap_and_orb(symbol: str) -> dict[str, Any]:
    sym = _sym(symbol)
    state, source, _ = StateSource().state()
    s = _session(state, sym)
    return {"symbol": sym, "source": source, "day": s.get("day"), "last_time": s.get("last_time"),
            "vwap": s.get("vwap"), "vwap_upper_2sd": s.get("vwap_upper_2sd"), "vwap_lower_2sd": s.get("vwap_lower_2sd"),
            "orb_minutes": s.get("orb_minutes"), "orb_high": s.get("orb_high"), "orb_low": s.get("orb_low"),
            "atr": s.get("atr")}


def get_risk_status() -> dict[str, Any]:
    state, source, api_error = StateSource().state()
    return {"source": source, "api_error": api_error, "account": state.get("account"), "profile": state.get("profile"),
            "notice": "Simulated numbers chosen for practice, not Apex's published rules. Live routing is off."}


def get_recent_bars(symbol: str, limit: int = 30) -> dict[str, Any]:
    sym = _sym(symbol)
    limit = max(1, min(int(limit), 500))
    bars, source = StateSource().bars(sym, limit)
    return {"symbol": sym, "source": source, "count": len(bars), "bars": bars}


def get_liquidity_levels(symbol: str) -> dict[str, Any]:
    sym = _sym(symbol)
    state, source, _ = StateSource().state()
    s = _session(state, sym)
    return {"symbol": sym, "source": source, "prev_day_high": s.get("prev_day_high"),
            "prev_day_low": s.get("prev_day_low"), "orb_high": s.get("orb_high"), "orb_low": s.get("orb_low"),
            "day_high": s.get("day_high"), "day_low": s.get("day_low"),
            "live_levels": s.get("liquidity_levels", []), "last_sweep": s.get("last_sweep")}


def analyze_setup(signal_context: dict[str, Any] | None = None, call_model: bool = False) -> dict[str, Any]:
    """Build the review prompt for a setup; optionally send it to Claude (requires ANTHROPIC_API_KEY).

    With call_model=false it only returns the prompt (no network). With call_model=true any failure
    raises ToolError, so callers fail closed.
    """
    ctx = signal_context or EXAMPLE_SIGNAL_CONTEXT
    out: dict[str, Any] = {"system": SYSTEM_PROMPT, "prompt": build_prompt(ctx), "example_prompt": EXAMPLE_PROMPT,
                           "used_example_context": signal_context is None}
    if call_model:
        try:
            v = call_claude(ctx, timeout_s=float(os.environ.get("CLAUDE_TIMEOUT_S", "15") or 15))
        except ClaudeCallError as exc:
            raise ToolError(f"Claude call failed (fail closed): {exc}") from exc
        out["verdict"] = {"decision": v.decision, "confidence": v.confidence, "reason": v.reason, "model": v.model}
    return out


TOOLS: dict[str, dict[str, Any]] = {
    "get_current_market_state": {
        "fn": get_current_market_state,
        "description": "Session context (VWAP, ORB, ATR, levels, last sweep), open position and account summary for a symbol.",
        "schema": {"type": "object", "properties": {"symbol": {"type": "string", "description": "MNQ or MES"}},
                   "required": ["symbol"]},
    },
    "get_vwap_and_orb": {
        "fn": get_vwap_and_orb,
        "description": "RTH VWAP anchored 09:30 ET with 2-sigma bands and the opening range for a symbol.",
        "schema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]},
    },
    "analyze_setup": {
        "fn": analyze_setup,
        "description": "Build the Claude review prompt for a candidate setup (signal, session, risk). "
                       "Set call_model=true to get an approve/reject verdict; errors mean reject.",
        "schema": {"type": "object", "properties": {
            "signal_context": {"type": "object", "description": "{signal, session, risk}; omit to get the example"},
            "call_model": {"type": "boolean", "default": False}}},
    },
    "get_risk_status": {
        "fn": get_risk_status,
        "description": "Paper account: balance, equity, EOD trail floor, cushion, lock state, daily limits.",
        "schema": {"type": "object", "properties": {}},
    },
    "get_recent_bars": {
        "fn": get_recent_bars,
        "description": "Most recent 1-minute bars stored by the backend for a symbol.",
        "schema": {"type": "object", "properties": {"symbol": {"type": "string"},
                                                     "limit": {"type": "integer", "default": 30}},
                   "required": ["symbol"]},
    },
    "get_liquidity_levels": {
        "fn": get_liquidity_levels,
        "description": "Previous-day high/low, opening range, live swing levels and the last sweep for a symbol.",
        "schema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]},
    },
}
