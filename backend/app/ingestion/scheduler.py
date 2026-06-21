"""The 5-second coordinated ingestion engine ("ingest 20, view 1").

A single background task drives one tick every ``settings.poll_interval_seconds``.
Each tick walks every discovered growing log, STAGGERED across wells with a
bounded ``asyncio.Semaphore`` so 20 wells never hammer the store at once. For
each log we resume incrementally from the cached ``last_index`` (the index
cache), dedupe the inclusive boundary row, append to the warm RingBufferStore,
publish live deltas to WS subscribers, and batch-persist to Postgres.

Strategy (brief §9 — "ingest 20, view 1"):
  * ALL wells stay warm — every growing log is polled each tick at the headline
    (full curve) rate. At 20 wells this is correct and simple; we keep the full
    curve set because the simulator's logs are small.
  * Wells with active WS subscribers (``store.subscriber_count > 0``) or the
    explicitly focused well are the "viewed" wells — they are polled FIRST in
    the tick so their deltas land with minimal latency.

Resilience:
  * Discovery that returns nothing (simulator still seeding) is tolerated; the
    tick loop retries discovery opportunistically until logs appear.
  * Every per-well step is wrapped in try/except so one bad well never stalls
    the others or kills the loop.
  * Index state is loaded from Postgres on start and snapshotted on stop (and
    periodically) so a restart resumes without re-pulling history.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from app.config import settings
from app.db.base import SessionLocal
from app.db.models import CurveSampleRow, IndexCacheSnapshot
from app.domain.models import CurveSample, LogHeader
from app.ingestion.store import (
    LogKey,
    LogState,
    RingBufferStore,
    get_store,
    sample_to_wire,
)
from app.witsml import polling
from app.witsml.client import WitsmlClient, WitsmlError, get_default_client
from app.witsml.constants import Direction, IndexType, ReturnElements
from app.witsml.parse import parse_log_headers, parse_wellbores, parse_wells
from app.witsml.queries import (
    log_header_query,
    well_query,
    wellbore_query,
)

logger = logging.getLogger(__name__)

#: Snapshot the index cache to Postgres roughly every N ticks.
_SNAPSHOT_EVERY_TICKS = 12


class IngestionScheduler:
    """Coordinates incremental polling of all discovered growing logs."""

    def __init__(self, server_id: int = 1) -> None:
        self.server_id = server_id
        self._store: RingBufferStore = get_store()
        self._client: WitsmlClient = get_default_client()

        # Discovered topology: LogKey -> its header. Keyed by the FULL identity,
        # not log uid alone — WITSML log uids are unique only within a wellbore,
        # so two wells can share e.g. "LOG-T" and must not collide.
        self._headers: dict[LogKey, LogHeader] = {}
        self._discovered = False

        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._sem = asyncio.Semaphore(max(1, settings.ingest_concurrency))
        self._tick_count = 0

        # Explicitly focused well (latest WS subscribe wins). Polled first.
        self._focused: str | None = None

    # ── lifecycle ───────────────────────────────────────────────────────
    async def start(self) -> None:
        """Load index snapshot, discover topology once, launch the tick loop."""
        try:
            await self._load_index_snapshot()
        except Exception:  # noqa: BLE001 — start must not crash app boot
            logger.exception("ingestion: failed to load index snapshot (continuing)")

        try:
            await self._discover()
        except Exception:  # noqa: BLE001 — simulator may still be seeding
            logger.warning(
                "ingestion: initial discovery failed; will retry on tick",
                exc_info=True,
            )

        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="ingestion-scheduler")
        logger.info(
            "ingestion: started (server_id=%s, logs=%d)",
            self.server_id,
            len(self._headers),
        )

    async def stop(self) -> None:
        """Cancel the tick loop and snapshot index state to Postgres."""
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        try:
            await self._snapshot_index_state()
        except Exception:  # noqa: BLE001 — shutdown is best-effort
            logger.exception("ingestion: failed to snapshot index state on stop")
        logger.info("ingestion: stopped")

    async def focus(self, well_uid: str) -> None:
        """Mark a well as the 'viewed' well (full-rate, polled first)."""
        self._focused = well_uid

    # ── tick loop ───────────────────────────────────────────────────────
    async def _run(self) -> None:
        interval = max(0.5, float(settings.poll_interval_seconds))
        while not self._stop.is_set():
            started = asyncio.get_event_loop().time()
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — never let one tick kill the loop
                logger.exception("ingestion: tick failed")

            elapsed = asyncio.get_event_loop().time() - started
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(0.0, interval - elapsed))
            except TimeoutError:
                pass

    async def _tick(self) -> None:
        self._tick_count += 1

        # Re-discover if the simulator hadn't seeded any logs yet.
        if not self._discovered or not self._headers:
            try:
                await self._discover()
            except Exception:  # noqa: BLE001
                logger.debug("ingestion: discovery retry failed", exc_info=True)

        headers = list(self._headers.values())
        if not headers:
            return

        # Viewed wells (focused or subscribed) go first so their deltas are
        # freshest; the rest follow to keep all 20 wells warm.
        def _is_viewed(h: LogHeader) -> bool:
            return h.uid_well == self._focused or self._store.subscriber_count(h.uid_well) > 0

        ordered = sorted(headers, key=lambda h: 0 if _is_viewed(h) else 1)

        stagger = max(0.0, settings.ingest_stagger_ms / 1000.0)
        tasks: list[asyncio.Task] = []
        for i, header in enumerate(ordered):
            if stagger and i:
                # Stagger work submission across wells (bounded by the
                # semaphore inside the worker).
                await asyncio.sleep(stagger)
            tasks.append(asyncio.create_task(self._ingest_log(header)))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        if self._tick_count % _SNAPSHOT_EVERY_TICKS == 0:
            try:
                await self._snapshot_index_state()
            except Exception:  # noqa: BLE001
                logger.exception("ingestion: periodic index snapshot failed")

    # ── per-log ingestion ───────────────────────────────────────────────
    async def _ingest_log(self, header: LogHeader) -> None:
        async with self._sem:
            try:
                await self._do_ingest_log(header)
            except WitsmlError as exc:
                logger.warning(
                    "ingestion: WITSML error on log %s (well %s): %s",
                    header.uid,
                    header.uid_well,
                    exc,
                )
            except Exception:  # noqa: BLE001 — isolate per-log failures
                logger.exception(
                    "ingestion: failed to ingest log %s (well %s)",
                    header.uid,
                    header.uid_well,
                )

    async def _do_ingest_log(self, header: LogHeader) -> None:
        key: LogKey = (
            self.server_id,
            header.uid_well,
            header.uid_wellbore,
            header.uid,
        )
        state = self._store.get_log_state(key) or self._state_from_header(header)

        index_mnem = state.index_mnemonic
        curve_mnems = [m for m in state.mnemonics if m != index_mnem]
        if not curve_mnems:
            return  # header carried only the index curve — nothing to fetch yet
        request_mnems = [index_mnem, *curve_mnems]

        result = await self._client.get_log_data(
            uid_well=header.uid_well,
            uid_wellbore=header.uid_wellbore,
            uid=header.uid,
            mnemonics=request_mnems,
            index_type=state.index_type,
            direction=state.direction,
            start=state.last_index,
            index_uom=state.index_uom,
            max_return_nodes=settings.max_return_nodes,
        )

        block = result.block
        # Drop the inclusive boundary row (== last_index) and anything not
        # strictly beyond it, so we never re-store the row we resumed from.
        deduped = polling.dedupe_boundary(block, state.last_index, state.direction)
        samples = deduped.samples()

        # Advance the index cursor from the *full* (pre-dedupe) block so the
        # next poll resumes correctly even when dedupe drops everything.
        new_cursor = polling.continuation_index(block, state.direction)
        if new_cursor is not None:
            state.last_index = new_cursor
        state.object_growing = True
        self._store.put_log_state(state)

        if not samples:
            return

        # Warm store (ring buffer) — the source of truth for WS/REST reads.
        self._store.append(header.uid_well, header.uid, samples)

        # Live fan-out: only wells with subscribers actually have queues; the
        # store no-ops the publish otherwise.
        by_mnem: dict[str, list[dict]] = {}
        for s in samples:
            by_mnem.setdefault(s.mnemonic, []).append(sample_to_wire(s))
        if by_mnem:
            self._store.publish(
                header.uid_well,
                {
                    "type": "data",
                    "wellUid": header.uid_well,
                    "curves": by_mnem,
                },
            )

        # Durable cache (batched single transaction per log per tick).
        try:
            await self._persist_samples(header, state, samples)
        except Exception:  # noqa: BLE001 — persistence is best-effort vs. live
            logger.exception("ingestion: failed to persist samples for log %s", header.uid)

    def _state_from_header(self, header: LogHeader) -> LogState:
        """Build initial LogState from a freshly discovered header."""
        index_mnem = header.index_curve or (header.mnemonics[0] if header.mnemonics else "")
        mnems = list(header.mnemonics)
        # Guarantee the index mnemonic leads the list (brief §6).
        if index_mnem and index_mnem in mnems:
            mnems = [index_mnem, *[m for m in mnems if m != index_mnem]]
        elif index_mnem:
            mnems = [index_mnem, *mnems]
        return LogState(
            server_id=self.server_id,
            well_uid=header.uid_well,
            wellbore_uid=header.uid_wellbore,
            log_uid=header.uid,
            index_type=header.index_type,
            direction=header.direction,
            index_uom=header.index_uom,
            index_mnemonic=index_mnem,
            mnemonics=mnems,
            last_index=None,
            object_growing=header.object_growing,
        )

    # ── discovery ───────────────────────────────────────────────────────
    async def _discover(self) -> None:
        """Discover wells -> wellbores -> log headers (cached). Idempotent."""
        wells = await self._fetch_wells()
        if not wells:
            return

        any_logs = False
        for well in wells:
            # Keep the cross-well status table populated (all 20 wells warm).
            self._store.set_well_meta(well.uid, well.name, well.region)
            try:
                wellbores = await self._fetch_wellbores(well.uid)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "ingestion: wellbore discovery failed for %s",
                    well.uid,
                    exc_info=True,
                )
                continue
            for wb in wellbores:
                try:
                    headers = await self._fetch_log_headers(well.uid, wb.uid)
                except Exception:  # noqa: BLE001
                    logger.debug(
                        "ingestion: log discovery failed for %s/%s",
                        well.uid,
                        wb.uid,
                        exc_info=True,
                    )
                    continue
                for h in headers:
                    if not h.uid:
                        continue
                    key: LogKey = (
                        self.server_id,
                        h.uid_well,
                        h.uid_wellbore,
                        h.uid,
                    )
                    self._headers[key] = h
                    any_logs = True
                    # Seed log state if we don't already have one (e.g. no
                    # snapshot restored it). Preserves restored last_index.
                    if self._store.get_log_state(key) is None:
                        self._store.put_log_state(self._state_from_header(h))

        if any_logs:
            self._discovered = True

    async def _fetch_wells(self):
        q = well_query(return_elements=ReturnElements.REQUESTED)
        _, xml, _ = await self._client.get_from_store(q.wml_type, q.query_xml, q.options_in)
        return parse_wells(xml or "")

    async def _fetch_wellbores(self, uid_well: str):
        q = wellbore_query(uid_well, return_elements=ReturnElements.REQUESTED)
        _, xml, _ = await self._client.get_from_store(q.wml_type, q.query_xml, q.options_in)
        return parse_wellbores(xml or "")

    async def _fetch_log_headers(self, uid_well: str, uid_wellbore: str):
        q = log_header_query(uid_well, uid_wellbore)
        _, xml, _ = await self._client.get_from_store(q.wml_type, q.query_xml, q.options_in)
        return parse_log_headers(xml or "")

    # ── Postgres persistence ────────────────────────────────────────────
    async def _persist_samples(
        self, header: LogHeader, state: LogState, samples: list[CurveSample]
    ) -> None:
        is_time = state.index_type.is_time
        rows = [
            CurveSampleRow(
                server_id=self.server_id,
                well_uid=header.uid_well,
                wellbore_uid=header.uid_wellbore,
                log_uid=header.uid,
                mnemonic=s.mnemonic,
                index_float=None if is_time else _as_float(s.index),
                index_dt=(s.index if (is_time and isinstance(s.index, datetime)) else None),
                value=s.value,
                text=s.text,
                uom=s.uom,
            )
            for s in samples
        ]
        async with SessionLocal() as session:
            session.add_all(rows)
            await session.commit()

    async def _load_index_snapshot(self) -> None:
        """Restore per-log last_index from Postgres into the store's LogState.

        Snapshot rows are per (log, mnemonic); the index cursor is identical
        across a log's curves, so we fold them into one LogState per log,
        taking the index curve's row for identity (direction/index_type/uom).
        """
        async with SessionLocal() as session:
            result = await session.execute(
                select(IndexCacheSnapshot).where(IndexCacheSnapshot.server_id == self.server_id)
            )
            snaps = result.scalars().all()

        # Group by log; collect the union of mnemonics and the resume cursor.
        per_log: dict[LogKey, list[IndexCacheSnapshot]] = {}
        for snap in snaps:
            key: LogKey = (
                snap.server_id,
                snap.well_uid,
                snap.wellbore_uid,
                snap.log_uid,
            )
            per_log.setdefault(key, []).append(snap)

        for key, group in per_log.items():
            head = group[0]
            direction = (
                Direction.DECREASING
                if (head.direction or "").lower() == "decreasing"
                else Direction.INCREASING
            )
            index_type = _index_type_from_str(head.index_type)
            last_index = _cursor_from_snap(head, index_type, direction)
            mnems = sorted({s.mnemonic for s in group})
            state = LogState(
                server_id=key[0],
                well_uid=key[1],
                wellbore_uid=key[2],
                log_uid=key[3],
                index_type=index_type,
                direction=direction,
                index_uom=head.uom,
                index_mnemonic=mnems[0] if mnems else "",
                mnemonics=mnems,
                last_index=last_index,
                object_growing=None,
            )
            self._store.put_log_state(state)

    async def _snapshot_index_state(self) -> None:
        """Upsert each log's per-mnemonic last_index to Postgres."""
        states = self._store.log_states()
        states = [s for s in states if s.server_id == self.server_id]
        if not states:
            return

        async with SessionLocal() as session:
            # Index existing rows for this server for a manual upsert (portable
            # across SQLite/Postgres without dialect-specific ON CONFLICT).
            existing_rows = (
                (
                    await session.execute(
                        select(IndexCacheSnapshot).where(
                            IndexCacheSnapshot.server_id == self.server_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            existing = {
                (r.well_uid, r.wellbore_uid, r.log_uid, r.mnemonic): r for r in existing_rows
            }

            for state in states:
                if state.last_index is None:
                    continue
                is_time = state.index_type.is_time
                lf = None if is_time else _as_float(state.last_index)
                ldt = (
                    state.last_index
                    if (is_time and isinstance(state.last_index, datetime))
                    else None
                )
                for mnem in state.mnemonics or [state.index_mnemonic]:
                    if not mnem:
                        continue
                    k = (state.well_uid, state.wellbore_uid, state.log_uid, mnem)
                    row = existing.get(k)
                    if row is None:
                        session.add(
                            IndexCacheSnapshot(
                                server_id=state.server_id,
                                well_uid=state.well_uid,
                                wellbore_uid=state.wellbore_uid,
                                log_uid=state.log_uid,
                                mnemonic=mnem,
                                last_index_float=lf,
                                last_index_dt=ldt,
                                uom=state.index_uom,
                                direction=state.direction.value,
                                index_type=state.index_type.value,
                            )
                        )
                    else:
                        row.last_index_float = lf
                        row.last_index_dt = ldt
                        row.uom = state.index_uom
                        row.direction = state.direction.value
                        row.index_type = state.index_type.value
            await session.commit()


# ── module helpers ──────────────────────────────────────────────────────
def _as_float(value) -> float | None:
    if value is None or isinstance(value, datetime):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _index_type_from_str(value: str | None) -> IndexType:
    if not value:
        return IndexType.MEASURED_DEPTH
    norm = value.strip().lower()
    for it in IndexType:
        if it.value == norm:
            return it
    if "time" in norm:
        return IndexType.DATE_TIME
    if "depth" in norm:
        return IndexType.MEASURED_DEPTH
    return IndexType.OTHER


def _cursor_from_snap(snap: IndexCacheSnapshot, index_type: IndexType, direction: Direction):
    if index_type.is_time:
        return snap.last_index_dt
    return snap.last_index_float
