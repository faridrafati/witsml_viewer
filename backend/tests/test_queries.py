"""QBE template correctness for the GetFromStore builders.

No network, no zeep — these only exercise app.witsml.queries + constants and
parse the serialized XML back with lxml to assert structure.
"""

from __future__ import annotations

from datetime import datetime, timezone

from lxml import etree

from app.witsml.constants import (
    NS_DATA,
    IndexType,
    IntervalRangeInclusion,
    ReturnElements,
)
from app.witsml.queries import (
    get_cap_options,
    latest_values_query,
    log_data_query,
    log_header_query,
    mudlog_query,
    well_query,
    wellbore_query,
)

Q = f"{{{NS_DATA}}}"


def _tree(q):
    return etree.fromstring(q.query_xml.encode("utf-8"))


def _opts(options_in: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in options_in.split(";"):
        if not part:
            continue
        k, _, v = part.partition("=")
        out[k] = v
    return out


# ── namespace / version ─────────────────────────────────────────────────
def test_query_uses_data_namespace_and_version():
    q = well_query()
    root = _tree(q)
    assert root.tag == f"{Q}wells"
    assert root.get("version") == "1.4.1.1"
    # every element sits in the data namespace
    for el in root.iter():
        assert etree.QName(el).namespace == NS_DATA


def test_well_query_default_id_only():
    q = well_query()
    assert q.wml_type == "well"
    assert _opts(q.options_in)["returnElements"] == ReturnElements.ID_ONLY.value


def test_wellbore_query_filters_by_well():
    q = wellbore_query("W-001")
    root = _tree(q)
    wb = root.find(f"{Q}wellbore")
    assert wb.get("uidWell") == "W-001"
    assert q.wml_type == "wellbore"


# ── log header ──────────────────────────────────────────────────────────
def test_log_header_query_is_header_only():
    q = log_header_query("W-001", "WB-001", "LOG-1")
    assert _opts(q.options_in)["returnElements"] == ReturnElements.HEADER_ONLY.value
    root = _tree(q)
    log = root.find(f"{Q}log")
    assert log.get("uid") == "LOG-1"
    assert log.get("uidWell") == "W-001"
    assert log.get("uidWellbore") == "WB-001"


# ── log data: index curve FIRST ─────────────────────────────────────────
def test_log_data_index_mnemonic_is_first():
    q = log_data_query(
        "W-001",
        "WB-001",
        "LOG-1",
        ["DEPT", "GR", "RHOB"],
        index_type=IndexType.MEASURED_DEPTH,
        start=2500.0,
        index_uom="m",
    )
    root = _tree(q)
    log = root.find(f"{Q}log")
    mnems = [lci.find(f"{Q}mnemonic").text for lci in log.findall(f"{Q}logCurveInfo")]
    assert mnems[0] == "DEPT", "index curve must be requested first"
    assert mnems == ["DEPT", "GR", "RHOB"]


def test_log_data_options_are_data_only():
    q = log_data_query(
        "W-001",
        "WB-001",
        "LOG-1",
        ["DEPT", "GR"],
        index_type=IndexType.MEASURED_DEPTH,
    )
    assert _opts(q.options_in)["returnElements"] == ReturnElements.DATA_ONLY.value


def test_log_data_has_empty_logdata_data_marker():
    q = log_data_query(
        "W-001", "WB-001", "LOG-1", ["DEPT", "GR"], index_type=IndexType.MEASURED_DEPTH
    )
    root = _tree(q)
    log = root.find(f"{Q}log")
    ld = log.find(f"{Q}logData")
    assert ld is not None
    assert ld.find(f"{Q}data") is not None


# ── time vs depth index rendering ───────────────────────────────────────
def test_time_log_renders_iso8601_z_start():
    dt = datetime(2026, 6, 21, 8, 0, 0, tzinfo=timezone.utc)
    q = log_data_query(
        "W-001",
        "WB-001",
        "LOG-TIME",
        ["TIME", "ROP"],
        index_type=IndexType.DATE_TIME,
        start=dt,
    )
    root = _tree(q)
    log = root.find(f"{Q}log")
    sdt = log.find(f"{Q}startDateTimeIndex")
    assert sdt is not None
    assert sdt.text == "2026-06-21T08:00:00.000Z"
    # a time query must NOT render a depth-style startIndex
    assert log.find(f"{Q}startIndex") is None


def test_time_log_naive_datetime_assumed_utc():
    dt = datetime(2026, 6, 21, 8, 0, 0)  # naive
    q = log_data_query(
        "W-001", "WB-001", "L", ["TIME", "ROP"], index_type=IndexType.DATE_TIME, start=dt
    )
    log = _tree(q).find(f"{Q}log")
    assert log.find(f"{Q}startDateTimeIndex").text.endswith("Z")


def test_depth_log_renders_start_index_with_uom():
    q = log_data_query(
        "W-001",
        "WB-001",
        "LOG-DEPTH",
        ["DEPT", "GR"],
        index_type=IndexType.MEASURED_DEPTH,
        start=2500.0,
        end=2600.0,
        index_uom="m",
    )
    root = _tree(q)
    log = root.find(f"{Q}log")
    si = log.find(f"{Q}startIndex")
    ei = log.find(f"{Q}endIndex")
    assert si is not None and si.get("uom") == "m"
    assert si.text == "2500"
    assert ei is not None and ei.get("uom") == "m" and ei.text == "2600"
    # a depth query must NOT render a time-style index
    assert log.find(f"{Q}startDateTimeIndex") is None


# ── latest values ───────────────────────────────────────────────────────
def test_latest_values_sets_request_latest_values():
    q = latest_values_query("W-001", "WB-001", "LOG-1", ["DEPT", "GR"], n=3)
    opts = _opts(q.options_in)
    assert opts["returnElements"] == ReturnElements.DATA_ONLY.value
    assert opts["requestLatestValues"] == "3"


# ── mudLog ──────────────────────────────────────────────────────────────
def test_mudlog_query_uses_any_part_inclusion():
    q = mudlog_query("W-001", "WB-001", "ML-1")
    assert q.wml_type == "mudLog"
    opts = _opts(q.options_in)
    assert opts["intervalRangeInclusion"] == IntervalRangeInclusion.ANY_PART.value


def test_mudlog_query_renders_md_range_with_uom():
    q = mudlog_query(
        "W-001", "WB-001", "ML-1", md_top=2500.0, md_bottom=2600.0, md_uom="m"
    )
    root = _tree(q)
    gi = root.find(f"{Q}mudLog").find(f"{Q}geologyInterval")
    top = gi.find(f"{Q}mdTop")
    assert top.get("uom") == "m" and top.text == "2500"


# ── capabilities ────────────────────────────────────────────────────────
def test_get_cap_options_is_exactly_data_version():
    assert get_cap_options() == "dataVersion=1.4.1.1"
