"""Aggregate REST router mounted under /api.

Feature routers are attached here as phases land. Discovery (Phase 1) is
imported defensively so the app still boots if that module is mid-build.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

api_router = APIRouter(prefix="/api")
log = logging.getLogger(__name__)

# Phase 1 — discovery (wells/wellbores/logs/cap). Wired in when present.
try:
    from app.api import discovery

    api_router.include_router(discovery.router)
except Exception as exc:  # pragma: no cover - defensive during incremental build
    log.warning("discovery router not mounted: %s", exc)
