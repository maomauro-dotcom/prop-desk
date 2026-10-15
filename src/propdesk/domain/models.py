"""Core domain types shared by strategies, risk, brokers and the API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"

    @property
    def sign(self) -> int:
        return 1 if self is Side.LONG else -1

    @property
    def opposite(self) -> "Side":
        return Side.SHORT if self is Side.LONG else Side.LONG


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderStatus(str, Enum):
    WORKING = "working"
    PENDING_PARENT = "pending_parent"  # bracket child waiting for its parent fill
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class Bar:
    """One OHLCV bar. `timestamp` is the bar OPEN time, tz-aware America/New_York."""

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: str = "1m"

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("Bar.timestamp must be timezone-aware")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError(f"Inconsistent OHLC for {self.symbol} at {self.timestamp.isoformat()}")
        if self.volume < 0:
            raise ValueError("Bar.volume must be >= 0")

    @property
    def range(self) -> float:
        return self.high - self.low


@dataclass(slots=True)
class Signal:
    strategy_id: str
    symbol: str
    side: Side
    price: float
    timestamp: datetime
    stop: float
    target: float
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def risk_points(self) -> float:
        return abs(self.price - self.stop)

    @property
    def reward_points(self) -> float:
        return abs(self.target - self.price)

    def validate(self) -> None:
        """Raise ValueError if stop/target are on the wrong side of entry."""
        if self.side is Side.LONG and not (self.stop < self.price < self.target):
            raise ValueError(f"Long signal needs stop < price < target ({self.stop}, {self.price}, {self.target})")
        if self.side is Side.SHORT and not (self.target < self.price < self.stop):
            raise ValueError(f"Short signal needs target < price < stop ({self.target}, {self.price}, {self.stop})")

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "price": self.price,
            "timestamp": self.timestamp.isoformat(),
            "stop": self.stop,
            "target": self.target,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class Order:
    id: str
    symbol: str
    side: Side
    qty: int
    type: OrderType
    price: float | None
    status: OrderStatus
    created_at: datetime
    strategy_id: str | None = None
    parent_id: str | None = None
    oco_group: str | None = None
    role: str = "entry"  # entry | stop | target | flatten
    fill_price: float | None = None
    filled_at: datetime | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side.value,
            "qty": self.qty,
            "type": self.type.value,
            "price": self.price,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "strategy_id": self.strategy_id,
            "parent_id": self.parent_id,
            "oco_group": self.oco_group,
            "role": self.role,
            "fill_price": self.fill_price,
            "filled_at": self.filled_at.isoformat() if self.filled_at else None,
            "reason": self.reason,
        }


@dataclass(slots=True)
class Fill:
    order_id: str
    symbol: str
    side: Side
    qty: int
    price: float
    timestamp: datetime
    role: str
    strategy_id: str | None


@dataclass(slots=True)
class Position:
    symbol: str
    side: Side
    qty: int
    avg_price: float
    opened_at: datetime
    strategy_id: str | None
    stop: float | None = None
    target: float | None = None

    def unrealized(self, mark: float, point_value: float) -> float:
        return (mark - self.avg_price) * self.side.sign * self.qty * point_value

    def to_dict(self, mark: float | None = None, point_value: float | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "symbol": self.symbol,
            "side": self.side.value,
            "qty": self.qty,
            "avg_price": self.avg_price,
            "opened_at": self.opened_at.isoformat(),
            "strategy_id": self.strategy_id,
            "stop": self.stop,
            "target": self.target,
        }
        if mark is not None and point_value is not None:
            out["mark"] = mark
            out["unrealized_usd"] = round(self.unrealized(mark, point_value), 2)
        return out


@dataclass(slots=True)
class Trade:
    """A closed round trip."""

    symbol: str
    side: Side
    qty: int
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    strategy_id: str | None
    pnl_usd: float
    r_multiple: float | None
    exit_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "qty": self.qty,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat(),
            "strategy_id": self.strategy_id,
            "pnl_usd": round(self.pnl_usd, 2),
            "r_multiple": None if self.r_multiple is None else round(self.r_multiple, 3),
            "exit_reason": self.exit_reason,
        }
