"""Fallback MCP server: newline-delimited JSON-RPC 2.0 over stdio with initialize / tools/list / tools/call.

Used when the official `mcp` SDK is not installed (or PROPDESK_MCP_IMPL=fallback). Same wire shape as the
MCP stdio transport, so any MCP client (and propdesk's own ClaudeFilter in transport=mcp) can talk to it.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from propdesk.mcp_server.tools import TOOLS, ToolError

PROTOCOL_VERSION = "2025-06-18"


def _result(rid: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = msg.get("method")
    rid = msg.get("id")
    if rid is None:  # notification
        return None
    if method == "initialize":
        return _result(rid, {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                             "serverInfo": {"name": "propdesk", "version": "0.1.0"}})
    if method == "ping":
        return _result(rid, {})
    if method == "tools/list":
        return _result(rid, {"tools": [{"name": n, "description": t["description"], "inputSchema": t["schema"]}
                                       for n, t in TOOLS.items()]})
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        tool = TOOLS.get(name)
        if tool is None:
            return _error(rid, -32602, f"unknown tool {name!r}")
        try:
            data = tool["fn"](**(params.get("arguments") or {}))
        except (ToolError, TypeError, ValueError) as exc:
            return _result(rid, {"isError": True, "content": [{"type": "text", "text": str(exc)}]})
        return _result(rid, {"content": [{"type": "text", "text": json.dumps(data, default=str)}],
                             "structuredContent": data, "isError": False})
    return _error(rid, -32601, f"method not found: {method}")


def serve(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            resp: dict[str, Any] | None = _error(None, -32700, f"parse error: {exc}")
        else:
            resp = handle(msg)
        if resp is not None:
            stdout.write(json.dumps(resp, default=str) + "\n")
            stdout.flush()
