"""WebSocket hub: fans the viewed well's live deltas to the browser.

One socket subscribes to exactly one well at a time ("ingest 20, view 1").
On subscribe we hand back a snapshot from the warm ring buffer, then drain the
per-well pub/sub queue the scheduler publishes deltas into. A resubscribe just
swaps the underlying queue. The hub is a thin forwarder — it does not reshape
payloads beyond building the initial snapshot; the scheduler already emits wire
frames via ``sample_to_wire``.

Auth: a ``?token=`` query param is decoded best-effort if the auth module is
present, but is NOT required yet (Phase 7 will enforce it).
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.ingestion.store import get_store, sample_to_wire

log = logging.getLogger("app.ws")


def _maybe_decode_token(token: str | None) -> dict | None:
    """Best-effort JWT decode. Never raises; auth is not enforced until Phase 7."""
    if not token:
        return None
    try:
        from app.auth.security import decode_token  # noqa: PLC0415
    except Exception:  # pragma: no cover - auth module lands in Phase 7
        return None
    try:
        return decode_token(token)
    except Exception:
        log.debug("WS token decode failed (ignored pre-Phase 7)")
        return None


async def _focus(app: FastAPI, well_uid: str) -> None:
    """Ask the scheduler to prioritise this well, if a scheduler is wired."""
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is None:
        return
    focus = getattr(scheduler, "focus", None)
    if focus is None:
        return
    try:
        result = focus(well_uid)
        if asyncio.iscoroutine(result):
            await result
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("scheduler.focus(%s) failed: %s", well_uid, exc)


def _snapshot_frame(well_uid: str) -> dict:
    store = get_store()
    recent = store.get_recent(well_uid, limit=300)
    curves = {mnem: [sample_to_wire(s) for s in samples] for mnem, samples in recent.items()}
    return {"type": "snapshot", "wellUid": well_uid, "curves": curves}


def register_ws(app: FastAPI) -> None:
    """Mount the live WebSocket route at ``/ws``."""

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:  # noqa: C901 - small state machine
        await ws.accept()
        _maybe_decode_token(ws.query_params.get("token"))

        store = get_store()
        current_well: str | None = None
        current_q: asyncio.Queue | None = None
        drain_task: asyncio.Task | None = None

        async def _drain(q: asyncio.Queue) -> None:
            """Forward every queued pub/sub payload to the socket verbatim."""
            while True:
                payload = await q.get()
                await ws.send_json(payload)

        def _stop_drain() -> None:
            nonlocal drain_task
            if drain_task is not None:
                drain_task.cancel()
                drain_task = None

        def _release() -> None:
            """Detach from the current well's pub/sub (idempotent)."""
            nonlocal current_well, current_q
            _stop_drain()
            if current_well is not None and current_q is not None:
                store.unsubscribe(current_well, current_q)
            current_well = None
            current_q = None

        async def _subscribe(well_uid: str) -> None:
            nonlocal current_well, current_q, drain_task
            # Swap off any previous well first.
            _release()
            q = store.subscribe(well_uid)
            current_well = well_uid
            current_q = q
            # Snapshot before the drain so live deltas can't race ahead of it.
            await ws.send_json(_snapshot_frame(well_uid))
            await _focus(app, well_uid)
            drain_task = asyncio.create_task(_drain(q))

        try:
            while True:
                msg = await ws.receive_json()
                if not isinstance(msg, dict):
                    continue
                mtype = msg.get("type")

                if mtype == "subscribe":
                    well_uid = msg.get("wellUid")
                    if isinstance(well_uid, str) and well_uid:
                        await _subscribe(well_uid)
                elif mtype == "unsubscribe":
                    _release()
                elif mtype == "ping":
                    await ws.send_json({"type": "pong"})
                # Unknown frames are ignored (forward-compatible).
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # pragma: no cover - log and tear down cleanly
            log.debug("WS endpoint error: %s", exc)
        finally:
            _release()
