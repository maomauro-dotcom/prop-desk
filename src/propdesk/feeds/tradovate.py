"""Tradovate market data interface - DISABLED (DOM not needed).

Integration points for a reviewed future version:
  * auth:  POST /auth/accesstokenrequest -> mdAccessToken
  * bars:  websocket wss://md.tradovateapi.com/v1/websocket, "md/getChart" with
           chartDescription {underlyingType: "MinuteBar", elementSize: 1} for MNQ/MES front month
  * convert each closed bar into propdesk.domain.models.Bar (timestamp -> America/New_York)
"""

from __future__ import annotations

from typing import NoReturn

from propdesk.brokers.base import LiveRoutingDisabledError


class TradovateMarketData:
    def __init__(self, enabled_flag: bool = False) -> None:
        self.enabled_flag = enabled_flag

    def connect(self) -> NoReturn:
        raise LiveRoutingDisabledError("Tradovate market data is disabled in this build; use the CSV feed or "
                                       "the TradingView webhook (/webhook/bars).")

    def subscribe_bars(self, symbol: str) -> NoReturn:
        self.connect()
