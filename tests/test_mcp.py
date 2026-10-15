from __future__ import annotations

import json
import sys

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from propdesk.engine.claude_filter import mcp_call_tool
from propdesk.mcp_server import tools as T
from propdesk.mcp_server.stdio_jsonrpc import handle


@pytest.fixture
def replayed_db(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'mcp.db'}"
    settings = Settings(webhook_secret="s", dashboard_token="t", database_url=url)
    with TestClient(create_app(settings, start_clock=False)) as c:
        assert c.post("/api/sim/replay", headers={"Authorization": "Bearer t"}).status_code == 200
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("PROPDESK_API_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return url


def test_tools_list_has_all_six():
    resp = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {"get_current_market_state", "get_vwap_and_orb", "analyze_setup", "get_risk_status",
                     "get_recent_bars", "get_liquidity_levels"}


def test_tools_read_sqlite(replayed_db):
    vo = T.get_vwap_and_orb("MNQ")
    assert vo["source"] == "sqlite" and vo["vwap"] and vo["orb_high"] > vo["orb_low"]
    assert T.get_recent_bars("MES", 5)["count"] == 5
    assert T.get_risk_status()["account"]["balance"] != 50_000
    assert "live_levels" in T.get_liquidity_levels("MNQ")
    assert T.get_current_market_state("MES")["session"]["symbol"] == "MES"


def test_no_source_is_an_error_not_fake_data(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'missing.db'}")
    monkeypatch.delenv("PROPDESK_API_URL", raising=False)
    with pytest.raises(T.ToolError):
        T.get_risk_status()


def test_analyze_setup_prompt_and_fail_closed(replayed_db):
    out = T.analyze_setup()
    assert out["used_example_context"] and "orb" in out["example_prompt"]
    resp = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                   "params": {"name": "analyze_setup", "arguments": {"call_model": True}}})
    assert resp["result"]["isError"] is True
    assert "ANTHROPIC_API_KEY" in resp["result"]["content"][0]["text"]


@pytest.mark.parametrize("impl", ["fallback", "sdk"])
def test_stdio_roundtrip(replayed_db, monkeypatch, impl):
    if impl == "sdk":
        pytest.importorskip("mcp")
    import os
    env = dict(os.environ, PROPDESK_MCP_IMPL=impl)
    r = mcp_call_tool([sys.executable, "-m", "propdesk.mcp_server"], "get_vwap_and_orb", {"symbol": "MNQ"},
                      timeout_s=30, env=env)
    assert not r.get("isError")
    data = json.loads("".join(c["text"] for c in r["content"] if c["type"] == "text"))
    assert data["symbol"] == "MNQ"
