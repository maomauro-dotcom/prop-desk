"""Parsing and authentication helpers for the TradingView bar webhook."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from propdesk.domain.clock import parse_timestamp
from propdesk.domain.instruments import normalize_symbol
from propdesk.domain.models import Bar

ACCEPTED_TIMEFRAMES = {"1", "1m", "1min", "60s"}


class WebhookPayloadError(ValueError):
    pass


def secret_matches(provided: str | None, expected: str | None) -> bool:
    """Constant-time comparison of SHA-256 digests. Empty expected secret rejects everything."""
    if not expected or not provided:
        return False
    a = hashlib.sha256(provided.encode("utf-8")).digest()
    b = hashlib.sha256(expected.encode("utf-8")).digest()
    return hmac.compare_digest(a, b)


def bar_from_payload(payload: dict[str, Any]) -> Bar:
    """Build a Bar from the Pine bridge JSON. Naive timestamps are America/New_York."""
    try:
        tf = str(payload.get("timeframe", "1")).strip().lower()
        if tf not in ACCEPTED_TIMEFRAMES:
            raise WebhookPayloadError(f"only 1-minute bars are accepted, got timeframe={tf!r}")
        return Bar(
            symbol=normalize_symbol(str(payload["symbol"])),
            timestamp=parse_timestamp(payload["timestamp"]),
            open=float(payload["open"]),
            high=float(payload["high"]),
            low=float(payload["low"]),
            close=float(payload["close"]),
            volume=float(payload.get("volume", 0) or 0),
        )
    except KeyError as exc:
        raise WebhookPayloadError(f"missing field {exc.args[0]!r}") from exc
    except (TypeError, ValueError) as exc:
        if isinstance(exc, WebhookPayloadError):
            raise
        raise WebhookPayloadError(str(exc)) from exc
