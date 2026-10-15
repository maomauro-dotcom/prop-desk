"""FastAPI application factory.

    uvicorn backend.app:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import Settings
from backend.db import make_engine, make_session_factory
from backend.routes import api, health, webhook
from backend.service import DeskService

log = logging.getLogger("propdesk.backend")


def create_app(settings: Settings | None = None, start_clock: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()
    if not settings.dashboard_token:
        log.warning("DASHBOARD_TOKEN vacío: todas las rutas /api rechazarán peticiones")
    if not settings.webhook_secret:
        log.warning("WEBHOOK_SECRET vacío: /webhook/bars rechazará peticiones")
    if settings.tradovate_enabled or settings.ib_enabled:
        log.warning("TRADOVATE_ENABLED/IB_ENABLED están en true, pero esta versión NO envía órdenes live")
    db_engine = make_engine(settings.database_url)
    service = DeskService(settings, make_session_factory(db_engine))

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        service.broadcaster.bind_loop(asyncio.get_running_loop())
        task = asyncio.create_task(_clock_loop(service, settings.clock_interval_s)) if start_clock else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            db_engine.dispose()

    app = FastAPI(title="Mesa de micros (paper)", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.service = service
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "OPTIONS"],
                       allow_headers=["Authorization", "Content-Type", "X-Webhook-Secret"])
    app.include_router(health.router)
    app.include_router(webhook.router)
    app.include_router(api.router)
    return app


async def _clock_loop(service: DeskService, interval: float) -> None:
    """Session clock: forces the 15:55 ET flatten + EOD mark even if no bar arrives."""
    while True:
        try:
            await asyncio.to_thread(service.clock_tick)
        except Exception:  # noqa: BLE001 - log loudly, keep the clock alive
            log.exception("clock tick failed")
        await asyncio.sleep(interval)


def _default_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return create_app()


_app: FastAPI | None = None


def __getattr__(name: str) -> FastAPI:
    """Lazy `backend.app:app` so importing this module (tests, MCP) never touches the DB."""
    global _app
    if name == "app":
        if _app is None:
            _app = _default_app()
        return _app
    raise AttributeError(name)
