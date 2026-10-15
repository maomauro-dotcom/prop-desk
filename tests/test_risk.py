from __future__ import annotations

from datetime import date

import pytest

from conftest import et
from propdesk.domain.models import Side, Signal
from propdesk.domain.profile import RiskProfile
from propdesk.engine.risk import RiskManager

D = date(2026, 10, 5)


def sig(symbol: str = "MNQ", price: float = 21000.0, stop: float = 20950.0, side: Side = Side.LONG) -> Signal:
    target = price + 2 * abs(price - stop) * side.sign
    return Signal("orb", symbol, side, price, et(D, 10, 0), stop, target)


def fresh(**changes) -> RiskManager:
    rm = RiskManager(RiskProfile().updated(changes) if changes else RiskProfile())
    rm.start_day(D)
    return rm


# ---------------------------------------------------------------- cushion caps
def test_risk_per_trade_capped_at_15_percent_of_cushion():
    rm = fresh()
    assert rm.cushion() == 2000
    # 15% of 2000 = 300 USD. MNQ = 2 USD/pt -> 150 pts max.
    ok = rm.evaluate_entry(sig(stop=21000 - 150), et(D, 10, 0), 0, set())
    assert ok.accepted and ok.qty == 1
    assert ok.details["max_risk_usd"] == 300.0
    too_big = rm.evaluate_entry(sig(stop=21000 - 150.25), et(D, 10, 0), 0, set())
    assert not too_big.accepted and too_big.reason == "risk_exceeds_cushion_cap"


def test_cap_shrinks_with_cushion():
    rm = fresh()
    rm.balance = 49_000  # cushion 1000 -> cap 150 USD = 75 MNQ points
    assert rm.cushion() == 1000
    assert rm.evaluate_entry(sig(stop=21000 - 75), et(D, 10, 0), 0, set()).accepted
    assert not rm.evaluate_entry(sig(stop=21000 - 80), et(D, 10, 0), 0, set()).accepted


def test_no_entry_when_cushion_below_40_percent_of_trail():
    rm = fresh()
    rm.balance = 48_000 + 799  # cushion 799 < 800
    d = rm.evaluate_entry(sig(stop=20995), et(D, 10, 0), 0, set())
    assert not d.accepted and d.reason == "cushion_below_floor"
    rm.balance = 48_000 + 800  # exactly at the floor is allowed
    assert rm.evaluate_entry(sig(stop=20995), et(D, 10, 0), 0, set()).accepted


def test_unrealized_loss_counts_against_cushion():
    rm = fresh()
    d = rm.evaluate_entry(sig(stop=20995), et(D, 10, 0), 0, set(), unrealized=-1250)
    assert not d.accepted  # 750 cushion; the -1250 also breaches daily loss
    assert d.reason in {"daily_loss_limit", "cushion_below_floor"}


# ------------------------------------------------------------------ EOD trail
def test_trail_follows_eod_peak_and_locks_at_starting_balance():
    rm = fresh()
    assert rm.trail_floor == 48_000 and not rm.trail_locked
    rm.record_realized(400)
    rec = rm.mark_eod(D)
    assert rec.peak == 50_400 and rm.trail_floor == 48_400
    # A losing day does not lower the floor.
    d2 = date(2026, 10, 6)
    rm.start_day(d2)
    rm.record_realized(-300)
    rm.mark_eod(d2)
    assert rm.balance == 50_100 and rm.trail_floor == 48_400
    # Big day: peak 52_500 -> peak - trail = 50_500 > 50_000 -> floor locks at 50_000.
    d3 = date(2026, 10, 7)
    rm.start_day(d3)
    rm.record_realized(2_400)
    rm.mark_eod(d3)
    assert rm.peak_eod_balance == 52_500
    assert rm.trail_floor == 50_000 and rm.trail_locked
    # Further highs never move the locked floor.
    d4 = date(2026, 10, 8)
    rm.start_day(d4)
    rm.record_realized(1_000)
    rm.mark_eod(d4)
    assert rm.trail_floor == 50_000


def test_intraday_does_not_move_trail():
    rm = fresh()
    rm.record_realized(900)
    assert rm.trail_floor == 48_000  # only EOD moves it
    assert rm.cushion() == 2_900


def test_mark_eod_resets_day_counters():
    rm = fresh()
    rm.record_entry()
    rm.record_realized(-100)
    rm.mark_eod(D)
    assert rm.entries_today == 0 and rm.day_realized == 0 and rm.balance == 49_900


# ------------------------------------------------------------- hard limits
def test_minis_blocked():
    rm = fresh()
    for sym in ("NQ", "ES", "CME_MINI:NQ1!"):
        d = rm.evaluate_entry(sig(symbol=sym, stop=20999), et(D, 10, 0), 0, set())
        assert not d.accepted and d.reason == "mini_blocked"


def test_minis_cannot_be_unblocked():
    with pytest.raises(ValueError, match="minis"):
        RiskProfile().updated({"block_minis": False})


def test_size_never_above_two_micros():
    with pytest.raises(ValueError):
        RiskProfile(max_contracts=3).validate()
    with pytest.raises(ValueError):
        RiskProfile(default_contracts=3, max_contracts=2).validate()
    rm = fresh(default_contracts=2)
    d = rm.evaluate_entry(sig(stop=20990), et(D, 10, 0), 0, set())
    assert d.accepted and d.qty == 2
    d = rm.evaluate_entry(sig(symbol="MES", price=5900, stop=5898), et(D, 10, 0), 1, {"MNQ"})
    assert d.accepted and d.qty == 1  # only 1 slot left
    d = rm.evaluate_entry(sig(symbol="MES", price=5900, stop=5898), et(D, 10, 0), 2, {"MNQ"})
    assert not d.accepted and d.reason == "max_contracts"


def test_daily_loss_blocks_entries():
    rm = fresh()
    rm.record_realized(-500)
    d = rm.evaluate_entry(sig(stop=20995), et(D, 10, 0), 0, set())
    assert not d.accepted and d.reason == "daily_loss_limit"


def test_daily_loss_lock_from_intraday_check():
    rm = fresh()
    assert rm.check_intraday(-499) is None
    assert rm.check_intraday(-500) == "daily_loss_limit"
    d = rm.evaluate_entry(sig(stop=20995), et(D, 10, 0), 0, set(), unrealized=0)
    assert not d.accepted and d.reason.startswith("day_locked")


def test_risk_capped_by_remaining_daily_loss():
    rm = fresh()
    rm.record_realized(-400)  # 100 USD of daily loss left -> 50 MNQ pts
    assert rm.evaluate_entry(sig(stop=20950), et(D, 10, 0), 0, set()).accepted
    d = rm.evaluate_entry(sig(stop=20949), et(D, 10, 0), 0, set())
    assert not d.accepted and d.reason == "risk_exceeds_cushion_cap"


def test_max_entries_per_day():
    rm = fresh()
    for _ in range(4):
        rm.record_entry()
    d = rm.evaluate_entry(sig(stop=20995), et(D, 10, 0), 0, set())
    assert not d.accepted and d.reason == "max_entries_per_day"


def test_no_entry_after_flatten_cutoff():
    rm = fresh()
    assert not rm.evaluate_entry(sig(stop=20995), et(D, 15, 55), 0, set()).accepted
    assert rm.evaluate_entry(sig(stop=20995), et(D, 15, 54), 0, set()).accepted
