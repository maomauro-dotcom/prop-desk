from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings

TOKEN = "test-dashboard-token"
SECRET = "test-webhook-secret"


def make_client(tmp_path: Path, **overrides) -> TestClient:
    settings = Settings(webhook_secret=SECRET, dashboard_token=TOKEN,
                        database_url=f"sqlite:///{tmp_path / 'desk.db'}")
    for k, v in overrides.items():
        setattr(settings, k, v)
    return TestClient(create_app(settings, start_clock=False))


AUTH = {"Authorization": f"Bearer {TOKEN}"}


def bar_payload(**kw):
    p = {"symbol": "CME_MINI:MNQ1!", "timeframe": "1", "open": 21000, "high": 21004, "low": 20998,
         "close": 21002, "volume": 1200, "timestamp": "2026-10-05T09:31:00"}
    p.update(kw)
    return p


def test_health_is_public_and_paper(tmp_path):
    with make_client(tmp_path) as c:
        r = c.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "mode": "paper", "tradovate_enabled": False, "ib_enabled": False}


def test_api_requires_token(tmp_path):
    with make_client(tmp_path) as c:
        assert c.get("/api/state").status_code == 401
        assert c.get("/api/state", headers={"Authorization": "Bearer nope"}).status_code == 401
        assert c.get("/api/state", headers=AUTH).status_code == 200


def test_empty_dashboard_token_rejects_everything(tmp_path):
    with make_client(tmp_path, dashboard_token="") as c:
        assert c.get("/api/state", headers={"Authorization": "Bearer "}).status_code == 503
        assert c.get("/api/state", headers=AUTH).status_code == 503


def test_webhook_wrong_secret_rejected(tmp_path):
    with make_client(tmp_path) as c:
        r = c.post("/webhook/bars", json=bar_payload(secret="wrong"))
        assert r.status_code == 401
        r = c.post("/webhook/bars", json=bar_payload())  # no secret at all
        assert r.status_code == 401
        r = c.post("/webhook/bars", json=bar_payload(), headers={"X-Webhook-Secret": "wrong"})
        assert r.status_code == 401


def test_webhook_correct_secret_accepted(tmp_path):
    with make_client(tmp_path) as c:
        r = c.post("/webhook/bars", json=bar_payload(secret=SECRET))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "accepted" and body["symbol"] == "MNQ"
        assert body["timestamp"].startswith("2026-10-05T09:31:00-04:00")  # naive = New York
        r = c.post("/webhook/bars", json=bar_payload(timestamp="2026-10-05T09:32:00"),
                   headers={"X-Webhook-Secret": SECRET})
        assert r.status_code == 200
        bars = c.get("/api/bars/MNQ", headers=AUTH).json()
        assert len(bars) == 2


def test_webhook_empty_secret_rejects_everything(tmp_path):
    with make_client(tmp_path, webhook_secret="") as c:
        assert c.post("/webhook/bars", json=bar_payload(secret="")).status_code == 503
        assert c.post("/webhook/bars", json=bar_payload(secret="x")).status_code == 503


def test_webhook_bad_payload_and_out_of_order(tmp_path):
    with make_client(tmp_path) as c:
        r = c.post("/webhook/bars", json={"secret": SECRET, "symbol": "MNQ"})
        assert r.status_code == 422
        r = c.post("/webhook/bars", json=bar_payload(secret=SECRET, timeframe="5"))
        assert r.status_code == 422
        assert c.post("/webhook/bars", json=bar_payload(secret=SECRET)).status_code == 200
        r = c.post("/webhook/bars", json=bar_payload(secret=SECRET))  # duplicate
        assert r.status_code == 409
        r = c.post("/webhook/bars", json=bar_payload(secret=SECRET, timestamp="2026-10-05T08:00:00"))
        assert r.json()["status"] == "ignored"


def test_replay_resets_and_produces_full_session(tmp_path):
    with make_client(tmp_path) as c:
        r = c.post("/api/sim/replay", headers=AUTH)
        assert r.status_code == 200, r.text
        summary = r.json()
        assert summary["equity"] != 50_000
        st = c.get("/api/state", headers=AUTH).json()
        assert st["positions"] == []
        sids = {s["strategy_id"] for s in st["signals"]}
        assert {"orb", "vwap_reclaim", "liquidity_sweep"} <= sids
        events = {e["event"] for e in st["events"]}
        assert {"flatten", "eod_marked"} <= events
        assert st["account"]["equity"] == summary["equity"]
        assert st["meta"]["mode"] == "paper"
        # Replaying again resets the account first: same deterministic result.
        again = c.post("/api/sim/replay", headers=AUTH).json()
        assert again["equity"] == summary["equity"]


def test_state_survives_restart(tmp_path):
    with make_client(tmp_path) as c:
        eq = c.post("/api/sim/replay", headers=AUTH).json()["balance"]
        c.put("/api/strategies/orb", headers=AUTH, json={"enabled": False, "params": {"range_minutes": 10}})
    with make_client(tmp_path) as c:
        st = c.get("/api/state", headers=AUTH).json()
        assert st["account"]["balance"] == eq
        orb = next(s for s in st["strategies"] if s["strategy_id"] == "orb")
        assert orb["enabled"] is False and orb["params"]["range_minutes"] == 10


def test_strategy_and_profile_updates_validate(tmp_path):
    with make_client(tmp_path) as c:
        r = c.put("/api/strategies/orb", headers=AUTH, json={"params": {"range_minutes": 99}})
        assert r.status_code == 422
        r = c.put("/api/strategies/nope", headers=AUTH, json={"enabled": True})
        assert r.status_code == 404
        r = c.put("/api/strategies/vwap_reclaim", headers=AUTH, json={"symbols": ["MES"], "enabled": True})
        assert r.status_code == 200 and r.json()["symbols"] == ["MES"]
        r = c.put("/api/risk/profile", headers=AUTH, json={"changes": {"max_contracts": 5}})
        assert r.status_code == 422
        r = c.put("/api/risk/profile", headers=AUTH, json={"changes": {"trail_amount": 2500}})
        assert r.status_code == 200 and r.json()["trail_amount"] == 2500
        assert c.get("/api/risk", headers=AUTH).json()["trail_floor"] == 47_500


def test_flatten_endpoint(tmp_path):
    with make_client(tmp_path) as c:
        r = c.post("/api/flatten", headers=AUTH)
        assert r.status_code == 200 and r.json()["positions"] == []


@pytest.mark.parametrize("flag", ["tradovate_enabled", "ib_enabled"])
def test_live_flags_do_not_enable_routing(tmp_path, flag):
    with make_client(tmp_path, **{flag: True}) as c:
        assert c.get("/health").json()["mode"] == "paper"
        st = c.get("/api/state", headers=AUTH).json()
        assert st["meta"]["live_routing"] is False
