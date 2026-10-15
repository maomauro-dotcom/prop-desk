"""Interactive Brokers live adapter - DISABLED.

The user has not confirmed an IB account or API access. Every method raises
LiveRoutingDisabledError regardless of IB_ENABLED. Integration points for a future,
reviewed implementation (official TWS API / IB Gateway only):

  * auth:      connect to TWS/IB Gateway (host, port, clientId); no credentials in this repo
  * bars:      reqHistoricalData / reqRealTimeBars on the CME MNQ/MES front month
  * orders:    placeOrder with parent + attached STP/LMT children (transmit flag on the last)
  * flatten:   reqPositions, then opposite MKT orders; reqGlobalCancel for working orders
  * positions: reqPositions / reqAccountUpdates
"""

from __future__ import annotations

from datetime import datetime
from typing import NoReturn

from propdesk.brokers.base import LIVE_DISABLED_MESSAGE, LiveRoutingDisabledError
from propdesk.domain.models import Side


class IbBroker:
    name = "interactive_brokers"

    def __init__(self, enabled_flag: bool = False) -> None:
        self.enabled_flag = enabled_flag

    def _refuse(self, action: str) -> NoReturn:
        raise LiveRoutingDisabledError(f"[ib:{action}] {LIVE_DISABLED_MESSAGE}")

    def connect(self) -> NoReturn:
        self._refuse("connect")

    def recent_bars(self, symbol: str) -> NoReturn:
        self._refuse("reqHistoricalData")

    def submit_market(self, symbol: str, side: Side, qty: int, ref_price: float, ts: datetime,
                      strategy_id: str | None = None, role: str = "entry") -> NoReturn:
        self._refuse("placeOrder")

    def submit_bracket(self, *args: object, **kwargs: object) -> NoReturn:
        self._refuse("placeOrder(bracket)")

    def cancel(self, order_id: str, reason: str = "cancelled") -> NoReturn:
        self._refuse("cancelOrder")

    def flatten(self, ts: datetime, reason: str, symbol: str | None = None,
                prices: dict[str, float] | None = None) -> NoReturn:
        self._refuse("flatten")

    def positions(self) -> NoReturn:
        self._refuse("reqPositions")
