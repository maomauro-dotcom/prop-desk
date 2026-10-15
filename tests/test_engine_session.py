from __future__ import annotations

from datetime import date, timedelta

from conftest import et, flat_day
from propdesk.brokers import IbBroker, LiveRoutingDisabledError, TradovateBroker
from propdesk.domain.models import Side, Signal
from propdesk.engine.engine import TradingEngine
from propdesk.feeds import TradovateMarketData

D = date(2026, 10, 5)


def engine_no_strategies() -> TradingEngine:
    eng = TradingEngine()
    for s in eng.strategies.values():
        s.enabled = False
    return eng


def run_until(eng: TradingEngine, bars, hh: int, mm: int):
    cut = et(D, hh, mm)
    rest = []
    for b in bars:
        if b.timestamp < cut:
            eng.process_bar(b)
        else:
            rest.append(b)
    return rest


def test_flatten_at_1555_and_eod_marked():
    eng = engine_no_strategies()
    bars = flat_day("MNQ", D, 21000.0, step=0.25, wiggle=1.0)
    rest = run_until(eng, bars, 15, 0)
    px = eng.broker.marks["MNQ"]
    sig = Signal("orb", "MNQ", Side.LONG, px, et(D, 15, 0), px - 100, px + 400)
    rec = eng.handle_signal(sig)
    assert rec["status"] == "accepted"
    assert eng.broker.positions
    for b in rest:
        if b.timestamp < et(D, 15, 55):
            eng.process_bar(b)
    assert eng.broker.positions, "still open before 15:55"
    remaining = [b for b in rest if b.timestamp >= et(D, 15, 55)]
    eng.process_bar(remaining[0])
    assert not eng.broker.positions
    assert not eng.broker.working_orders()
    names = [e["event"] for e in eng.events]
    assert "flatten" in names and "eod_marked" in names
    assert names.index("flatten") < names.index("eod_marked")
    trade = eng.broker.trades[-1]
    assert trade.exit_reason == "flatten:eod_flatten"
    assert trade.exit_time == et(D, 15, 55)
    # P&L moved into the balance at EOD.
    assert eng.risk.day_realized == 0
    assert eng.risk.balance == 50_000 + trade.pnl_usd


def test_no_entries_after_cutoff():
    eng = engine_no_strategies()
    bars = flat_day("MNQ", D, 21000.0)
    for b in bars:
        eng.process_bar(b)
    late = Signal("orb", "MNQ", Side.LONG, 21000.0, et(D, 15, 56), 20990.0, 21020.0)
    rec = eng.handle_signal(late)
    assert rec["status"] == "rejected" and rec["reason"] == "after_flatten_cutoff"
    at_cut = Signal("orb", "MNQ", Side.LONG, 21000.0, et(D, 15, 55), 20990.0, 21020.0)
    assert eng.handle_signal(at_cut)["reason"] == "after_flatten_cutoff"


def test_strategies_never_enter_after_cutoff_on_sample(sample_engine):
    for s in sample_engine.signals:
        if s["status"] == "accepted":
            hhmm = s["timestamp"][11:16]
            assert hhmm < "15:55", s


def test_clock_tick_flattens_without_bars():
    eng = engine_no_strategies()
    bars = flat_day("MNQ", D, 21000.0, end=(14, 0))
    for b in bars:
        eng.process_bar(b)
    eng.handle_signal(Signal("orb", "MNQ", Side.LONG, eng.broker.marks["MNQ"], et(D, 14, 0),
                             eng.broker.marks["MNQ"] - 20, eng.broker.marks["MNQ"] + 40))
    assert eng.broker.positions
    assert not eng.clock_tick(et(D, 15, 54))
    assert eng.clock_tick(et(D, 15, 55))
    assert not eng.broker.positions
    assert eng.eod_marked_day == D


def test_day_rollover_marks_missing_eod():
    eng = engine_no_strategies()
    for b in flat_day("MES", D, 5900.0, end=(11, 0)):
        eng.process_bar(b)
    d2 = D + timedelta(days=1)
    for b in flat_day("MES", d2, 5900.0, end=(9, 40)):
        eng.process_bar(b)
    assert eng.eod_marked_day == D
    assert any(e["event"] == "eod_marked" for e in eng.events)


def test_daily_loss_flattens_and_locks():
    from propdesk.domain.models import Bar
    eng = engine_no_strategies()
    for b in flat_day("MNQ", D, 21000.0, step=0.0, wiggle=0.5, end=(10, 0)):
        eng.process_bar(b)
    eng.risk.record_realized(-300)  # earlier losses today
    sig = Signal("orb", "MNQ", Side.LONG, 21000.0, et(D, 10, 0), 20910.0, 21200.0)
    rec = eng.handle_signal(sig)
    assert rec["status"] == "accepted"
    # Gap through the stop: filled at the open, day P&L beyond -500 -> flatten + lock.
    eng.process_bar(Bar("MNQ", et(D, 10, 0), 20800, 20805, 20790, 20800, 1000))
    assert not eng.broker.positions
    assert eng.risk.day_pnl() <= -500
    assert eng.risk.day_lock_reason == "daily_loss_limit"
    assert any(e["event"] == "daily_loss_limit" for e in eng.events)
    again = Signal("orb", "MNQ", Side.LONG, 20800.0, et(D, 10, 2), 20790.0, 20830.0)
    assert eng.handle_signal(again)["reason"].startswith("day_locked")


def test_live_adapters_never_route():
    import pytest
    for broker in (TradovateBroker(enabled_flag=True), IbBroker(enabled_flag=True)):
        with pytest.raises(LiveRoutingDisabledError):
            broker.submit_market("MNQ", Side.LONG, 1, 21000.0, et(D, 10, 0))
        with pytest.raises(LiveRoutingDisabledError):
            broker.flatten(et(D, 10, 0), "manual")
    with pytest.raises(LiveRoutingDisabledError):
        TradovateMarketData(enabled_flag=True).connect()
