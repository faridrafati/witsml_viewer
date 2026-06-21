"""THE CRITICAL TEST: incremental-polling correctness.

Simulates consecutive incremental polls over batches and asserts the merged
series has ZERO duplicates and ZERO gaps across the boundary. Covers:

  * dedupe_boundary drops exactly the reused boundary row (inclusive-range gotcha)
  * continuation_index respects index direction (increasing vs decreasing)
  * a +2 truncation spanning two batches, merged via merge_blocks, recovers
    ALL rows in order with no loss and no dups.

Pure: imports only domain models + polling + constants. No XML, no network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.models import LogDataBlock
from app.witsml.constants import Direction, IndexType
from app.witsml.polling import (
    continuation_index,
    dedupe_boundary,
    is_beyond,
    merge_blocks,
)

MNEMS = ["DEPT", "GR"]
UNITS = ["m", "gAPI"]


def _block(rows, index_type=IndexType.MEASURED_DEPTH):
    return LogDataBlock(
        mnemonics=MNEMS, units=UNITS, index_type=index_type, rows=[list(r) for r in rows]
    )


def _indices(block):
    return [r[0] for r in block.rows]


# ── continuation_index respects direction ───────────────────────────────
def test_continuation_index_increasing_picks_max():
    b = _block([[2500.0, 1.0], [2502.0, 2.0], [2501.0, 3.0]])
    assert continuation_index(b, Direction.INCREASING) == 2502.0


def test_continuation_index_decreasing_picks_min():
    b = _block([[2500.0, 1.0], [2498.0, 2.0], [2499.0, 3.0]])
    assert continuation_index(b, Direction.DECREASING) == 2498.0


def test_continuation_index_empty_returns_none():
    assert continuation_index(_block([]), Direction.INCREASING) is None


def test_is_beyond_direction_aware():
    assert is_beyond(10.0, 9.0, Direction.INCREASING)
    assert not is_beyond(9.0, 9.0, Direction.INCREASING)  # equal is NOT beyond
    assert is_beyond(8.0, 9.0, Direction.DECREASING)
    assert not is_beyond(10.0, 9.0, Direction.DECREASING)


# ── boundary dedup: inclusive range re-returns last row ─────────────────
def test_dedupe_boundary_drops_exactly_the_boundary_row_increasing():
    # poll 1 ended at 2501.0; poll 2 re-queried from start=2501.0 (inclusive)
    poll2 = _block([[2501.0, 99.0], [2501.5, 5.0], [2502.0, 6.0]])
    deduped = dedupe_boundary(poll2, last_index=2501.0, direction=Direction.INCREASING)
    assert _indices(deduped) == [2501.5, 2502.0]
    # the duplicated boundary value never leaks through
    assert all(r[0] != 2501.0 for r in deduped.rows)


def test_dedupe_boundary_decreasing():
    poll2 = _block([[2499.0, 9.0], [2498.5, 1.0], [2498.0, 2.0]])
    deduped = dedupe_boundary(poll2, last_index=2499.0, direction=Direction.DECREASING)
    assert _indices(deduped) == [2498.5, 2498.0]


def test_dedupe_boundary_none_last_index_is_noop():
    b = _block([[2500.0, 1.0], [2500.5, 2.0]])
    out = dedupe_boundary(b, last_index=None, direction=Direction.INCREASING)
    assert _indices(out) == [2500.0, 2500.5]


# ── full incremental loop: zero dups, zero gaps across boundary ─────────
def _run_increasing_poll_loop(batches):
    """Simulate the ingest loop: each batch is re-queried with start == last
    stored index (inclusive), so it re-includes the boundary row. We dedupe it
    against last_index and append. Returns the accumulated stored series.
    """
    series: list = []
    last_index = None
    for raw in batches:
        block = _block(raw)
        deduped = dedupe_boundary(block, last_index, Direction.INCREASING)
        series.extend(deduped.rows)
        ci = continuation_index(deduped, Direction.INCREASING)
        if ci is not None:
            last_index = ci
    return series


def test_incremental_loop_no_dups_no_gaps_across_boundary():
    # Each poll re-sends its starting (boundary) row because range is inclusive.
    poll1 = [[2500.0, 1.0], [2500.5, 2.0], [2501.0, 3.0]]
    poll2 = [[2501.0, 3.0], [2501.5, 4.0], [2502.0, 5.0]]  # boundary 2501.0 repeats
    poll3 = [[2502.0, 5.0], [2502.5, 6.0], [2503.0, 7.0]]  # boundary 2502.0 repeats

    series = _run_increasing_poll_loop([poll1, poll2, poll3])
    indices = [r[0] for r in series]

    # ZERO duplicates
    assert len(indices) == len(set(indices)), f"duplicate indices: {indices}"
    # ZERO gaps: contiguous 0.5 m steps from 2500.0 to 2503.0
    expected = [2500.0 + 0.5 * i for i in range(7)]
    assert indices == expected


# ── +2 truncation across two batches, merged via merge_blocks ───────────
def test_plus2_truncation_recovers_all_rows_in_order():
    # Server truncated the growing-object pull into two +2 batches. The loop
    # re-queries from continuation_index(batch1) (inclusive), so batch2 repeats
    # the boundary row. dedupe_boundary removes it; merge_blocks concatenates.
    batch1 = _block([[2500.0, 1.0], [2501.0, 2.0], [2502.0, 3.0]])  # result == +2
    ci = continuation_index(batch1, Direction.INCREASING)
    assert ci == 2502.0

    raw_batch2 = _block([[2502.0, 3.0], [2503.0, 4.0], [2504.0, 5.0]])  # result == +1
    batch2 = dedupe_boundary(raw_batch2, ci, Direction.INCREASING)

    merged = merge_blocks([batch1, batch2])
    indices = [r[0] for r in merged.rows]

    # ALL rows recovered, ascending, no loss, no dups
    assert indices == [2500.0, 2501.0, 2502.0, 2503.0, 2504.0]
    assert len(indices) == len(set(indices))
    # values intact and aligned
    assert {r[0]: r[1] for r in merged.rows} == {
        2500.0: 1.0,
        2501.0: 2.0,
        2502.0: 3.0,
        2503.0: 4.0,
        2504.0: 5.0,
    }


def test_merge_blocks_last_write_wins_on_dup_index():
    a = _block([[10.0, 1.0]])
    b = _block([[10.0, 2.0], [11.0, 3.0]])
    merged = merge_blocks([a, b])
    assert len(merged.rows) == 2
    by_idx = {r[0]: r[1] for r in merged.rows}
    assert by_idx[10.0] == 2.0  # later block wins


# ── time-indexed boundary dedup (datetime indices) ──────────────────────
def test_dedupe_boundary_with_datetime_indices():
    t0 = datetime(2026, 6, 21, 8, 0, 0, tzinfo=timezone.utc)
    rows = [[t0 + timedelta(seconds=10 * i), float(i)] for i in range(4)]
    poll2 = _block(rows, index_type=IndexType.DATE_TIME)
    last = t0 + timedelta(seconds=10)  # boundary is the second timestamp
    deduped = dedupe_boundary(poll2, last, Direction.INCREASING)
    assert all(r[0] > last for r in deduped.rows)
    assert len(deduped.rows) == 2
