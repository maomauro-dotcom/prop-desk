"""CSV bar feed. Columns: timestamp,symbol,open,high,low,close,volume (naive timestamps = ET)."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

from propdesk.domain.clock import parse_timestamp
from propdesk.domain.instruments import normalize_symbol
from propdesk.domain.models import Bar

REQUIRED_COLUMNS = ("timestamp", "symbol", "open", "high", "low", "close", "volume")


class CsvFeedError(ValueError):
    pass


class CsvBarFeed:
    def __init__(self, path: str | Path, symbols: set[str] | None = None) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise CsvFeedError(f"CSV not found: {self.path}")
        self.symbols = {normalize_symbol(s) for s in symbols} if symbols else None

    def load(self) -> list[Bar]:
        bars: list[Bar] = []
        with self.path.open(newline="") as fh:
            reader = csv.DictReader(fh)
            missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                raise CsvFeedError(f"{self.path}: missing columns {missing}")
            for lineno, row in enumerate(reader, start=2):
                try:
                    symbol = normalize_symbol(row["symbol"])
                    if self.symbols and symbol not in self.symbols:
                        continue
                    bars.append(Bar(
                        symbol=symbol,
                        timestamp=parse_timestamp(row["timestamp"]),
                        open=float(row["open"]), high=float(row["high"]),
                        low=float(row["low"]), close=float(row["close"]),
                        volume=float(row["volume"]),
                    ))
                except (KeyError, ValueError) as exc:
                    raise CsvFeedError(f"{self.path}:{lineno}: {exc}") from exc
        bars.sort(key=lambda b: (b.timestamp, b.symbol))
        return bars

    def __iter__(self) -> Iterator[Bar]:
        return iter(self.load())
