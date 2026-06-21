"""Regression: polling comparisons must be timezone-safe.

Indices parsed from WITSML XML are tz-aware UTC, but a `last_index` restored
from a SQLite ``DateTime(timezone=True)`` column comes back NAIVE. Comparing
the two raised ``TypeError: can't compare offset-naive and offset-aware
datetimes`` and silently stalled a log's ingestion. The live integration test
caught it; this pins the fix at the unit level.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.domain.models import LogDataBlock
from app.witsml.constants import Direction, IndexType
from app.witsml.polling import continuation_index, dedupe_boundary, is_beyond


def test_is_beyond_mixed_naive_aware_does_not_raise():
    aware = datetime(2026, 1, 1, 9, 0, 5, tzinfo=timezone.utc)
    naive = datetime(2026, 1, 1, 9, 0, 0)  # e.g. from SQLite
    # aware index is strictly beyond a naive (UTC-assumed) last index.
    assert is_beyond(aware, naive, Direction.INCREASING) is True
    assert is_beyond(naive, aware, Direction.INCREASING) is False


def test_dedupe_boundary_with_naive_last_index():
    rows = [
        [datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc), 1.0],
        [datetime(2026, 1, 1, 9, 0, 5, tzinfo=timezone.utc), 2.0],
        [datetime(2026, 1, 1, 9, 0, 10, tzinfo=timezone.utc), 3.0],
    ]
    block = LogDataBlock(
        mnemonics=["TIME", "ROP"], units=["s", "m/h"], index_type=IndexType.DATE_TIME, rows=rows
    )
    naive_boundary = datetime(2026, 1, 1, 9, 0, 5)  # naive, as from SQLite
    kept = dedupe_boundary(block, naive_boundary, Direction.INCREASING)
    # Only the row strictly after 09:00:05 survives — boundary dropped.
    assert len(kept.rows) == 1
    assert kept.rows[0][1] == 3.0


def test_continuation_index_returns_aware_datetime():
    rows = [[datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc), 1.0]]
    block = LogDataBlock(
        mnemonics=["TIME", "ROP"], units=["s", "m/h"], index_type=IndexType.DATE_TIME, rows=rows
    )
    cur = continuation_index(block, Direction.INCREASING)
    assert isinstance(cur, datetime) and cur.tzinfo is not None
