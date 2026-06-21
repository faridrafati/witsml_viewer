"""Pure polling-correctness helpers (no zeep, no I/O — fully unit-testable).

These encode the two gotchas that silently corrupt a display if wrong:

  §11.1  Inclusive range boundaries. Structural range queries return nodes
         where index >= start AND <= end. Reusing the last endIndex as the
         next startIndex re-returns the boundary row → we must de-duplicate
         the boundary against the last index we already stored.

  §11.2  +2 truncation. A growing-object result may be truncated; the caller
         must re-query from the new max index until +1. `continuation_index`
         computes that new max (respecting index direction).

All comparisons respect index `direction` (increasing | decreasing) — never
assume increasing (§11.7).
"""

from __future__ import annotations

from datetime import datetime

from app.domain.models import LogDataBlock
from app.witsml.constants import Direction

IndexValue = float | datetime


def _row_indices(block: LogDataBlock) -> list[IndexValue]:
    return [r[0] for r in block.rows if r[0] is not None]  # type: ignore[misc]


def continuation_index(block: LogDataBlock, direction: Direction) -> IndexValue | None:
    """The index to resume from after a (possibly truncated, +2) batch.

    Increasing logs grow at the high end → resume from the max seen.
    Decreasing logs grow at the low end → resume from the min seen.
    Returns None for an empty batch (nothing new; stop the loop).
    """
    idxs = _row_indices(block)
    if not idxs:
        return None
    return max(idxs) if direction == Direction.INCREASING else min(idxs)


def is_beyond(index: IndexValue, last: IndexValue, direction: Direction) -> bool:
    """True if `index` is strictly newer than `last` for the given direction."""
    if direction == Direction.INCREASING:
        return index > last
    return index < last


def dedupe_boundary(
    block: LogDataBlock,
    last_index: IndexValue | None,
    direction: Direction,
) -> LogDataBlock:
    """Drop rows already seen — the boundary row (== last_index) and anything
    not strictly beyond it. Idempotent; returns a new block.
    """
    if last_index is None:
        return block
    kept = [
        r
        for r in block.rows
        if r[0] is not None and is_beyond(r[0], last_index, direction)  # type: ignore[arg-type]
    ]
    return LogDataBlock(
        mnemonics=block.mnemonics,
        units=block.units,
        index_type=block.index_type,
        rows=kept,
    )


def merge_blocks(blocks: list[LogDataBlock]) -> LogDataBlock:
    """Concatenate +2-loop iterations into one ordered, dup-free block.

    Rows are keyed by index (last write wins) then sorted ascending. Mixed
    empty inputs are tolerated; raises if column headers disagree.
    """
    if not blocks:
        raise ValueError("merge_blocks: at least one block is required")
    head = next((b for b in blocks if b.mnemonics), blocks[0])
    by_index: dict[IndexValue, list] = {}
    for b in blocks:
        if b.mnemonics and b.mnemonics != head.mnemonics:
            raise ValueError("merge_blocks: mnemonic headers differ across batches")
        for r in b.rows:
            if r[0] is None:
                continue
            by_index[r[0]] = r  # type: ignore[index]
    ordered = [by_index[k] for k in sorted(by_index.keys())]
    return LogDataBlock(
        mnemonics=head.mnemonics,
        units=head.units,
        index_type=head.index_type,
        rows=ordered,
    )
