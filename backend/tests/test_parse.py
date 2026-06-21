"""Parser correctness against realistic WITSML 1.4.1.1 fixtures.

Covers row counts, null handling (-999.25 + empty -> None and dropped from
samples), uom parsing, ISO-8601 -> tz-aware UTC, decreasing-index direction,
geologyInterval/lithPc parsing, numeric indices NOT coerced to datetime, and
merge_sparse_rows densification.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.witsml.constants import Direction, IndexType
from app.witsml.parse import (
    merge_sparse_rows,
    parse_log_data,
    parse_log_headers,
    parse_mudlogs,
    parse_wellbores,
    parse_wells,
)

from tests.conftest import load_fixture


# ── wells / wellbores ───────────────────────────────────────────────────
def test_parse_wells_count_and_fields():
    wells = parse_wells(load_fixture("wells.xml"))
    assert len(wells) == 3
    w = {x.uid: x for x in wells}
    assert w["W-001"].name == "Snorre A-12"
    assert w["W-001"].field == "Snorre"
    assert w["W-001"].region == "North Sea"
    assert w["W-003"].region == "Permian Basin"


def test_parse_wellbores_under_well():
    wbs = parse_wellbores(load_fixture("wellbores.xml"))
    assert len(wbs) == 2
    assert all(wb.uid_well == "W-001" for wb in wbs)
    assert {wb.uid for wb in wbs} == {"WB-001", "WB-002"}


# ── time log header ─────────────────────────────────────────────────────
def test_parse_time_header_metadata():
    hdr = parse_log_headers(load_fixture("log_header_time.xml"))[0]
    assert hdr.index_type == IndexType.DATE_TIME
    assert hdr.index_type.is_time
    assert hdr.direction == Direction.INCREASING
    assert hdr.null_value == "-999.25"
    assert hdr.mnemonics == ["TIME", "ROP", "WOB"]
    rop = hdr.curve("ROP")
    assert rop is not None
    assert rop.unit == "m/h"
    assert rop.type_log_data == "double"
    # ISO-8601 extents parsed to tz-aware UTC
    assert hdr.start_datetime_index == datetime(
        2026, 6, 21, 8, 0, 0, tzinfo=timezone.utc
    )
    assert hdr.start_datetime_index.tzinfo is not None


def test_time_header_curve_datetime_extent_is_utc_aware():
    hdr = parse_log_headers(load_fixture("log_header_time.xml"))[0]
    tc = hdr.curve("TIME")
    assert tc.min_datetime_index == datetime(2026, 6, 21, 8, 0, 0, tzinfo=timezone.utc)
    assert tc.min_datetime_index.utcoffset().total_seconds() == 0


# ── decreasing depth header ─────────────────────────────────────────────
def test_parse_decreasing_depth_header_direction_and_uom():
    hdr = parse_log_headers(load_fixture("log_header_depth_decreasing.xml"))[0]
    assert hdr.index_type == IndexType.MEASURED_DEPTH
    assert hdr.direction == Direction.DECREASING
    assert hdr.index_uom == "m"
    assert hdr.start_index == 3000.0
    assert hdr.end_index == 2990.0


# ── time data: null handling ────────────────────────────────────────────
def test_parse_time_data_rows_and_index_datetime():
    res = parse_log_data(
        load_fixture("log_data_time.xml"), index_type=IndexType.DATE_TIME
    )[0]
    block = res.block
    assert res.index_type == IndexType.DATE_TIME
    assert block.mnemonics == ["TIME", "ROP", "WOB"]
    assert len(block.rows) == 4
    # index cells are genuine tz-aware datetimes, not floats
    for row in block.rows:
        assert isinstance(row[0], datetime)
        assert row[0].tzinfo is not None


def test_time_data_null_and_empty_become_none_and_drop_from_samples():
    res = parse_log_data(
        load_fixture("log_data_time.xml"), index_type=IndexType.DATE_TIME
    )[0]
    block = res.block
    # row 1: ROP == -999.25 sentinel -> None
    assert block.rows[1][1] is None
    # row 2: WOB empty cell -> None
    assert block.rows[2][2] is None
    samples = block.samples()
    # 4 rows x 2 data curves = 8 cells, minus 2 nulled cells = 6 samples
    assert len(samples) == 6
    assert all(s.value is not None for s in samples)
    # samples carry the right uom from unitList
    rop_samples = [s for s in samples if s.mnemonic == "ROP"]
    assert all(s.uom == "m/h" for s in rop_samples)


# ── depth data: numeric index NOT coerced to datetime ───────────────────
def test_depth_data_numeric_index_not_datetime():
    res = parse_log_data(
        load_fixture("log_data_depth.xml"), index_type=IndexType.MEASURED_DEPTH
    )[0]
    block = res.block
    assert len(block.rows) == 4
    for row in block.rows:
        assert isinstance(row[0], float)
        assert not isinstance(row[0], datetime)
    assert block.rows[0][0] == 2500.0
    assert block.mnemonics[0] == "DEPT"


def test_depth_data_uom_parsed_into_samples():
    res = parse_log_data(
        load_fixture("log_data_depth.xml"), index_type=IndexType.MEASURED_DEPTH
    )[0]
    gr = [s for s in res.block.samples() if s.mnemonic == "GR"]
    assert gr and all(s.uom == "gAPI" for s in gr)


# ── merge_sparse_rows densification ─────────────────────────────────────
def test_merge_sparse_rows_densifies_latest_values():
    res = parse_log_data(
        load_fixture("log_data_latest_sparse.xml"), index_type=IndexType.MEASURED_DEPTH
    )[0]
    sparse = res.block
    # sparse: 4 rows, each with exactly one populated data curve, repeated index
    assert len(sparse.rows) == 4
    merged = merge_sparse_rows(sparse)
    # collapses to 2 dense rows keyed by the 2 distinct indices, sorted ascending
    assert len(merged.rows) == 2
    indices = [r[0] for r in merged.rows]
    assert indices == sorted(indices)
    by_idx = {r[0]: r for r in merged.rows}
    # both curves now populated on each dense row
    assert by_idx[2501.0][1] == 44.8 and by_idx[2501.0][2] == 2.30
    assert by_idx[2501.5][1] == 47.1 and by_idx[2501.5][2] == 2.33


# ── mudLog / geology ────────────────────────────────────────────────────
def test_parse_mudlog_intervals_and_lithologies():
    ml = parse_mudlogs(load_fixture("mudlog.xml"))[0]
    assert ml.uid == "ML-001"
    assert ml.object_growing is True
    assert len(ml.geology_intervals) == 2
    gi0 = ml.geology_intervals[0]
    assert gi0.md_top == 2500.0
    assert gi0.md_bottom == 2520.0
    assert gi0.md_uom == "m"
    assert len(gi0.lithologies) == 2
    ss = next(l for l in gi0.lithologies if l.type == "sandstone")
    assert ss.lith_pc == 70.0
    assert ss.code_lith == "SS"
    assert ss.description == "Fine-grained, well sorted"
    # second interval
    gi1 = ml.geology_intervals[1]
    pcts = sorted(l.lith_pc for l in gi1.lithologies)
    assert pcts == [15.0, 85.0]
