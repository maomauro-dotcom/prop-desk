from __future__ import annotations

from propdesk.backtest import run_backtest
from propdesk.strategies import STRATEGY_CLASSES


def test_each_strategy_fires_on_sample_csv(sample_engine):
    accepted = {s["strategy_id"] for s in sample_engine.signals if s["status"] == "accepted"}
    emitted = {s["strategy_id"] for s in sample_engine.signals}
    for sid in STRATEGY_CLASSES:
        assert sid in emitted, f"{sid} never emitted a signal"
        assert sid in accepted, f"{sid} never had an accepted signal"


def test_each_strategy_fires_in_isolated_backtest():
    for name in ("orb", "vwap", "sweep"):
        for sym in ("MNQ", "MES"):
            rep = run_backtest(name, sym)
            assert rep.signals >= 1, (name, sym)


def test_replay_ends_flat_with_flatten_and_eod(sample_engine):
    assert not sample_engine.broker.positions
    names = {e["event"] for e in sample_engine.events}
    assert {"flatten", "eod_marked"} <= names
    assert sample_engine.risk.balance != 50_000


def test_signal_geometry(sample_engine):
    for s in sample_engine.signals:
        if s["side"] == "long":
            assert s["stop"] < s["price"] < s["target"]
        else:
            assert s["target"] < s["price"] < s["stop"]


def test_size_never_exceeds_two(sample_engine):
    from propdesk.domain.models import OrderStatus
    # Replay the fills: open contracts across symbols never exceed 2.
    open_qty: dict[str, int] = {}
    for f in sample_engine.broker.fills:
        sign = 1 if f.role == "entry" else -1
        open_qty[f.symbol] = open_qty.get(f.symbol, 0) + sign * f.qty
        assert sum(open_qty.values()) <= 2
    assert all(o.qty <= 2 for o in sample_engine.broker.orders.values() if o.status is OrderStatus.FILLED)


def test_param_update_validates():
    import pytest
    s = STRATEGY_CLASSES["orb"]()
    s.update_params({"range_minutes": 5, "target_r": 2.0})
    assert s.params.range_minutes == 5
    with pytest.raises(ValueError):
        s.update_params({"range_minutes": 30})
    with pytest.raises(ValueError):
        s.update_params({"nope": 1})
    with pytest.raises(ValueError):
        s.update_params({"use_vwap_bias": "maybe"})
