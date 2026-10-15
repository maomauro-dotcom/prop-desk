"""Internal paper broker driven by bars.

Fill model (documented, deterministic):
  * Market orders fill at the reference price passed by the engine: the CLOSE of the
    signal bar. No slippage is added (configurable `slippage_ticks`, default 0).
  * Limit / stop orders are evaluated on bars AFTER they become active.
      - buy limit: fills if low <= price, at min(price, open)
      - sell limit: fills if high >= price, at max(price, open)
      - buy stop: fills if high >= price, at max(price, open)
      - sell stop: fills if low <= price, at min(price, open)
  * Brackets: parent + stop + target. Children stay PENDING_PARENT until the parent fills
    and are evaluated starting with the next bar. One child filling cancels the other (OCO).
    If stop and target are both touched inside the same bar, the STOP is assumed first
    (conservative, there is no intrabar path in 1-minute data).
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from propdesk.domain.instruments import spec_for
from propdesk.domain.models import Bar, Fill, Order, OrderStatus, OrderType, Position, Side, Trade


class BrokerError(RuntimeError):
    """Raised for any invalid order request. Never swallowed on the order path."""


@dataclass(slots=True)
class Bracket:
    parent: Order
    stop: Order
    target: Order


FillListener = Callable[[Fill, float, Trade | None], None]


class PaperBroker:
    name = "paper"

    def __init__(self, slippage_ticks: int = 0) -> None:
        self.slippage_ticks = slippage_ticks
        self._listeners: list[FillListener] = []
        self.reset()

    def reset(self) -> None:
        self._ids = itertools.count(1)
        self.orders: dict[str, Order] = {}
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.fills: list[Fill] = []
        self.marks: dict[str, float] = {}
        self.realized_total: float = 0.0
        self._risk_points: dict[str, float] = {}
        self._active_from: dict[str, datetime] = {}

    def add_fill_listener(self, fn: FillListener) -> None:
        self._listeners.append(fn)

    # ------------------------------------------------------------- submission
    def _new_id(self) -> str:
        return f"P{next(self._ids):06d}"

    def _check(self, symbol: str, qty: int) -> str:
        if qty <= 0:
            raise BrokerError(f"qty must be positive, got {qty}")
        try:
            return spec_for(symbol).root
        except ValueError as exc:
            raise BrokerError(str(exc)) from exc

    def submit_market(self, symbol: str, side: Side, qty: int, ref_price: float, ts: datetime,
                      strategy_id: str | None = None, role: str = "entry") -> Order:
        symbol = self._check(symbol, qty)
        if ref_price <= 0:
            raise BrokerError(f"invalid reference price {ref_price}")
        order = Order(self._new_id(), symbol, side, qty, OrderType.MARKET, None, OrderStatus.WORKING, ts,
                      strategy_id=strategy_id, role=role)
        self.orders[order.id] = order
        slip = self.slippage_ticks * spec_for(symbol).tick_size * side.sign
        self._fill(order, ref_price + slip, ts)
        return order

    def submit_limit(self, symbol: str, side: Side, qty: int, price: float, ts: datetime,
                     strategy_id: str | None = None, role: str = "entry") -> Order:
        return self._submit_resting(symbol, side, qty, OrderType.LIMIT, price, ts, strategy_id, role)

    def submit_stop(self, symbol: str, side: Side, qty: int, price: float, ts: datetime,
                    strategy_id: str | None = None, role: str = "entry") -> Order:
        return self._submit_resting(symbol, side, qty, OrderType.STOP, price, ts, strategy_id, role)

    def _submit_resting(self, symbol: str, side: Side, qty: int, otype: OrderType, price: float, ts: datetime,
                        strategy_id: str | None, role: str, parent_id: str | None = None,
                        oco: str | None = None) -> Order:
        symbol = self._check(symbol, qty)
        if price <= 0:
            raise BrokerError(f"invalid {otype.value} price {price}")
        status = OrderStatus.PENDING_PARENT if parent_id else OrderStatus.WORKING
        order = Order(self._new_id(), symbol, side, qty, otype, price, status, ts, strategy_id=strategy_id,
                      parent_id=parent_id, oco_group=oco, role=role)
        self.orders[order.id] = order
        if status is OrderStatus.WORKING:
            self._active_from[order.id] = ts
        return order

    def submit_bracket(self, symbol: str, side: Side, qty: int, stop: float, target: float, ts: datetime,
                       strategy_id: str | None = None, entry_type: OrderType = OrderType.MARKET,
                       entry_price: float | None = None) -> Bracket:
        """Parent + protective stop + target with OCO. Market parents fill at `entry_price` (bar close)."""
        if entry_price is None:
            raise BrokerError("bracket requires entry_price (reference close for market, limit/stop price otherwise)")
        if side is Side.LONG and not (stop < entry_price < target):
            raise BrokerError(f"long bracket needs stop < entry < target ({stop}, {entry_price}, {target})")
        if side is Side.SHORT and not (target < entry_price < stop):
            raise BrokerError(f"short bracket needs target < entry < stop ({target}, {entry_price}, {stop})")
        symbol = self._check(symbol, qty)
        oco = f"OCO-{next(self._ids):06d}"
        if entry_type is OrderType.MARKET:
            parent = Order(self._new_id(), symbol, side, qty, OrderType.MARKET, None, OrderStatus.WORKING, ts,
                           strategy_id=strategy_id, role="entry")
            self.orders[parent.id] = parent
        else:
            parent = self._submit_resting(symbol, side, qty, entry_type, entry_price, ts, strategy_id, "entry")
        stop_o = self._submit_resting(symbol, side.opposite, qty, OrderType.STOP, stop, ts, strategy_id, "stop",
                                      parent_id=parent.id, oco=oco)
        target_o = self._submit_resting(symbol, side.opposite, qty, OrderType.LIMIT, target, ts, strategy_id,
                                        "target", parent_id=parent.id, oco=oco)
        self._risk_points[parent.id] = abs(entry_price - stop)
        if entry_type is OrderType.MARKET:
            slip = self.slippage_ticks * spec_for(symbol).tick_size * side.sign
            self._fill(parent, entry_price + slip, ts)
        return Bracket(parent, stop_o, target_o)

    def cancel(self, order_id: str, reason: str = "cancelled") -> Order:
        order = self.orders.get(order_id)
        if order is None:
            raise BrokerError(f"unknown order {order_id}")
        if order.status not in (OrderStatus.WORKING, OrderStatus.PENDING_PARENT):
            raise BrokerError(f"order {order_id} is {order.status.value}, cannot cancel")
        order.status = OrderStatus.CANCELLED
        order.reason = reason
        self._active_from.pop(order_id, None)
        for child in self.orders.values():
            if child.parent_id == order_id and child.status is OrderStatus.PENDING_PARENT:
                child.status = OrderStatus.CANCELLED
                child.reason = "parent_cancelled"
        return order

    # --------------------------------------------------------------- bar loop
    def on_bar(self, bar: Bar) -> list[Fill]:
        """Evaluate resting orders against a bar. Returns fills in execution order."""
        self.marks[bar.symbol] = bar.close
        fills: list[Fill] = []
        working = [o for o in self.orders.values() if o.symbol == bar.symbol and o.status is OrderStatus.WORKING
                   and o.type is not OrderType.MARKET and self._active_from.get(o.id, bar.timestamp) <= bar.timestamp]
        # Entries first, then exits; stops before targets (conservative).
        working.sort(key=lambda o: (o.role != "entry", o.role != "stop"))
        for o in working:
            if o.status is not OrderStatus.WORKING:
                continue  # cancelled by OCO within this loop
            px = self._trigger_price(o, bar)
            if px is not None:
                fills.append(self._fill(o, px, bar.timestamp + timedelta(minutes=1)))
        return fills

    @staticmethod
    def _trigger_price(o: Order, bar: Bar) -> float | None:
        assert o.price is not None
        if o.type is OrderType.LIMIT:
            if o.side is Side.LONG and bar.low <= o.price:
                return min(o.price, bar.open)
            if o.side is Side.SHORT and bar.high >= o.price:
                return max(o.price, bar.open)
        elif o.type is OrderType.STOP:
            if o.side is Side.LONG and bar.high >= o.price:
                return max(o.price, bar.open)
            if o.side is Side.SHORT and bar.low <= o.price:
                return min(o.price, bar.open)
        return None

    # -------------------------------------------------------------- flatten
    def flatten(self, ts: datetime, reason: str, symbol: str | None = None,
                prices: dict[str, float] | None = None) -> list[Fill]:
        """Cancel every working order and close every position at the given/last price."""
        for o in list(self.orders.values()):
            if (symbol is None or o.symbol == symbol) and o.status in (OrderStatus.WORKING, OrderStatus.PENDING_PARENT):
                o.status = OrderStatus.CANCELLED
                o.reason = f"flatten:{reason}"
                self._active_from.pop(o.id, None)
        fills = []
        for sym, pos in list(self.positions.items()):
            if symbol is not None and sym != symbol:
                continue
            price = (prices or {}).get(sym, self.marks.get(sym))
            if price is None:
                raise BrokerError(f"cannot flatten {sym}: no price available")
            order = Order(self._new_id(), sym, pos.side.opposite, pos.qty, OrderType.MARKET, None,
                          OrderStatus.WORKING, ts, strategy_id=pos.strategy_id, role="flatten", reason=reason)
            self.orders[order.id] = order
            fills.append(self._fill(order, price, ts))
        return fills

    # ---------------------------------------------------------------- fills
    def _fill(self, order: Order, price: float, ts: datetime) -> Fill:
        order.status = OrderStatus.FILLED
        order.fill_price = price
        order.filled_at = ts
        self._active_from.pop(order.id, None)
        fill = Fill(order.id, order.symbol, order.side, order.qty, price, ts, order.role, order.strategy_id)
        self.fills.append(fill)
        realized, trade = self._apply_to_position(order, price, ts)
        self.realized_total += realized
        # Bracket bookkeeping.
        if order.role == "entry":
            for child in self.orders.values():
                if child.parent_id == order.id and child.status is OrderStatus.PENDING_PARENT:
                    child.status = OrderStatus.WORKING
                    child.qty = order.qty
                    self._active_from[child.id] = ts
                    pos = self.positions.get(order.symbol)
                    if pos is not None:
                        if child.role == "stop":
                            pos.stop = child.price
                        elif child.role == "target":
                            pos.target = child.price
        if order.oco_group:
            for sib in self.orders.values():
                if sib.oco_group == order.oco_group and sib.id != order.id and \
                        sib.status in (OrderStatus.WORKING, OrderStatus.PENDING_PARENT):
                    sib.status = OrderStatus.CANCELLED
                    sib.reason = "oco"
                    self._active_from.pop(sib.id, None)
        for fn in self._listeners:
            fn(fill, realized, trade)
        return fill

    def _apply_to_position(self, order: Order, price: float, ts: datetime) -> tuple[float, Trade | None]:
        pv = spec_for(order.symbol).point_value
        pos = self.positions.get(order.symbol)
        if pos is None:
            self.positions[order.symbol] = Position(order.symbol, order.side, order.qty, price, ts, order.strategy_id)
            pos_risk = self._risk_points.get(order.id)
            if pos_risk is not None:
                self._risk_points[order.symbol] = pos_risk
            return 0.0, None
        if pos.side is order.side:
            total = pos.qty + order.qty
            pos.avg_price = (pos.avg_price * pos.qty + price * order.qty) / total
            pos.qty = total
            return 0.0, None
        closing = min(pos.qty, order.qty)
        realized = (price - pos.avg_price) * pos.side.sign * closing * pv
        trade = None
        if closing == pos.qty:
            risk_pts = self._risk_points.pop(order.symbol, None)
            pts = (price - pos.avg_price) * pos.side.sign
            trade = Trade(order.symbol, pos.side, pos.qty, pos.avg_price, price, pos.opened_at, ts, pos.strategy_id,
                          realized, (pts / risk_pts) if risk_pts else None,
                          order.role if order.role != "flatten" else f"flatten:{order.reason}")
            self.trades.append(trade)
            del self.positions[order.symbol]
            leftover = order.qty - closing
            if leftover > 0:
                self.positions[order.symbol] = Position(order.symbol, order.side, leftover, price, ts,
                                                        order.strategy_id)
        else:
            pos.qty -= closing
        return realized, trade

    # -------------------------------------------------------------- queries
    def open_contracts(self) -> int:
        return sum(p.qty for p in self.positions.values())

    def open_symbols(self) -> set[str]:
        return set(self.positions)

    def unrealized(self) -> float:
        total = 0.0
        for sym, pos in self.positions.items():
            mark = self.marks.get(sym, pos.avg_price)
            total += pos.unrealized(mark, spec_for(sym).point_value)
        return total

    def positions_view(self) -> list[dict]:
        return [p.to_dict(self.marks.get(s, p.avg_price), spec_for(s).point_value) for s, p in self.positions.items()]

    def working_orders(self) -> list[Order]:
        return [o for o in self.orders.values() if o.status in (OrderStatus.WORKING, OrderStatus.PENDING_PARENT)]
