"""Prompt and Anthropic call shared by the backend filter and the MCP `analyze_setup` tool."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

DEFAULT_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = (
    "You are a risk reviewer for a PAPER trading simulator of CME micro index futures (MNQ/MES). "
    "You receive one candidate setup that already passed hard risk rules (size, daily loss, EOD trail cushion). "
    "Your only job is to veto setups whose context looks poor: entry far from the described level, stop inside "
    "noise relative to ATR, target unrealistic vs. session structure, or the setup contradicting VWAP/opening-range "
    "context. You never size positions and never suggest live trading. When in doubt, reject."
)

DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["approve", "reject"]},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["decision", "confidence", "reason"],
    "additionalProperties": False,
}

EXAMPLE_SIGNAL_CONTEXT: dict[str, Any] = {
    "signal": {
        "strategy_id": "orb", "symbol": "MNQ", "side": "long", "price": 21085.25,
        "stop": 21032.0, "target": 21165.0, "timestamp": "2026-10-12T09:52:00-04:00",
        "metadata": {"orb_high": 21080.0, "orb_low": 21032.0, "bar_volume": 2100, "avg_volume": 1400, "atr": 11.2},
    },
    "session": {"vwap": 21058.4, "vwap_upper_2sd": 21110.0, "vwap_lower_2sd": 21006.8, "atr": 11.2,
                "orb_high": 21080.0, "orb_low": 21032.0, "prev_day_high": 21120.5, "prev_day_low": 20940.0},
    "risk": {"cushion_usd": 2000.0, "risk_usd": 106.5, "day_pnl": 0.0, "entries_today": 0},
}


def build_prompt(signal_context: dict[str, Any]) -> str:
    return (
        "Review this candidate paper-trading setup and answer with the JSON schema provided.\n"
        "Context (JSON):\n"
        f"{json.dumps(signal_context, indent=2, sort_keys=True, default=str)}\n\n"
        "Checklist: (1) is the entry consistent with the strategy_id definition and the levels in metadata? "
        "(2) is the stop distance at least ~1 ATR and beyond the invalidation level? "
        "(3) is the target reachable given VWAP bands and session levels? "
        "(4) any conflict with VWAP side or opening range? "
        "Reply decision=approve only if all four look reasonable."
    )


EXAMPLE_PROMPT = build_prompt(EXAMPLE_SIGNAL_CONTEXT)


class ClaudeCallError(RuntimeError):
    pass


@dataclass(slots=True)
class ClaudeVerdict:
    decision: str
    confidence: float
    reason: str
    model: str


def call_claude(signal_context: dict[str, Any], *, api_key: str | None = None, model: str | None = None,
                timeout_s: float = 15.0) -> ClaudeVerdict:
    """Single Messages API call with structured output. Raises ClaudeCallError on ANY problem."""
    key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ClaudeCallError("ANTHROPIC_API_KEY is not set")
    model = model or os.environ.get("CLAUDE_MODEL") or DEFAULT_MODEL
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ClaudeCallError(f"anthropic SDK not installed: {exc}") from exc
    try:
        client = anthropic.Anthropic(api_key=key, timeout=timeout_s, max_retries=0)
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": DECISION_SCHEMA}},
            messages=[{"role": "user", "content": build_prompt(signal_context)}],
        )
    except anthropic.APITimeoutError as exc:
        raise ClaudeCallError(f"timeout after {timeout_s}s") from exc
    except anthropic.APIStatusError as exc:
        raise ClaudeCallError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise ClaudeCallError(f"Anthropic connection error: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - fail closed on anything unexpected
        raise ClaudeCallError(f"unexpected error calling Anthropic: {exc!r}") from exc
    if response.stop_reason == "refusal":
        raise ClaudeCallError("model refused the request")
    if response.stop_reason == "max_tokens":
        raise ClaudeCallError("response truncated (max_tokens)")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise ClaudeCallError("empty response")
    try:
        data = json.loads(text)
        decision = data["decision"]
        if decision not in ("approve", "reject"):
            raise ValueError(decision)
        return ClaudeVerdict(decision, float(data.get("confidence", 0.0)), str(data.get("reason", "")), model)
    except (ValueError, KeyError, TypeError) as exc:
        raise ClaudeCallError(f"unparseable decision: {text[:200]!r}") from exc
