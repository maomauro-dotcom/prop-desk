from __future__ import annotations

from datetime import date

from conftest import et, flat_day
from propdesk.domain.models import Side, Signal
from propdesk.domain.profile import RiskProfile
from propdesk.engine.claude_filter import ClaudeFilter
from propdesk.engine.claude_prompt import ClaudeCallError, ClaudeVerdict
from propdesk.engine.engine import TradingEngine

D = date(2026, 10, 5)


def engine_with(filter_: ClaudeFilter, enabled: bool = True) -> TradingEngine:
    eng = TradingEngine(profile=RiskProfile(claude_filter_enabled=enabled), claude_filter=filter_)
    for s in eng.strategies.values():
        s.enabled = False
    for b in flat_day("MNQ", D, 21000.0, end=(10, 0)):
        eng.process_bar(b)
    return eng


def signal() -> Signal:
    return Signal("orb", "MNQ", Side.LONG, 21000.0, et(D, 10, 0), 20980.0, 21040.0)


def test_missing_api_key_fails_closed():
    eng = engine_with(ClaudeFilter(api_key=""))
    rec = eng.handle_signal(signal())
    assert rec["status"] == "rejected"
    assert "claude_filter_fail_closed" in rec["reason"] and "ANTHROPIC_API_KEY" in rec["reason"]
    assert not eng.broker.positions
    assert any(e["event"] == "claude_filter" and not e["data"]["approved"] for e in eng.events)


def test_timeout_fails_closed():
    def slow(_ctx):
        raise ClaudeCallError("timeout after 0.01s")

    eng = engine_with(ClaudeFilter(api_key="sk-test", caller=slow))
    rec = eng.handle_signal(signal())
    assert rec["status"] == "rejected" and "timeout" in rec["reason"]


def test_unexpected_exception_fails_closed():
    def boom(_ctx):
        raise RuntimeError("network down")

    eng = engine_with(ClaudeFilter(api_key="sk-test", caller=boom))
    assert eng.handle_signal(signal())["status"] == "rejected"


def test_mcp_failure_fails_closed():
    f = ClaudeFilter(api_key="", transport="mcp", timeout_s=5,
                     mcp_command=["python3", "-c", "import sys; sys.exit(3)"])
    eng = engine_with(f)
    rec = eng.handle_signal(signal())
    assert rec["status"] == "rejected" and "claude_filter_fail_closed" in rec["reason"]


def test_reject_verdict_rejects_and_approve_passes():
    eng = engine_with(ClaudeFilter(caller=lambda c: ClaudeVerdict("reject", 0.9, "stop in noise", "stub")))
    assert eng.handle_signal(signal())["status"] == "rejected"
    eng = engine_with(ClaudeFilter(caller=lambda c: ClaudeVerdict("approve", 0.8, "fine", "stub")))
    rec = eng.handle_signal(signal())
    assert rec["status"] == "accepted" and rec["claude"]["approved"]


def test_filter_off_by_default_does_not_call():
    calls = []
    eng = engine_with(ClaudeFilter(caller=lambda c: calls.append(c) or ClaudeVerdict("reject", 1, "", "x")),
                      enabled=False)
    assert eng.handle_signal(signal())["status"] == "accepted"
    assert calls == []
