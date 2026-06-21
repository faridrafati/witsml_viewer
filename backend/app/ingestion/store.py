"""In-memory warm store: per-well ring buffers, index-cache state, pub/sub.

This is the kernel of the "ingest 20, view 1" strategy. The scheduler writes
ingested samples here; the WebSocket hub fans the viewed well's deltas to
subscribers; the REST curve API reads recent samples for back-fill. Index
state is kept so the scheduler resumes incrementally (and is snapshotted to
Postgres by the scheduler).

Redis is optional — when unavailable this in-process implementation is the
fallback (single-process dev). The pub/sub surface (subscribe/unsubscribe/
publish) is intentionally Redis-shaped so a Redis fan-out can slot in later.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache

from pydantic import BaseModel

from app.config import settings
from app.domain.models import CurveSample
from app.witsml.constants import Direction, IndexType

# (server_id, well_uid, wellbore_uid, log_uid)
LogKey = tuple[int, str, str, str]

IndexValue = float | datetime


@dataclass
class LogState:
    """Resumable per-log ingestion state (the index cache)."""

    server_id: int
    well_uid: str
    wellbore_uid: str
    log_uid: str
    index_type: IndexType
    direction: Direction
    index_uom: str | None = None
    index_mnemonic: str = ""
    mnemonics: list[str] = field(default_factory=list)
    last_index: IndexValue | None = None
    object_growing: bool | None = None

    @property
    def key(self) -> LogKey:
        return (self.server_id, self.well_uid, self.wellbore_uid, self.log_uid)


class WellStatus(BaseModel):
    """Cross-well status surfaced to the UI (keeps all 20 wells 'warm')."""

    well_uid: str
    name: str | None = None
    region: str | None = None
    growing: bool = False
    last_update: datetime | None = None
    sample_count: int = 0
    mnemonics: list[str] = []


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RingBufferStore:
    """Bounded per-(well, mnemonic) sample buffers + log state + pub/sub."""

    def __init__(self, max_samples_per_curve: int = 10_000) -> None:
        self.max_samples = max_samples_per_curve
        self._curves: dict[tuple[str, str], deque[CurveSample]] = defaultdict(
            lambda: deque(maxlen=self.max_samples)
        )
        self._log_states: dict[LogKey, LogState] = {}
        self._well_meta: dict[str, dict] = {}
        self._last_update: dict[str, datetime] = {}
        # well_uid -> set of bounded subscriber queues (WS fan-out).
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

    # ── sample ingestion ────────────────────────────────────────────────
    def append(self, well_uid: str, log_uid: str, samples: list[CurveSample]) -> None:
        if not samples:
            return
        for s in samples:
            self._curves[(well_uid, s.mnemonic)].append(s)
        self._last_update[well_uid] = _utcnow()

    def get_recent(
        self,
        well_uid: str,
        mnemonics: list[str] | None = None,
        *,
        since: IndexValue | None = None,
        limit: int | None = None,
    ) -> dict[str, list[CurveSample]]:
        out: dict[str, list[CurveSample]] = {}
        keys = (
            [(well_uid, m) for m in mnemonics]
            if mnemonics
            else [k for k in self._curves if k[0] == well_uid]
        )
        for key in keys:
            buf = self._curves.get(key)
            if not buf:
                continue
            mnem = key[1]
            items = list(buf)
            if since is not None:
                items = [s for s in items if _gt(s.index, since)]
            if limit is not None:
                items = items[-limit:]
            out[mnem] = items
        return out

    def curve_mnemonics(self, well_uid: str) -> list[str]:
        return sorted({k[1] for k in self._curves if k[0] == well_uid})

    # ── well metadata / status ──────────────────────────────────────────
    def set_well_meta(self, well_uid: str, name: str | None, region: str | None) -> None:
        self._well_meta[well_uid] = {"name": name, "region": region}

    def well_uids(self) -> list[str]:
        uids = set(self._well_meta) | {k[0] for k in self._curves}
        return sorted(uids)

    def well_status(self) -> list[WellStatus]:
        out: list[WellStatus] = []
        for uid in self.well_uids():
            meta = self._well_meta.get(uid, {})
            mnems = self.curve_mnemonics(uid)
            count = sum(len(self._curves[(uid, m)]) for m in mnems)
            growing = any(
                st.object_growing for st in self._log_states.values() if st.well_uid == uid
            )
            out.append(
                WellStatus(
                    well_uid=uid,
                    name=meta.get("name"),
                    region=meta.get("region"),
                    growing=bool(growing),
                    last_update=self._last_update.get(uid),
                    sample_count=count,
                    mnemonics=mnems,
                )
            )
        return out

    # ── log (index-cache) state ─────────────────────────────────────────
    def get_log_state(self, key: LogKey) -> LogState | None:
        return self._log_states.get(key)

    def put_log_state(self, state: LogState) -> None:
        self._log_states[state.key] = state

    def log_states(self) -> list[LogState]:
        return list(self._log_states.values())

    # ── pub/sub (WS fan-out, with back-pressure) ────────────────────────
    def subscribe(self, well_uid: str, maxsize: int = 256) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subscribers[well_uid].add(q)
        return q

    def unsubscribe(self, well_uid: str, q: asyncio.Queue) -> None:
        self._subscribers.get(well_uid, set()).discard(q)

    def publish(self, well_uid: str, payload: dict) -> None:
        """Non-blocking fan-out. Slow clients drop the OLDEST queued message
        (coalesce-to-latest) rather than blocking the scheduler (brief §9 load).
        """
        for q in list(self._subscribers.get(well_uid, ())):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    def subscriber_count(self, well_uid: str) -> int:
        return len(self._subscribers.get(well_uid, ()))


def sample_to_wire(s: CurveSample) -> dict:
    """Compact JSON for WS/REST: i=index (epoch ms or float), v=value, u=uom."""
    if isinstance(s.index, datetime):
        idx: float = s.index.timestamp() * 1000.0
    else:
        idx = float(s.index)
    return {"i": idx, "v": s.value, "t": s.text, "u": s.uom}


def _gt(a: IndexValue, b: IndexValue) -> bool:
    try:
        return a > b  # type: ignore[operator]
    except TypeError:
        return False


@lru_cache
def get_store() -> RingBufferStore:
    # Bound memory: RING_BUFFER_HOURS at 5s cadence, with headroom for bursts.
    per_curve = max(
        2000,
        int(settings.ring_buffer_hours * 3600 / settings.poll_interval_seconds) * 2,
    )
    return RingBufferStore(max_samples_per_curve=per_curve)
