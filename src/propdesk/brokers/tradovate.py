"""Tradovate live adapter - DISABLED.

Even with TRADOVATE_ENABLED=true and credentials present, every method raises
LiveRoutingDisabledError. No network call is made. Integration points are documented
below so a future, reviewed implementation knows where things go:

  * auth:      POST {base}/auth/accesstokenrequest  (name, password, appId, appVersion, cid, sec)
               -> accessToken / mdAccessToken, renew via GET /auth/renewaccesstoken
  * orders:    POST /order/placeorder, /order/placeoso (bracket), /order/cancelorder
  * flatten:   POST /order/liquidateposition (per contract) for every open position
  * positions: GET /position/list, GET /account/list for the account id
  * bars:      see propdesk.feeds.tradovate.TradovateMarketData (md/getChart over websocket)
"""

from __future__ import annotations

from datetime import datetime
from typing import NoReturn

from propdesk.brokers.base import LIVE_DISABLED_MESSAGE, LiveRoutingDisabledError
from propdesk.domain.models import Side


class TradovateBroker:
    name = "tradovate"

    def __init__(self, enabled_flag: bool = False) -> None:
        # The flag is recorded for diagnostics only; it does NOT enable routing.
        self.enabled_flag = enabled_flag

    def _refuse(self, action: str) -> NoReturn:
        raise LiveRoutingDisabledError(f"[tradovate:{action}] {LIVE_DISABLED_MESSAGE}")

    def authenticate(self) -> NoReturn:
        self._refuse("auth")

    def submit_market(self, symbol: str, side: Side, qty: int, ref_price: float, ts: datetime,
                      strategy_id: str | None = None, role: str = "entry") -> NoReturn:
        self._refuse("placeorder")

    def submit_bracket(self, *args: object, **kwargs: object) -> NoReturn:
        self._refuse("placeoso")

    def cancel(self, order_id: str, reason: str = "cancelled") -> NoReturn:
        self._refuse("cancelorder")

    def flatten(self, ts: datetime, reason: str, symbol: str | None = None,
                prices: dict[str, float] | None = None) -> NoReturn:
        self._refuse("liquidateposition")

    def positions(self) -> NoReturn:
        self._refuse("position/list")
