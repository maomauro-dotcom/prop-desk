"""Entry point: official MCP SDK when available, otherwise the stdio JSON-RPC fallback."""

from __future__ import annotations

import os
import sys
from typing import Any

from propdesk.mcp_server import tools as T


def _build_sdk_server() -> Any | None:
    try:
        from mcp.server.mcpserver import MCPServer as Server  # mcp >= 2
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as Server  # mcp 1.x
        except ImportError:
            return None
    server = Server("propdesk")

    @server.tool()
    def get_current_market_state(symbol: str) -> dict:
        """Session context (VWAP, ORB, ATR, levels, last sweep), open position and account summary."""
        return T.get_current_market_state(symbol)

    @server.tool()
    def get_vwap_and_orb(symbol: str) -> dict:
        """RTH VWAP anchored 09:30 ET with 2-sigma bands and the opening range."""
        return T.get_vwap_and_orb(symbol)

    @server.tool()
    def analyze_setup(signal_context: dict | None = None, call_model: bool = False) -> dict:
        """Build the Claude review prompt for a setup; call_model=true returns an approve/reject verdict."""
        return T.analyze_setup(signal_context, call_model)

    @server.tool()
    def get_risk_status() -> dict:
        """Paper account: balance, equity, EOD trail floor, cushion, lock state, daily limits."""
        return T.get_risk_status()

    @server.tool()
    def get_recent_bars(symbol: str, limit: int = 30) -> dict:
        """Most recent 1-minute bars stored by the backend."""
        return T.get_recent_bars(symbol, limit)

    @server.tool()
    def get_liquidity_levels(symbol: str) -> dict:
        """Previous-day high/low, opening range, live swing levels and the last sweep."""
        return T.get_liquidity_levels(symbol)

    return server


def main() -> None:
    impl = os.environ.get("PROPDESK_MCP_IMPL", "auto")
    server = None if impl == "fallback" else _build_sdk_server()
    if server is None:
        if impl == "sdk":
            sys.exit("PROPDESK_MCP_IMPL=sdk but the official `mcp` package is not installed")
        from propdesk.mcp_server.stdio_jsonrpc import serve
        serve()
        return
    server.run("stdio")
