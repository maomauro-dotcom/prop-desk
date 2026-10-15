"""Generate data/sample_rth_mnq_mes.csv: SYNTHETIC 1-minute RTH bars for MNQ and MES.

This is NOT a CME recording. Each day follows a scripted path (Brownian bridge between
waypoints) so that ORB, VWAP pullback/reclaim and liquidity sweep setups appear.
Deterministic: same seed -> same file.

    python scripts/make_sample_data.py [--out data/sample_rth_mnq_mes.csv] [--seed 7]
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

MINUTES = 390  # 09:30 .. 15:59
BASE = {"MNQ": 21000.0, "MES": 5900.0}
BETA = {"MNQ": 1.0, "MES": 0.8}
SIGMA_PCT = 0.040  # per-minute sigma, % of price
WICK = 0.45  # wick size, in sigmas

# (minute index, % move from the day's open). Day open gap is relative to the prior close.
DAYS: list[tuple[date, float, list[tuple[int, float]]]] = [
    # Trend-up day: tight opening range, volume breakout up, VWAP pullbacks, drift up.
    (date(2026, 10, 5), 0.0, [(0, 0.0), (5, 0.10), (10, -0.06), (14, 0.04), (18, 0.30), (40, 0.55), (70, 0.70),
                              (95, 0.42), (130, 0.80), (170, 0.95), (210, 0.70), (260, 0.90), (330, 1.05),
                              (389, 0.95)]),
    # Gap down, sweep below previous-day low then V reversal; afternoon reclaim of VWAP.
    (date(2026, 10, 6), -0.70, [(0, 0.0), (6, -0.15), (14, 0.05), (20, -0.40), (24, 0.05), (45, 0.30), (80, 0.10),
                                (120, -0.25), (150, -0.35), (175, -0.05), (200, 0.25), (240, 0.10),
                                (300, 0.35), (389, 0.30)]),
    # Trend-down day: breakdown of the opening range, VWAP pullbacks short.
    (date(2026, 10, 7), 0.25, [(0, 0.0), (6, -0.08), (12, 0.08), (15, -0.02), (20, -0.30), (45, -0.55),
                               (75, -0.70), (100, -0.45), (135, -0.85), (175, -1.00), (215, -0.80),
                               (265, -1.05), (330, -1.15), (389, -1.00)]),
    # Range day: sweep of the opening-range high and fade, sweep of the low later.
    (date(2026, 10, 8), 0.15, [(0, 0.0), (7, 0.18), (14, -0.10), (30, 0.10), (36, 0.32), (40, 0.05),
                               (80, -0.20), (110, -0.05), (150, -0.32), (155, -0.08), (200, 0.05),
                               (260, -0.10), (320, 0.12), (389, 0.05)]),
    # Up open, failed breakout, reclaim then drift.
    (date(2026, 10, 9), 0.30, [(0, 0.0), (8, -0.12), (14, 0.10), (19, 0.28), (30, 0.10), (60, -0.25),
                               (90, -0.40), (115, -0.15), (140, 0.15), (180, 0.30), (230, 0.20), (300, 0.45),
                               (389, 0.40)]),
]


def bridge(rng: random.Random, p0: float, p1: float, n: int, sigma: float) -> list[float]:
    walk = [0.0]
    for _ in range(n):
        walk.append(walk[-1] + rng.gauss(0.0, sigma))
    return [p0 + (p1 - p0) * i / n + (walk[i] - walk[n] * i / n) for i in range(1, n + 1)]


def day_path(rng: random.Random, waypoints: list[tuple[int, float]], sigma: float) -> list[float]:
    path = [waypoints[0][1]]
    for (t0, p0), (t1, p1) in zip(waypoints, waypoints[1:]):
        path.extend(bridge(rng, p0, p1, t1 - t0, sigma))
    assert len(path) == MINUTES, len(path)
    return path


def tick(x: float) -> float:
    return round(x * 4) / 4


def volume_profile(i: int) -> float:
    u = i / (MINUTES - 1)
    return 0.65 + 1.6 * math.exp(-u * 9) + 0.7 * math.exp(-(1 - u) * 10)


def generate(seed: int) -> list[dict[str, object]]:
    rng = random.Random(seed)
    rows: list[dict[str, object]] = []
    prev_close_pct = 0.0
    for d, gap, wps in DAYS:
        open_pct = prev_close_pct + gap
        common = day_path(rng, wps, SIGMA_PCT * 0.85)
        for sym in ("MNQ", "MES"):
            idio = day_path(rng, [(0, 0.0), (MINUTES - 1, 0.0)], SIGMA_PCT * 0.25)
            base = BASE[sym]
            sigma_pts = base * SIGMA_PCT / 100
            pct = [open_pct + BETA[sym] * (c + e) for c, e in zip(common, idio)]
            closes = [base * (1 + p / 100) for p in pct]
            prev = base * (1 + open_pct / 100)
            base_vol = 1500 if sym == "MNQ" else 2600
            for i, c in enumerate(closes):
                o = prev
                hi = max(o, c) + abs(rng.gauss(0, WICK * sigma_pts))
                lo = min(o, c) - abs(rng.gauss(0, WICK * sigma_pts))
                move = abs(c - o) / sigma_pts
                vol = base_vol * volume_profile(i) * math.exp(rng.gauss(0, 0.25)) * (0.7 + 0.45 * min(move, 4))
                ts = datetime.combine(d, time(9, 30)) + timedelta(minutes=i)
                o_t, c_t = tick(o), tick(c)
                rows.append({
                    "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                    "symbol": sym,
                    "open": f"{o_t:.2f}",
                    "high": f"{max(tick(hi), o_t, c_t):.2f}",
                    "low": f"{min(tick(lo), o_t, c_t):.2f}",
                    "close": f"{c_t:.2f}",
                    "volume": int(vol),
                })
                prev = c
        prev_close_pct = open_pct + common[-1]
    rows.sort(key=lambda r: (r["timestamp"], r["symbol"]))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "data" / "sample_rth_mnq_mes.csv"))
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rows = generate(args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["timestamp", "symbol", "open", "high", "low", "close", "volume"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} bars to {out}")


if __name__ == "__main__":
    main()
