"""Dashboard API. Every route requires Authorization: Bearer <DASHBOARD_TOKEN>."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.security import require_dashboard_token
from propdesk.domain.instruments import UnknownSymbolError, normalize_symbol
from propdesk.feeds.csv_feed import CsvFeedError

router = APIRouter(prefix="/api", dependencies=[Depends(require_dashboard_token)])


class StrategyUpdate(BaseModel):
    enabled: bool | None = None
    symbols: list[str] | None = None
    params: dict[str, Any] | None = None


class ProfileUpdate(BaseModel):
    changes: dict[str, Any] = Field(default_factory=dict)


def svc(request: Request):  # noqa: ANN201
    return request.app.state.service


def _symbol(symbol: str) -> str:
    try:
        return normalize_symbol(symbol)
    except UnknownSymbolError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None


@router.get("/state")
def state(request: Request) -> dict[str, Any]:
    return svc(request).state()


@router.get("/meta")
def meta(request: Request) -> dict[str, Any]:
    return svc(request).meta()


@router.get("/strategies")
def strategies(request: Request) -> list[dict[str, Any]]:
    return svc(request).state()["strategies"]


@router.put("/strategies/{strategy_id}")
def update_strategy(strategy_id: str, body: StrategyUpdate, request: Request) -> dict[str, Any]:
    try:
        return svc(request).update_strategy(strategy_id, body.enabled, body.symbols, body.params)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"estrategia desconocida: {strategy_id}") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/risk")
def risk(request: Request) -> dict[str, Any]:
    return svc(request).state()["account"]


@router.get("/risk/profile")
def get_profile(request: Request) -> dict[str, Any]:
    return svc(request).engine.profile.to_dict()


@router.put("/risk/profile")
def put_profile(body: ProfileUpdate, request: Request) -> dict[str, Any]:
    try:
        return svc(request).update_profile(body.changes)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/positions")
def positions(request: Request) -> dict[str, Any]:
    st = svc(request).state()
    return {"positions": st["positions"], "working_orders": st["working_orders"]}


@router.get("/signals")
def signals(request: Request, limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
    return svc(request).state()["signals"][:limit]


@router.get("/events")
def events(request: Request, limit: int = Query(100, ge=1, le=1000)) -> list[dict[str, Any]]:
    return svc(request).state()["events"][:limit]


@router.get("/trades")
def trades(request: Request) -> list[dict[str, Any]]:
    return svc(request).state()["trades"]


@router.get("/equity")
def equity(request: Request) -> list[dict[str, Any]]:
    return svc(request).state()["equity_curve"]


@router.get("/session")
def session(request: Request) -> dict[str, Any]:
    return svc(request).state()["session"]


@router.get("/session/{symbol}")
def session_symbol(symbol: str, request: Request) -> dict[str, Any]:
    sym = _symbol(symbol)
    sess = svc(request).state()["session"].get(sym)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"sin barras de sesión para {sym}")
    return sess


@router.get("/bars/{symbol}")
def bars(symbol: str, request: Request, limit: int = Query(60, ge=1, le=2000)) -> list[dict[str, Any]]:
    return svc(request).recent_bars(_symbol(symbol), limit)


@router.post("/sim/replay")
async def replay(request: Request) -> dict[str, Any]:
    try:
        return await run_in_threadpool(svc(request).replay_sample)
    except CsvFeedError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"CSV de muestra inválido: {exc}") from None


@router.post("/sim/reset")
def reset(request: Request) -> dict[str, Any]:
    return svc(request).reset_simulation()


@router.post("/flatten")
def flatten(request: Request) -> dict[str, Any]:
    return svc(request).manual_flatten()


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    service = svc(request)

    async def gen():
        yield "event: hello\ndata: {\"type\":\"hello\"}\n\n"
        async for data in service.broadcaster.subscribe():
            if await request.is_disconnected():
                break
            yield f"data: {data}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
