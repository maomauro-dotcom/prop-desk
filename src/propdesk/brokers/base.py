"""Broker interface. Only PaperBroker is functional in this version."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from propdesk.domain.models import Fill, Order, Side


class LiveRoutingDisabledError(RuntimeError):
    """Raised by every live adapter method. This build never sends orders to a broker."""


LIVE_DISABLED_MESSAGE = (
    "Live order routing is disabled in this build of propdesk. No order was sent. "
    "Apex accounts usually forbid automated trading: get written permission from Apex before "
    "even considering a live route, and implement/review the adapter explicitly."
)


class Broker(Protocol):
    name: str

    def submit_market(self, symbol: str, side: Side, qty: int, ref_price: float, ts: datetime,
                      strategy_id: str | None = None, role: str = "entry") -> Order: ...

    def cancel(self, order_id: str, reason: str = "cancelled") -> Order: ...

    def flatten(self, ts: datetime, reason: str, symbol: str | None = None,
                prices: dict[str, float] | None = None) -> list[Fill]: ...
