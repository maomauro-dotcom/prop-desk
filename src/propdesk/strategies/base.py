"""Strategy base class, typed editable parameters and the per-bar context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import MISSING, asdict, dataclass, field, fields, replace
from datetime import datetime, time, timedelta
from typing import Any, ClassVar, Generic, TypeVar

from propdesk.domain.clock import to_et
from propdesk.domain.models import Bar, Signal
from propdesk.engine.session import SymbolSession
from propdesk.strategies.filters import VolatilityFilter


def param(default: Any, *, label: str, minimum: float | None = None, maximum: float | None = None,
          choices: tuple[str, ...] | None = None, help: str = "") -> Any:  # noqa: A002
    """Dataclass field carrying UI/validation metadata."""
    meta = {"label": label, "min": minimum, "max": maximum, "choices": choices, "help": help}
    return field(default=default, metadata=meta)


def parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


@dataclass(slots=True)
class StrategyContext:
    """What a strategy may look at when a bar closes."""

    session: SymbolSession
    volatility: VolatilityFilter
    now: datetime  # bar close time, ET

    @property
    def atr(self) -> float | None:
        return self.session.atr


P = TypeVar("P")


class Strategy(ABC, Generic[P]):
    strategy_id: ClassVar[str]
    display_name: ClassVar[str]
    params_cls: ClassVar[type]
    default_symbols: ClassVar[tuple[str, ...]] = ("MNQ", "MES")

    def __init__(self, params: P | None = None, symbols: set[str] | None = None, enabled: bool = True) -> None:
        self.params: P = params if params is not None else self.params_cls()
        self.symbols: set[str] = set(symbols) if symbols is not None else set(self.default_symbols)
        self.enabled = enabled
        self._validate(self.params)
        self.reset()

    # ------------------------------------------------------------------ API
    @abstractmethod
    def on_bar(self, bar: Bar, ctx: StrategyContext) -> list[Signal]:
        ...

    @abstractmethod
    def reset(self) -> None:
        """Clear intraday state (called on replay/reset)."""

    def update_params(self, changes: dict[str, Any]) -> None:
        current = asdict(self.params)  # type: ignore[call-overload]
        unknown = set(changes) - set(current)
        if unknown:
            raise ValueError(f"unknown parameters for {self.strategy_id}: {sorted(unknown)}")
        coerced: dict[str, Any] = {}
        for f in fields(self.params):  # type: ignore[arg-type]
            if f.name in changes:
                coerced[f.name] = _coerce(f.type, changes[f.name], f.name)
        new = replace(self.params, **coerced)  # type: ignore[type-var]
        self._validate(new)
        self.params = new

    def describe(self) -> dict[str, Any]:
        specs = []
        for f in fields(self.params):  # type: ignore[arg-type]
            meta = dict(f.metadata)
            specs.append({
                "name": f.name,
                "type": _type_name(f.type),
                "value": getattr(self.params, f.name),
                "default": f.default if f.default is not MISSING else None,
                "label": meta.get("label", f.name),
                "min": meta.get("min"),
                "max": meta.get("max"),
                "choices": list(meta["choices"]) if meta.get("choices") else None,
                "help": meta.get("help", ""),
            })
        return {
            "strategy_id": self.strategy_id,
            "name": self.display_name,
            "enabled": self.enabled,
            "symbols": sorted(self.symbols),
            "params": asdict(self.params),  # type: ignore[call-overload]
            "param_specs": specs,
        }

    # -------------------------------------------------------------- helpers
    def _validate(self, params: Any) -> None:
        errors = []
        for f in fields(params):
            v = getattr(params, f.name)
            meta = f.metadata
            if meta.get("min") is not None and isinstance(v, (int, float)) and not isinstance(v, bool) and v < meta["min"]:
                errors.append(f"{f.name}={v} < min {meta['min']}")
            if meta.get("max") is not None and isinstance(v, (int, float)) and not isinstance(v, bool) and v > meta["max"]:
                errors.append(f"{f.name}={v} > max {meta['max']}")
            if meta.get("choices") and v not in meta["choices"]:
                errors.append(f"{f.name}={v!r} not in {list(meta['choices'])}")
            if isinstance(v, str) and f.name.endswith(("_start", "_end")):
                try:
                    parse_hhmm(v)
                except ValueError:
                    errors.append(f"{f.name} must be HH:MM")
        extra = self.validate_params(params)
        errors.extend(extra)
        if errors:
            raise ValueError(f"invalid parameters for {self.strategy_id}: " + "; ".join(errors))

    def validate_params(self, params: Any) -> list[str]:
        return []

    @staticmethod
    def bar_close_time(bar: Bar) -> datetime:
        return to_et(bar.timestamp) + timedelta(minutes=1)


def _type_name(tp: Any) -> str:
    name = tp if isinstance(tp, str) else getattr(tp, "__name__", str(tp))
    return {"int": "int", "float": "float", "bool": "bool", "str": "str"}.get(name, name)


def _coerce(tp: Any, value: Any, name: str) -> Any:
    t = _type_name(tp)
    try:
        if t == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.lower() in {"true", "false", "1", "0"}:
                return value.lower() in {"true", "1"}
            raise ValueError
        if t == "int":
            if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
                raise ValueError
            return int(value)
        if t == "float":
            if isinstance(value, bool):
                raise ValueError
            return float(value)
        if t == "str":
            if not isinstance(value, str):
                raise ValueError
            return value
    except (TypeError, ValueError):
        raise ValueError(f"parameter {name} expects {t}, got {value!r}") from None
    return value
