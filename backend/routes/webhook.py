"""TradingView bar webhook. The secret travels in the JSON body (`secret`) or X-Webhook-Secret."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool

from propdesk.domain.clock import is_rth
from propdesk.feeds.webhook import WebhookPayloadError, bar_from_payload, secret_matches

router = APIRouter()


@router.post("/webhook/bars")
async def webhook_bars(request: Request, x_webhook_secret: str | None = Header(default=None)) -> dict[str, Any]:
    settings = request.app.state.settings
    if not settings.webhook_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "WEBHOOK_SECRET no configurado: el webhook rechaza todas las peticiones")
    raw = await request.body()
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        # Still authenticate by header first so we don't leak parse details to strangers.
        if not secret_matches(x_webhook_secret, settings.webhook_secret):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "secreto inválido") from None
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"JSON inválido: {exc}") from None
    if not isinstance(payload, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "se espera un objeto JSON")
    provided = payload.pop("secret", None) or x_webhook_secret
    if not secret_matches(provided if isinstance(provided, str) else None, settings.webhook_secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "secreto inválido")
    try:
        bar = bar_from_payload(payload)
    except WebhookPayloadError as exc:
        raise HTTPException(422, f"payload inválido: {exc}") from None
    if not is_rth(bar.timestamp):
        return {"status": "ignored", "reason": "outside_rth", "symbol": bar.symbol,
                "timestamp": bar.timestamp.isoformat()}
    service = request.app.state.service
    try:
        records = await run_in_threadpool(service.ingest_bar, bar, "webhook")
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"barra rechazada: {exc}") from None
    return {
        "status": "accepted",
        "symbol": bar.symbol,
        "timestamp": bar.timestamp.isoformat(),
        "signals": [{k: r[k] for k in ("strategy_id", "symbol", "side", "price", "status", "reason")} for r in records],
    }
