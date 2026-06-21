"""Aggregate REST router mounted under /api.

Feature routers are attached here as phases land. Each is imported defensively
so the app still boots if a module is mid-build or has an import error.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

api_router = APIRouter(prefix="/api")
log = logging.getLogger(__name__)

# (module, attribute) pairs — all expose `router: APIRouter`.
_FEATURE_MODULES = [
    "app.api.discovery",  # Phase 1 — wells/wellbores/logs/cap/tree
    "app.api.curves",  # Phase 2 — ingested curve data (/ingest)
    "app.api.units",  # Phase 3 — unit defs + safe formula convert (/units)
    "app.api.pages",  # Phase 3 — dashboard pages CRUD (/pages)
    "app.api.parameters",  # Phase 3 — parameter catalog CRUD (/parameters)
    "app.api.store_write",  # Phase 4 — write path (/store)
    "app.api.comparison",  # Phase 5 — multi-well comparison + lithology (/comparison)
    "app.api.formulas",  # Phase 6 — drilling-hydraulics formulas (/formulas)
    "app.api.export",  # Phase 6 — Excel/PDF export (/export)
    "app.api.auth",  # Phase 7 — login / me (/auth)
    "app.api.admin",  # Phase 7 — users + page grants (/admin)
    "app.api.servers",  # Phase 7 — WITSML server connections (/servers)
    "app.api.reports",  # Phase 7 — reporting: remarks, mud properties, ... (/reports)
]

for _mod in _FEATURE_MODULES:
    try:
        module = __import__(_mod, fromlist=["router"])
        api_router.include_router(module.router)
    except Exception as exc:  # pragma: no cover - defensive during incremental build
        log.warning("router %s not mounted: %s", _mod, exc)
