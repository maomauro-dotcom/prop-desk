from propdesk.strategies.base import Strategy, StrategyContext
from propdesk.strategies.filters import VolatilityFilter
from propdesk.strategies.liquidity_sweep import LiquiditySweepParams, LiquiditySweepStrategy
from propdesk.strategies.orb import OrbParams, OrbStrategy
from propdesk.strategies.vwap_reclaim import VwapReclaimParams, VwapReclaimStrategy

STRATEGY_CLASSES: dict[str, type[Strategy]] = {
    OrbStrategy.strategy_id: OrbStrategy,
    VwapReclaimStrategy.strategy_id: VwapReclaimStrategy,
    LiquiditySweepStrategy.strategy_id: LiquiditySweepStrategy,
}

ALIASES = {"orb": "orb", "vwap": "vwap_reclaim", "vwap_reclaim": "vwap_reclaim",
           "sweep": "liquidity_sweep", "liquidity_sweep": "liquidity_sweep"}


def build_default_strategies() -> dict[str, Strategy]:
    return {sid: cls() for sid, cls in STRATEGY_CLASSES.items()}


def resolve_strategy_id(name: str) -> str:
    try:
        return ALIASES[name.lower()]
    except KeyError:
        raise ValueError(f"unknown strategy {name!r}; choose from {sorted(ALIASES)}") from None


__all__ = [
    "ALIASES", "LiquiditySweepParams", "LiquiditySweepStrategy", "OrbParams", "OrbStrategy", "STRATEGY_CLASSES",
    "Strategy", "StrategyContext", "VolatilityFilter", "VwapReclaimParams", "VwapReclaimStrategy",
    "build_default_strategies", "resolve_strategy_id",
]
