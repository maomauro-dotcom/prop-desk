"""Risk manager: owns sizing, daily P&L, the simulated EOD trail, cushion, lock and flatten rules.

Trail model (EOD trailing drawdown, simulated):
  * floor = min(peak_eod_balance - trail_amount, trail_lock_level)
  * The peak only moves when the day is marked EOD (after the forced flatten).
  * Once peak - trail reaches the lock level (starting balance by default) the floor stops moving.
  * Cushion = current equity (closed balance + realized today + open P&L) - floor.

Entry gates (all must pass):
  * minis blocked, account not breached, before the flatten cut-off, day not locked
  * day P&L above -daily_loss_limit, entries today < max_entries_per_day
  * one position per symbol, total open contracts < max_contracts (hard cap 2 micros)
  * cushion >= min_cushion_pct_of_trail * trail_amount (800 USD with a 2000 trail)
  * risk per trade <= max_risk_pct_of_cushion * cushion (15%) and <= the daily loss still available
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from propdesk.domain.clock import to_et
from propdesk.domain.instruments import CONTRACTS, MINIS, normalize_symbol
from propdesk.domain.models import Signal
from propdesk.domain.profile import RiskProfile

HARD_MAX_CONTRACTS = 2


@dataclass(slots=True)
class RiskDecision:
    accepted: bool
    qty: int
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EodRecord:
    day: date
    day_pnl: float
    balance: float
    peak: float
    floor: float
    locked: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "day": self.day.isoformat(),
            "day_pnl": round(self.day_pnl, 2),
            "balance": round(self.balance, 2),
            "peak": round(self.peak, 2),
            "floor": round(self.floor, 2),
            "locked": self.locked,
        }


class RiskManager:
    def __init__(self, profile: RiskProfile) -> None:
        profile.validate()
        self.profile = profile
        self.reset()

    # ------------------------------------------------------------------ state
    def reset(self, profile: RiskProfile | None = None) -> None:
        if profile is not None:
            profile.validate()
            self.profile = profile
        self.balance: float = self.profile.starting_balance
        self.peak_eod_balance: float = self.profile.starting_balance
        self.day_realized: float = 0.0
        self.entries_today: int = 0
        self.current_day: date | None = None
        self.day_lock_reason: str | None = None
        self.breached: bool = False
        self.eod_history: list[EodRecord] = []

    def update_profile(self, profile: RiskProfile) -> None:
        """Limits apply immediately. starting_balance only takes effect on reset()."""
        profile.validate()
        self.profile = profile

    # ---------------------------------------------------------------- derived
    @property
    def trail_floor(self) -> float:
        return min(self.peak_eod_balance - self.profile.trail_amount, self.profile.trail_lock_level)

    @property
    def trail_locked(self) -> bool:
        return self.peak_eod_balance - self.profile.trail_amount >= self.profile.trail_lock_level

    def equity(self, unrealized: float = 0.0) -> float:
        return self.balance + self.day_realized + unrealized

    def day_pnl(self, unrealized: float = 0.0) -> float:
        return self.day_realized + unrealized

    def cushion(self, unrealized: float = 0.0) -> float:
        return self.equity(unrealized) - self.trail_floor

    # -------------------------------------------------------------- lifecycle
    def start_day(self, day: date) -> None:
        if self.current_day == day:
            return
        if self.current_day is not None and self.current_day > day:
            raise ValueError(f"session date went backwards: {self.current_day} -> {day}")
        self.current_day = day
        self.day_realized = 0.0
        self.entries_today = 0
        self.day_lock_reason = None

    def record_entry(self) -> None:
        self.entries_today += 1

    def record_realized(self, pnl_usd: float) -> None:
        self.day_realized += pnl_usd

    def check_intraday(self, unrealized: float) -> str | None:
        """Return a reason string when the open book must be flattened now."""
        if self.equity(unrealized) <= self.trail_floor and not self.breached:
            self.breached = True
            self.day_lock_reason = "account_breached"
            return "account_breached"
        if self.day_pnl(unrealized) <= -self.profile.daily_loss_limit and self.day_lock_reason is None:
            self.day_lock_reason = "daily_loss_limit"
            return "daily_loss_limit"
        return None

    def mark_eod(self, day: date) -> EodRecord:
        """Close the day: P&L moves into the balance, counters reset, trail follows a new peak."""
        if self.current_day is not None and day != self.current_day:
            raise ValueError(f"mark_eod for {day} but current session is {self.current_day}")
        day_pnl = self.day_realized
        self.balance += day_pnl
        if self.balance > self.peak_eod_balance:
            self.peak_eod_balance = self.balance
        if self.balance <= self.trail_floor:
            self.breached = True
        rec = EodRecord(day, day_pnl, self.balance, self.peak_eod_balance, self.trail_floor, self.trail_locked)
        self.eod_history.append(rec)
        self.day_realized = 0.0
        self.entries_today = 0
        self.day_lock_reason = None
        return rec

    # ---------------------------------------------------------------- sizing
    def evaluate_entry(
        self,
        signal: Signal,
        now: datetime,
        open_contracts: int,
        open_symbols: set[str],
        unrealized: float = 0.0,
    ) -> RiskDecision:
        p = self.profile
        try:
            symbol = normalize_symbol(signal.symbol)
        except ValueError as exc:
            return RiskDecision(False, 0, "unknown_symbol", {"error": str(exc)})
        cushion = self.cushion(unrealized)
        details: dict[str, Any] = {
            "cushion_usd": round(cushion, 2),
            "trail_floor": round(self.trail_floor, 2),
            "day_pnl": round(self.day_pnl(unrealized), 2),
            "entries_today": self.entries_today,
        }

        def reject(reason: str, **extra: Any) -> RiskDecision:
            return RiskDecision(False, 0, reason, {**details, **extra})

        if p.block_minis and symbol in MINIS:
            return reject("mini_blocked")
        if not CONTRACTS[symbol].is_micro:
            return reject("mini_blocked")
        if self.breached:
            return reject("account_breached")
        if to_et(now).time() >= p.flatten_clock:
            return reject("after_flatten_cutoff")
        if self.day_lock_reason is not None:
            return reject(f"day_locked:{self.day_lock_reason}")
        if self.day_pnl(unrealized) <= -p.daily_loss_limit:
            return reject("daily_loss_limit")
        if self.entries_today >= p.max_entries_per_day:
            return reject("max_entries_per_day")
        if symbol in open_symbols:
            return reject("position_open_on_symbol")
        max_contracts = min(p.max_contracts, HARD_MAX_CONTRACTS)
        if open_contracts >= max_contracts:
            return reject("max_contracts")
        if cushion < p.min_cushion_usd:
            return reject("cushion_below_floor", min_cushion_usd=round(p.min_cushion_usd, 2))

        risk_per_contract = signal.risk_points * CONTRACTS[symbol].point_value
        if risk_per_contract <= 0:
            return reject("invalid_stop")
        cap_cushion = p.max_risk_pct_of_cushion * cushion
        cap_daily = p.daily_loss_limit + self.day_pnl(unrealized)
        max_risk = min(cap_cushion, cap_daily)
        by_risk = math.floor(max_risk / risk_per_contract + 1e-9)
        qty = min(p.default_contracts, max_contracts - open_contracts, by_risk)
        details.update(
            risk_per_contract_usd=round(risk_per_contract, 2),
            max_risk_usd=round(max_risk, 2),
            risk_cap_cushion_usd=round(cap_cushion, 2),
            risk_cap_daily_usd=round(cap_daily, 2),
        )
        if qty < 1:
            return reject("risk_exceeds_cushion_cap")
        details["risk_usd"] = round(qty * risk_per_contract, 2)
        return RiskDecision(True, qty, "ok", details)

    # -------------------------------------------------------------- snapshot
    def snapshot(self, unrealized: float = 0.0) -> dict[str, Any]:
        p = self.profile
        cushion = self.cushion(unrealized)
        return {
            "profile": p.name,
            "balance": round(self.balance, 2),
            "equity": round(self.equity(unrealized), 2),
            "day_realized": round(self.day_realized, 2),
            "day_pnl": round(self.day_pnl(unrealized), 2),
            "unrealized": round(unrealized, 2),
            "peak_eod_balance": round(self.peak_eod_balance, 2),
            "trail_floor": round(self.trail_floor, 2),
            "trail_locked": self.trail_locked,
            "trail_status": "bloqueado" if self.trail_locked else "sigue al pico",
            "cushion_usd": round(cushion, 2),
            "cushion_pct": round(100.0 * cushion / p.trail_amount, 2),
            "cushion_floor_usd": round(p.min_cushion_usd, 2),
            "max_risk_per_trade_usd": round(max(0.0, p.max_risk_pct_of_cushion * cushion), 2),
            "entries_today": self.entries_today,
            "max_entries_per_day": p.max_entries_per_day,
            "daily_loss_limit": p.daily_loss_limit,
            "day_lock_reason": self.day_lock_reason,
            "breached": self.breached,
            "can_open": (not self.breached and self.day_lock_reason is None and cushion >= p.min_cushion_usd
                         and self.entries_today < p.max_entries_per_day),
            "current_day": self.current_day.isoformat() if self.current_day else None,
            "eod_history": [r.to_dict() for r in self.eod_history[-30:]],
        }

    def to_state(self) -> dict[str, Any]:
        return {
            "balance": self.balance,
            "peak_eod_balance": self.peak_eod_balance,
            "breached": self.breached,
            "eod_history": [r.to_dict() for r in self.eod_history],
        }

    def load_state(self, state: dict[str, Any]) -> None:
        self.balance = float(state["balance"])
        self.peak_eod_balance = float(state["peak_eod_balance"])
        self.breached = bool(state.get("breached", False))
        self.eod_history = [
            EodRecord(date.fromisoformat(r["day"]), r["day_pnl"], r["balance"], r["peak"], r["floor"], r["locked"])
            for r in state.get("eod_history", [])
        ]
