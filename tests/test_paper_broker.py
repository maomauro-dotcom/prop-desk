from __future__ import annotations

from datetime import date, timedelta

import pytest

from conftest import et, make_bar
from propdesk.brokers import BrokerError, PaperBroker
from propdesk.domain.models import OrderStatus, OrderType, Side

D = date(2026, 10, 5)


def test_bracket_target_fills_and_cancels_stop():
    b = PaperBroker()
    t0 = et(D, 10, 0)
    br = b.submit_bracket("MNQ", Side.LONG, 1, stop=20990, target=21020, ts=t0 + timedelta(minutes=1),
                          entry_price=21000)
    assert br.parent.status is OrderStatus.FILLED and br.parent.fill_price == 21000
    assert br.stop.status is OrderStatus.WORKING and br.target.status is OrderStatus.WORKING
    b.on_bar(make_bar("MNQ", t0 + timedelta(minutes=1), 21000, 21025, 20995, 21018))
    assert br.target.status is OrderStatus.FILLED and br.target.fill_price == 21020
    assert br.stop.status is OrderStatus.CANCELLED and br.stop.reason == "oco"
    assert not b.positions
    assert b.trades[0].pnl_usd == pytest.approx(40.0)
    assert b.trades[0].r_multiple == pytest.approx(2.0)


def test_stop_wins_when_both_hit_in_same_bar():
    b = PaperBroker()
    t0 = et(D, 10, 0)
    br = b.submit_bracket("MES", Side.SHORT, 1, stop=5905, target=5895, ts=t0 + timedelta(minutes=1),
                          entry_price=5900)
    b.on_bar(make_bar("MES", t0 + timedelta(minutes=1), 5900, 5906, 5894, 5899))
    assert br.stop.status is OrderStatus.FILLED
    assert br.target.status is OrderStatus.CANCELLED
    assert b.trades[0].pnl_usd == pytest.approx(-25.0)


def test_children_not_evaluated_on_signal_bar():
    b = PaperBroker()
    t0 = et(D, 10, 0)
    br = b.submit_bracket("MNQ", Side.LONG, 1, stop=20990, target=21020, ts=t0 + timedelta(minutes=1),
                          entry_price=21000)
    # Same bar as the signal (opened at t0) is not re-evaluated.
    b.on_bar(make_bar("MNQ", t0, 20980, 21030, 20980, 21000))
    assert br.stop.status is OrderStatus.WORKING


def test_limit_and_stop_entries_gap_fills():
    b = PaperBroker()
    t0 = et(D, 10, 0)
    lim = b.submit_limit("MNQ", Side.LONG, 1, 20990, t0)
    stp = b.submit_stop("MES", Side.SHORT, 1, 5890, t0)
    b.on_bar(make_bar("MNQ", t0, 20985, 20995, 20980, 20992))
    b.on_bar(make_bar("MES", t0, 5885, 5888, 5880, 5884))
    assert lim.fill_price == 20985  # gapped through the limit: fill at open
    assert stp.fill_price == 5885


def test_limit_parent_bracket_and_cancel():
    b = PaperBroker()
    t0 = et(D, 10, 0)
    br = b.submit_bracket("MNQ", Side.LONG, 1, 20980, 21020, t0, entry_type=OrderType.LIMIT, entry_price=20995)
    assert br.stop.status is OrderStatus.PENDING_PARENT
    b.cancel(br.parent.id)
    assert br.stop.status is OrderStatus.CANCELLED and br.target.status is OrderStatus.CANCELLED


def test_flatten_closes_everything():
    b = PaperBroker()
    t0 = et(D, 10, 0)
    b.submit_bracket("MNQ", Side.LONG, 1, 20990, 21020, t0, entry_price=21000)
    b.on_bar(make_bar("MNQ", t0 + timedelta(minutes=1), 21000, 21005, 20995, 21003))
    fills = b.flatten(t0 + timedelta(minutes=2), "manual")
    assert len(fills) == 1 and fills[0].price == 21003
    assert not b.positions and not b.working_orders()


def test_invalid_orders_raise():
    b = PaperBroker()
    t0 = et(D, 10, 0)
    with pytest.raises(BrokerError):
        b.submit_bracket("MNQ", Side.LONG, 1, stop=21010, target=21020, ts=t0, entry_price=21000)
    with pytest.raises(BrokerError):
        b.submit_market("MNQ", Side.LONG, 0, 21000, t0)
    with pytest.raises(BrokerError):
        b.submit_market("XYZ", Side.LONG, 1, 21000, t0)
