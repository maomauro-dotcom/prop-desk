"""Risk profile used by the simulator.

IMPORTANT: the default numbers are the ones chosen for PRACTICE, not Apex's published
rules. A public 50k EOD trail is usually 2500, not 2000. Paste the real numbers of your
account through the dashboard; nothing here changes them silently.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import time
from typing import Any

PROFILE_NOTICE_ES = (
    "Estos números son los elegidos para la simulación, no las reglas publicadas de Apex. "
    "Un trail de una cuenta de 50k suele ser 2500. El enrutado en vivo sigue apagado."
)


@dataclass(slots=True)
class RiskProfile:
    name: str = "eod-trail-50k"
    starting_balance: float = 50_000.0
    trail_amount: float = 2_000.0
    # The trail floor stops rising once it reaches this level (defaults to starting balance).
    trail_lock_level: float = 50_000.0
    daily_loss_limit: float = 500.0
    default_contracts: int = 1
    max_contracts: int = 2
    block_minis: bool = True
    consistency_rule: bool = False
    flatten_time: str = "15:55"
    allow_overnight: bool = False
    max_risk_pct_of_cushion: float = 0.15
    min_cushion_pct_of_trail: float = 0.40
    max_entries_per_day: int = 4
    claude_filter_enabled: bool = False

    def validate(self) -> None:
        errors: list[str] = []
        if self.starting_balance <= 0:
            errors.append("starting_balance must be > 0")
        if self.trail_amount <= 0:
            errors.append("trail_amount must be > 0")
        if self.trail_lock_level <= 0:
            errors.append("trail_lock_level must be > 0")
        if self.daily_loss_limit <= 0:
            errors.append("daily_loss_limit must be > 0")
        if not (1 <= self.default_contracts <= self.max_contracts):
            errors.append("default_contracts must be between 1 and max_contracts")
        if not (1 <= self.max_contracts <= 2):
            errors.append("max_contracts is hard-capped at 2 micros")
        if not (0 < self.max_risk_pct_of_cushion <= 1):
            errors.append("max_risk_pct_of_cushion must be in (0, 1]")
        if not (0 <= self.min_cushion_pct_of_trail <= 1):
            errors.append("min_cushion_pct_of_trail must be in [0, 1]")
        if self.max_entries_per_day < 0:
            errors.append("max_entries_per_day must be >= 0")
        if not self.block_minis:
            errors.append("minis (NQ/ES) stay blocked in this version: only MNQ/MES micros are allowed")
        if self.consistency_rule:
            errors.append("consistency rule is not part of this profile")
        if self.allow_overnight:
            errors.append("overnight holding is not supported by this simulator")
        try:
            t = self.flatten_clock
            if not (time(9, 30) < t <= time(16, 0)):
                errors.append("flatten_time must be within RTH (09:30-16:00 ET)")
        except ValueError:
            errors.append("flatten_time must be HH:MM")
        if errors:
            raise ValueError("; ".join(errors))

    @property
    def flatten_clock(self) -> time:
        hh, mm = self.flatten_time.split(":")
        return time(int(hh), int(mm))

    @property
    def min_cushion_usd(self) -> float:
        return self.min_cushion_pct_of_trail * self.trail_amount

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RiskProfile":
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown profile fields: {sorted(unknown)}")
        prof = cls(**data)
        prof.validate()
        return prof

    def updated(self, changes: dict[str, Any]) -> "RiskProfile":
        merged = self.to_dict()
        merged.update(changes)
        return RiskProfile.from_dict(merged)
