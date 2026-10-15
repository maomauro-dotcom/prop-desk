"""Volatility filter shared by every strategy.

Thresholds are on ATR(14) of 1-minute bars, in index points:

| Symbol    | Dead session (ATR <) | Extreme (ATR >) | Spike bar (range > k*ATR) |
|-----------|----------------------|-----------------|---------------------------|
| MNQ / NQ  | 4.0                  | 60.0            | 4.0 x ATR                 |
| MES / ES  | 1.0                  | 15.0            | 4.0 x ATR                 |

Rationale: a normal NQ RTH minute moves ~8-20 points (ES ~2-4). Below the dead threshold
stops are inside the noise of the spread and fills are unrealistic; above the extreme
threshold (news, halts, CPI/FOMC minutes) the simulator's fill model is no longer credible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from propdesk.domain.models import Bar


@dataclass(frozen=True, slots=True)
class VolThreshold:
    min_atr: float
    max_atr: float
    spike_mult: float = 4.0


DEFAULT_THRESHOLDS: dict[str, VolThreshold] = {
    "MNQ": VolThreshold(4.0, 60.0),
    "NQ": VolThreshold(4.0, 60.0),
    "MES": VolThreshold(1.0, 15.0),
    "ES": VolThreshold(1.0, 15.0),
}


@dataclass
class VolatilityFilter:
    thresholds: dict[str, VolThreshold] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))

    def check(self, bar: Bar, atr: float | None) -> tuple[bool, str]:
        th = self.thresholds.get(bar.symbol)
        if th is None:
            return False, f"no volatility thresholds for {bar.symbol}"
        if atr is None:
            return False, "atr_unavailable"
        if atr < th.min_atr:
            return False, f"dead_session atr={atr:.2f}<{th.min_atr}"
        if atr > th.max_atr:
            return False, f"atr_extreme atr={atr:.2f}>{th.max_atr}"
        if bar.range > th.spike_mult * atr:
            return False, f"spike_bar range={bar.range:.2f}>{th.spike_mult}xATR"
        return True, "ok"

    def describe(self) -> dict[str, Any]:
        return {k: {"min_atr": v.min_atr, "max_atr": v.max_atr, "spike_mult": v.spike_mult}
                for k, v in self.thresholds.items()}
