"""CME equity index contract specs and symbol normalization."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContractSpec:
    root: str
    point_value: float  # USD per 1.0 index point per contract
    tick_size: float
    is_micro: bool
    description: str

    @property
    def tick_value(self) -> float:
        return self.point_value * self.tick_size


CONTRACTS: dict[str, ContractSpec] = {
    "MNQ": ContractSpec("MNQ", 2.0, 0.25, True, "Micro E-mini Nasdaq-100"),
    "MES": ContractSpec("MES", 5.0, 0.25, True, "Micro E-mini S&P 500"),
    "NQ": ContractSpec("NQ", 20.0, 0.25, False, "E-mini Nasdaq-100"),
    "ES": ContractSpec("ES", 50.0, 0.25, False, "E-mini S&P 500"),
}

MICROS: tuple[str, ...] = ("MNQ", "MES")
MINIS: tuple[str, ...] = ("NQ", "ES")

# Longest roots first so "MNQ" is not mistaken for "NQ".
_ROOTS_BY_LEN = sorted(CONTRACTS, key=len, reverse=True)
_MONTH_CODE = re.compile(r"[FGHJKMNQUVXZ]\d{1,4}")


class UnknownSymbolError(ValueError):
    pass


def normalize_symbol(raw: str) -> str:
    """Map TradingView/Tradovate style tickers to a contract root.

    Examples: "CME_MINI:MNQ1!" -> "MNQ", "MNQZ2026" -> "MNQ", "MESZ6" -> "MES", "es" -> "ES".
    """
    if not raw or not raw.strip():
        raise UnknownSymbolError("empty symbol")
    s = raw.strip().upper()
    if ":" in s:
        s = s.split(":", 1)[1]
    s = s.replace("!", "")
    for root in _ROOTS_BY_LEN:
        if s.startswith(root):
            rest = s[len(root):]
            if rest == "" or rest.isdigit() or _MONTH_CODE.fullmatch(rest):
                return root
    raise UnknownSymbolError(f"unsupported symbol: {raw!r}")


def spec_for(symbol: str) -> ContractSpec:
    return CONTRACTS[normalize_symbol(symbol)]


def round_to_tick(price: float, symbol: str) -> float:
    tick = spec_for(symbol).tick_size
    return round(round(price / tick) * tick, 10)
