"""Ingestion KERNEL behaviour (app.ingestion.store + app.witsml.polling).

No network, no real SOAP, no DB. Exercises the in-memory warm store that
backs the "ingest 20, view 1" strategy:

  1. Ring-buffer eviction caps each per-curve deque at max_samples, keeping
     the NEWEST samples.
  2. Pub/sub back-pressure: publish() never raises and coalesces to the
     LATEST payload when a slow subscriber's queue overflows.
  3. No-dupes/no-gaps across simulated incremental polls: a fake server
     re-returns the inclusive boundary row each round; dedupe_boundary +
     continuation_index + store.append must yield a contiguous, dup-free
     stored series.
  4. well_status() populates sample_count / mnemonics / last_update after
     appends.

Imports only domain models + polling + store. Does NOT import
app.witsml.client.
"""

from __future__ import annotations

from app.domain.models import CurveSample, LogDataBlock
from app.ingestion.store import RingBufferStore
from app.witsml.constants import Direction, IndexType
from app.witsml.polling import continuation_index, dedupe_boundary

MNEMS = ["DEPT", "GR"]
UNITS = ["m", "gAPI"]


def _sample(mnem: str, index: float, value: float, uom: str | None = "gAPI") -> CurveSample:
    return CurveSample(mnemonic=mnem, index=index, value=value, uom=uom)


# ── 1. Ring-buffer eviction ─────────────────────────────────────────────
def test_ring_buffer_caps_at_max_and_keeps_newest():
    n = 5
    store = RingBufferStore(max_samples_per_curve=n)

    # Append 20 samples (4x the cap) for a single curve, one per call to also
    # prove the deque is shared/persistent across append calls.
    for i in range(20):
        store.append("W-1", "LOG-1", [_sample("GR", float(i), float(i) * 10.0)])

    recent = store.get_recent("W-1", ["GR"])
    series = recent["GR"]

    # Capped at N.
    assert len(series) == n
    # Keeps the NEWEST (last 5 indices: 15..19).
    assert [s.index for s in series] == [15.0, 16.0, 17.0, 18.0, 19.0]
    assert [s.value for s in series] == [150.0, 160.0, 170.0, 180.0, 190.0]


def test_ring_buffer_eviction_within_single_append_call():
    store = RingBufferStore(max_samples_per_curve=3)
    batch = [_sample("GR", float(i), float(i)) for i in range(10)]
    store.append("W-1", "LOG-1", batch)

    series = store.get_recent("W-1", ["GR"])["GR"]
    assert len(series) == 3
    assert [s.index for s in series] == [7.0, 8.0, 9.0]


# ── 2. Pub/sub back-pressure ────────────────────────────────────────────
async def test_publish_never_raises_and_coalesces_to_latest():
    store = RingBufferStore(max_samples_per_curve=100)
    maxsize = 4
    q = store.subscribe("W-1", maxsize=maxsize)

    # Publish far more than maxsize. Each publish must be non-blocking and
    # must never raise, even though the slow subscriber never drains.
    total = 20
    for i in range(total):
        store.publish("W-1", {"type": "data", "wellUid": "W-1", "seq": i})

    # Queue is capped at maxsize (oldest were dropped to make room).
    assert q.qsize() == maxsize

    drained = []
    while not q.empty():
        drained.append(q.get_nowait())
    seqs = [p["seq"] for p in drained]

    # Keeps the LATEST `maxsize` payloads; oldest dropped (coalesce-to-latest).
    assert seqs == [total - maxsize + i for i in range(maxsize)]
    assert seqs[-1] == total - 1  # newest is present


async def test_publish_with_no_subscribers_is_noop():
    store = RingBufferStore(max_samples_per_curve=10)
    # Must not raise when nobody is listening.
    store.publish("W-ghost", {"type": "data"})
    assert store.subscriber_count("W-ghost") == 0


async def test_unsubscribe_stops_delivery():
    store = RingBufferStore(max_samples_per_curve=10)
    q = store.subscribe("W-1", maxsize=8)
    assert store.subscriber_count("W-1") == 1

    store.unsubscribe("W-1", q)
    assert store.subscriber_count("W-1") == 0

    store.publish("W-1", {"type": "data", "seq": 0})
    assert q.empty()


# ── 3. No-dupes / no-gaps across simulated incremental polls ─────────────
class _FakeGrowingLog:
    """A toy WITSML server emulation (no SOAP).

    Models a growing depth log with a fixed `step`. Each poll returns the rows
    from `start` (inclusive — the §11.1 boundary gotcha) up to the current
    growing frontier, re-including the boundary row that was already stored.
    """

    def __init__(self, start: float, step: float, mnemonics, units):
        self._step = step
        self._mnemonics = mnemonics
        self._units = units
        self._origin = start
        self._frontier = start  # highest index produced so far

    def grow(self, rows: int) -> None:
        self._frontier += self._step * rows

    def poll(self, start: float | None) -> LogDataBlock:
        """Return an inclusive [start, frontier] block (or whole log if start is
        None). Re-returns the boundary row when start lands on an existing row.
        """
        lo = self._origin if start is None else start
        rows: list[list[float]] = []
        idx = lo
        # Build contiguous rows lo, lo+step, ... <= frontier (float-safe).
        n = 0
        while idx <= self._frontier + 1e-9:
            value = (idx - self._origin) / self._step  # row ordinal as the value
            rows.append([round(idx, 6), value])
            n += 1
            idx = round(lo + self._step * n, 6)
        return LogDataBlock(
            mnemonics=self._mnemonics,
            units=self._units,
            index_type=IndexType.MEASURED_DEPTH,
            rows=rows,
        )


def test_simulated_polls_zero_dups_zero_gaps():
    step = 0.5
    server = _FakeGrowingLog(start=2500.0, step=step, mnemonics=MNEMS, units=UNITS)
    store = RingBufferStore(max_samples_per_curve=10_000)

    last_index: float | None = None
    rounds = [3, 2, 4, 1, 5]  # rows the log grows by before each subsequent poll

    for round_no, grow_by in enumerate(rounds):
        if round_no == 0:
            server.grow(grow_by)  # seed the very first batch
        # Poll re-queries from the last stored index (inclusive boundary).
        block = server.poll(last_index)
        # Drop the re-returned boundary row(s) and anything not strictly beyond.
        deduped = dedupe_boundary(block, last_index, Direction.INCREASING)
        # Persist only the genuinely-new samples.
        store.append("W-1", "LOG-1", deduped.samples())
        # Advance the resume cursor using the kernel helper.
        ci = continuation_index(deduped, Direction.INCREASING)
        if ci is not None:
            last_index = ci
        # Grow the log for the NEXT poll.
        if round_no + 1 < len(rounds):
            server.grow(rounds[round_no + 1])

    # GR mirrors the index 1:1 (every row has a GR cell), so inspect it.
    series = store.get_recent("W-1", ["GR"])["GR"]
    indices = [s.index for s in series]

    # ZERO duplicate indices.
    assert len(indices) == len(set(indices)), f"duplicate indices stored: {indices}"

    # ZERO gaps: contiguous `step` from the origin.
    assert indices == sorted(indices), "stored indices out of order"
    total_rows = len(indices)
    expected = [round(2500.0 + step * i, 6) for i in range(total_rows)]
    assert indices == expected, f"non-contiguous series: {indices}"

    # Sanity: we actually grew across multiple polls (not a one-shot).
    assert total_rows > rounds[0]


def test_simulated_polls_dedupe_drops_boundary_row_each_round():
    """Tighter check: the raw block always re-includes the boundary, but the
    stored series never gains a duplicate of it."""
    server = _FakeGrowingLog(start=0.0, step=1.0, mnemonics=MNEMS, units=UNITS)
    store = RingBufferStore(max_samples_per_curve=10_000)
    server.grow(3)  # rows at 0,1,2,3

    last_index = None
    raw_boundary_repeats = 0
    seen_indices: set[float] = set()

    for _ in range(3):
        block = server.poll(last_index)
        raw_idxs = [r[0] for r in block.rows]
        if last_index is not None and last_index in raw_idxs:
            raw_boundary_repeats += 1  # server DID re-return the boundary
        deduped = dedupe_boundary(block, last_index, Direction.INCREASING)
        for s in deduped.samples():
            assert s.index not in seen_indices, f"duplicate {s.index} leaked into store"
            seen_indices.add(s.index)
        store.append("W-1", "LOG-1", deduped.samples())
        ci = continuation_index(deduped, Direction.INCREASING)
        if ci is not None:
            last_index = ci
        server.grow(2)

    # The fake really did re-return boundary rows on follow-up polls...
    assert raw_boundary_repeats >= 1
    # ...yet the store has no duplicates.
    stored = [s.index for s in store.get_recent("W-1", ["GR"])["GR"]]
    assert len(stored) == len(set(stored))


# ── 4. well_status() population ──────────────────────────────────────────
def test_well_status_populates_after_append():
    store = RingBufferStore(max_samples_per_curve=10_000)
    store.set_well_meta("W-1", name="Pad-7 Lateral", region="Permian")

    store.append(
        "W-1",
        "LOG-1",
        [
            _sample("GR", 2500.0, 55.0),
            _sample("GR", 2500.5, 56.0),
            _sample("ROP", 2500.0, 30.0, uom="m/h"),
        ],
    )

    statuses = {s.well_uid: s for s in store.well_status()}
    assert "W-1" in statuses
    st = statuses["W-1"]

    assert st.name == "Pad-7 Lateral"
    assert st.region == "Permian"
    # sample_count is the sum across curves: 2 GR + 1 ROP.
    assert st.sample_count == 3
    # mnemonics enumerate the distinct curves (sorted).
    assert st.mnemonics == ["GR", "ROP"]
    # last_update was set by append() and is tz-aware UTC.
    assert st.last_update is not None
    assert st.last_update.tzinfo is not None


def test_well_status_empty_before_any_append():
    store = RingBufferStore(max_samples_per_curve=10)
    store.set_well_meta("W-1", name="Idle", region="N/A")
    st = {s.well_uid: s for s in store.well_status()}["W-1"]
    assert st.sample_count == 0
    assert st.mnemonics == []
    assert st.last_update is None


def test_well_status_growing_flag_from_log_state():
    from app.ingestion.store import LogState

    store = RingBufferStore(max_samples_per_curve=10)
    store.set_well_meta("W-1", name="Active", region="Permian")
    store.put_log_state(
        LogState(
            server_id=1,
            well_uid="W-1",
            wellbore_uid="WB-1",
            log_uid="LOG-1",
            index_type=IndexType.MEASURED_DEPTH,
            direction=Direction.INCREASING,
            object_growing=True,
        )
    )
    store.append("W-1", "LOG-1", [_sample("GR", 1.0, 2.0)])

    st = {s.well_uid: s for s in store.well_status()}["W-1"]
    assert st.growing is True
