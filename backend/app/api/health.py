"""Liveness / readiness endpoints (compose healthcheck hits /health)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from app.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Cheap liveness probe — no external calls."""
    return {
        "status": "ok",
        "service": "witsml-mudlogging-api",
        "witsml_version_target": "1.4.1.1",
        "witsml_url": settings.witsml_url,
        "time": datetime.now(UTC).isoformat(),
    }
