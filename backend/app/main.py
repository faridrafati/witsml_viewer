"""FastAPI application entrypoint.

Wires the REST API, health probe, and (as phases land) the ingestion
scheduler and WebSocket hub. Startup creates DB tables and seeds reference
data best-effort so a fresh `docker compose up` is immediately usable.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.router import api_router
from app.config import settings

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── startup ──
    try:
        from app.db.base import init_models

        await init_models()
        log.info("DB schema ready.")
    except Exception as exc:  # pragma: no cover
        log.error("init_models failed: %s", exc)

    try:
        from app.db.seed import run_seed

        await run_seed()
    except Exception as exc:  # pragma: no cover
        log.warning("seed failed (continuing): %s", exc)

    # Ingestion scheduler is started here once Phase 2 lands.
    scheduler = None
    try:
        from app.ingestion.scheduler import IngestionScheduler

        scheduler = IngestionScheduler()
        await scheduler.start()
        app.state.scheduler = scheduler
        log.info("Ingestion scheduler started.")
    except Exception as exc:  # pragma: no cover - not present until Phase 2
        log.info("Ingestion scheduler not started: %s", exc)

    yield

    # ── shutdown ──
    if scheduler is not None:
        try:
            await scheduler.stop()
        except Exception as exc:  # pragma: no cover
            log.warning("scheduler stop failed: %s", exc)


app = FastAPI(
    title="WITSML Mudlogging Monitor",
    version="0.1.0",
    description="WITSML 1.4.1.1 mudlogging real-time monitoring & data management BFF.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev-permissive; tighten in production.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(api_router)


# WebSocket hub is mounted here once Phase 2 lands.
try:
    from app.ws.hub import register_ws

    register_ws(app)
except Exception:  # pragma: no cover - not present until Phase 2
    pass
