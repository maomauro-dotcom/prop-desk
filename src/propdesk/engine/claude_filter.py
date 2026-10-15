"""Optional Claude filter. FAIL CLOSED: any missing key, timeout, API/MCP error => reject."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from propdesk.engine.claude_prompt import ClaudeCallError, ClaudeVerdict, call_claude


@dataclass(slots=True)
class FilterDecision:
    approved: bool
    reason: str
    transport: str
    details: dict[str, Any] = field(default_factory=dict)


ClaudeCaller = Callable[[dict[str, Any]], ClaudeVerdict]


class ClaudeFilter:
    def __init__(self, api_key: str | None = None, model: str | None = None, timeout_s: float = 15.0,
                 transport: str = "anthropic", caller: ClaudeCaller | None = None,
                 mcp_command: list[str] | None = None) -> None:
        if transport not in ("anthropic", "mcp"):
            raise ValueError("transport must be 'anthropic' or 'mcp'")
        self.api_key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self.timeout_s = timeout_s
        self.transport = transport
        self._caller = caller
        self.mcp_command = mcp_command or [sys.executable, "-m", "propdesk.mcp_server"]

    def evaluate(self, signal_context: dict[str, Any]) -> FilterDecision:
        try:
            if self._caller is not None:
                verdict = self._caller(signal_context)
            elif self.transport == "mcp":
                verdict = self._via_mcp(signal_context)
            else:
                if not self.api_key:
                    raise ClaudeCallError("ANTHROPIC_API_KEY is not set")
                verdict = call_claude(signal_context, api_key=self.api_key, model=self.model,
                                      timeout_s=self.timeout_s)
        except Exception as exc:  # noqa: BLE001 - fail closed on everything, and say why
            return FilterDecision(False, f"claude_filter_fail_closed: {exc}", self.transport,
                                  {"error": type(exc).__name__})
        approved = verdict.decision == "approve"
        return FilterDecision(approved, f"claude_{verdict.decision}: {verdict.reason}", self.transport,
                              {"confidence": verdict.confidence, "model": verdict.model})

    # ------------------------------------------------------------------ MCP
    def _via_mcp(self, signal_context: dict[str, Any]) -> ClaudeVerdict:
        """Call the `analyze_setup` tool of our MCP server over stdio (JSON-RPC 2.0, newline-delimited)."""
        env = dict(os.environ)
        if self.api_key:
            env["ANTHROPIC_API_KEY"] = self.api_key
        result = mcp_call_tool(self.mcp_command, "analyze_setup",
                               {"signal_context": signal_context, "call_model": True},
                               timeout_s=self.timeout_s + 5, env=env)
        if result.get("isError"):
            raise ClaudeCallError(f"MCP analyze_setup error: {_content_text(result)[:300]}")
        data = result.get("structuredContent") or json.loads(_content_text(result) or "{}")
        if "result" in data and isinstance(data["result"], dict):
            data = data["result"]
        verdict = data.get("verdict")
        if not verdict:
            raise ClaudeCallError(f"MCP analyze_setup returned no verdict: {data.get('error', 'unknown')}")
        return ClaudeVerdict(verdict["decision"], float(verdict.get("confidence", 0)), verdict.get("reason", ""),
                             verdict.get("model", "?"))


def _content_text(result: dict[str, Any]) -> str:
    return "".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")


def mcp_call_tool(command: list[str], tool: str, arguments: dict[str, Any], timeout_s: float = 20.0,
                  env: dict[str, str] | None = None) -> dict[str, Any]:
    """Minimal MCP stdio client: initialize -> initialized -> tools/call. Raises on any failure."""
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env)
    timer = threading.Timer(timeout_s, proc.kill)
    timer.start()
    try:
        assert proc.stdin and proc.stdout

        def send(msg: dict[str, Any]) -> None:
            proc.stdin.write(json.dumps(msg) + "\n")  # type: ignore[union-attr]
            proc.stdin.flush()  # type: ignore[union-attr]

        def recv(want_id: int) -> dict[str, Any]:
            while True:
                line = proc.stdout.readline()  # type: ignore[union-attr]
                if not line:
                    raise ClaudeCallError(f"MCP server closed the pipe (timeout {timeout_s}s or crash)")
                msg = json.loads(line)
                if msg.get("id") == want_id:
                    if "error" in msg:
                        raise ClaudeCallError(f"MCP error: {msg['error']}")
                    return msg["result"]

        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "propdesk-backend", "version": "0.1.0"}}})
        recv(1)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": arguments}})
        return recv(2)
    finally:
        timer.cancel()
        try:
            proc.kill()
        except OSError:
            pass
