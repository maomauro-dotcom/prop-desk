from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
def health(request: Request) -> dict:
    s = request.app.state.settings
    # Mode is always paper: the live adapters refuse to route even if their flags are true.
    return {"status": "ok", "mode": "paper", "tradovate_enabled": s.tradovate_enabled, "ib_enabled": s.ib_enabled}
