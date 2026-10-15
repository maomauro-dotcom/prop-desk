"""Backtest one strategy on one symbol through the full engine (risk + paper broker + flatten/EOD).

    python -m propdesk.backtest --strategy orb --symbol MNQ [--csv data/sample_rth_mnq_mes.csv]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from propdesk.domain.instruments import normalize_symbol
from propdesk.domain.models import Trade
from propdesk.domain.profile import PROFILE_NOTICE_ES, RiskProfile
from propdesk.engine.engine import TradingEngine
from propdesk.feeds.csv_feed import CsvBarFeed
from propdesk.paths import SAMPLE_CSV
from propdesk.strategies import build_default_strategies, resolve_strategy_id

TRAIL_REASONS = {"cushion_below_floor", "risk_exceeds_cushion_cap", "account_breached"}


@dataclass
class BacktestReport:
    strategy_id: str
    symbol: str
    csv: str
    trades: list[Trade]
    signals: int
    accepted: int
    rejections: dict[str, int]
    win_rate: float
    avg_r: float | None
    net_pnl: float
    max_drawdown: float
    trail_blocked_entries: int
    trail_breached: bool
    trail_locked: bool
    final_balance: float
    final_floor: float
    eod: list[dict[str, Any]] = field(default_factory=list)


def run_backtest(strategy: str, symbol: str, csv_path: str | Path | None = None,
                 profile: RiskProfile | None = None) -> BacktestReport:
    sid = resolve_strategy_id(strategy)
    sym = normalize_symbol(symbol)
    strategies = build_default_strategies()
    for k, s in strategies.items():
        s.enabled = k == sid
        s.symbols = {sym} if k == sid else set()
    engine = TradingEngine(profile=profile or RiskProfile(), strategies=strategies)
    path = Path(csv_path) if csv_path else SAMPLE_CSV
    engine.replay(CsvBarFeed(path, symbols={sym}))

    trades = list(engine.broker.trades)
    wins = [t for t in trades if t.pnl_usd > 0]
    rs = [t.r_multiple for t in trades if t.r_multiple is not None]
    # Max drawdown on the mark-to-market equity curve.
    peak, mdd = float("-inf"), 0.0
    for pt in engine.equity_curve:
        peak = max(peak, pt["equity"])
        mdd = max(mdd, peak - pt["equity"])
    rejections: dict[str, int] = {}
    for s in engine.signals:
        if s["status"] == "rejected":
            rejections[s["reason"]] = rejections.get(s["reason"], 0) + 1
    return BacktestReport(
        strategy_id=sid, symbol=sym, csv=str(path), trades=trades,
        signals=len(engine.signals), accepted=sum(1 for s in engine.signals if s["status"] == "accepted"),
        rejections=rejections,
        win_rate=(len(wins) / len(trades)) if trades else 0.0,
        avg_r=(sum(rs) / len(rs)) if rs else None,
        net_pnl=sum(t.pnl_usd for t in trades),
        max_drawdown=mdd,
        trail_blocked_entries=sum(v for k, v in rejections.items() if k in TRAIL_REASONS),
        trail_breached=engine.risk.breached,
        trail_locked=engine.risk.trail_locked,
        final_balance=engine.risk.balance,
        final_floor=engine.risk.trail_floor,
        eod=[r.to_dict() for r in engine.risk.eod_history],
    )


def format_report(rep: BacktestReport) -> str:
    lines = [
        f"Backtest {rep.strategy_id} · {rep.symbol} · {rep.csv}",
        "AVISO: datos sintéticos de muestra (no es grabación del CME). " + PROFILE_NOTICE_ES,
        "",
        f"{'entrada':<17} {'salida':<6} {'lado':<5} {'qty':>3} {'precio in':>10} {'precio out':>10} "
        f"{'P&L USD':>9} {'R':>6}  motivo",
    ]
    for t in rep.trades:
        lines.append(
            f"{t.entry_time.strftime('%Y-%m-%d %H:%M'):<17} {t.exit_time.strftime('%H:%M'):<6} {t.side.value:<5} "
            f"{t.qty:>3} {t.entry_price:>10.2f} {t.exit_price:>10.2f} {t.pnl_usd:>9.2f} "
            f"{(f'{t.r_multiple:.2f}' if t.r_multiple is not None else '-'):>6}  {t.exit_reason}")
    if not rep.trades:
        lines.append("(sin operaciones)")
    lines += [
        "",
        f"Señales: {rep.signals} · aceptadas: {rep.accepted} · rechazos: {rep.rejections or '{}'}",
        f"Operaciones: {len(rep.trades)}",
        f"Win rate: {rep.win_rate * 100:.1f}%",
        f"R medio: {rep.avg_r:.3f}" if rep.avg_r is not None else "R medio: n/a",
        f"P&L neto: {rep.net_pnl:.2f} USD",
        f"Max drawdown: {rep.max_drawdown:.2f} USD",
        f"Entradas bloqueadas por el trail/colchón: {rep.trail_blocked_entries}",
        f"¿El trail habría bloqueado la cuenta?: {'sí' if rep.trail_breached else 'no'}"
        f" · trail bloqueado en saldo inicial: {'sí' if rep.trail_locked else 'no'}",
        f"Saldo final: {rep.final_balance:.2f} · piso del trail: {rep.final_floor:.2f}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m propdesk.backtest", description="Backtest paper de una estrategia")
    ap.add_argument("--strategy", required=True, help="orb | vwap | sweep (o el id completo)")
    ap.add_argument("--symbol", required=True, help="MNQ | MES")
    ap.add_argument("--csv", default=None, help="CSV de barras de 1 minuto (por defecto el de muestra)")
    args = ap.parse_args(argv)
    try:
        rep = run_backtest(args.strategy, args.symbol, args.csv)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(format_report(rep))
    return 0
