"""Deterministic write-then-read EQUALITY test against the in-process MockStore.

No network, no SOAP, no zeep: this drives :class:`mockstore.store.MockStore`
directly. We

  1. build a well + a growing depth log (units, nullValue, increasing index,
     two non-index curves) via the same WITSML 1.4.1.1 XML builders the write
     API uses (``app.api.store_write``), AddToStore them,
  2. UpdateInStore-append more rows (growing log),
  3. GetFromStore data-only and parse the response with the authoritative
     ``app.witsml.parse``,

then assert the read-back log data equals exactly what was written —
mnemonics, units, indices, values, nullValue preserved, objectGrowing true.

PYTHONPATH includes the repo root (for ``mockstore``) and backend (for
``app.*``). The test is fully offline and fast.
"""

from __future__ import annotations

from lxml import etree
from mockstore.store import RC_SUCCESS, MockStore

from app.api.store_write import (
    CurveBody,
    LogBody,
    WellBody,
    build_log_xml,
    build_well_xml,
)
from app.witsml.constants import NS_DATA, WITSML_VERSION, IndexType
from app.witsml.parse import parse_log_data, parse_log_headers

# ── the data we write (the single source of truth for the assertions) ─────
WELL_UID = "W-EQ-1"
LOG_UID = "L-EQ-1"
WELLBORE_UID = "B-EQ-1"
NULL_VALUE = "-999.25"
INDEX_UOM = "m"

MNEMONICS = ["DEPTH", "ROP", "GR"]
UNITS = ["m", "m/h", "gAPI"]

# Rows written at create time (increasing index), then more via UpdateInStore.
CREATE_ROWS = [
    (1000.0, 12.5, 45.0),
    (1000.5, 13.0, 46.5),
    (1001.0, 13.5, 47.0),
]
APPEND_ROWS = [
    (1001.5, 14.0, 48.5),
    (1002.0, 14.5, 49.0),
]
ALL_ROWS = CREATE_ROWS + APPEND_ROWS


def _log_body() -> LogBody:
    return LogBody(
        uid=LOG_UID,
        uidWell=WELL_UID,
        uidWellbore=WELLBORE_UID,
        name="Equality Log",
        nameWell="Equality Well",
        nameWellbore="Equality Wellbore",
        indexType="measured depth",
        indexCurve="DEPTH",
        direction="increasing",
        nullValue=NULL_VALUE,
        indexUom=INDEX_UOM,
        curves=[
            CurveBody(mnemonic="DEPTH", unit="m", typeLogData="double"),
            CurveBody(mnemonic="ROP", unit="m/h", typeLogData="double"),
            CurveBody(mnemonic="GR", unit="gAPI", typeLogData="double"),
        ],
    )


def _fmt(value: float) -> str:
    """Match the query builder's numeric formatting (clean integers/floats)."""
    if float(value).is_integer():
        return str(int(value))
    return repr(float(value))


def _data_csv(row: tuple[float, float, float]) -> str:
    return ",".join(_fmt(v) for v in row)


def _logdata_update_xml(rows: list[tuple[float, float, float]]) -> str:
    """Build a minimal UpdateInStore <log> carrying a <logData> append block."""
    root = etree.Element(
        f"{{{NS_DATA}}}logs", nsmap={None: NS_DATA}, version=WITSML_VERSION
    )
    log_el = etree.SubElement(root, f"{{{NS_DATA}}}log")
    log_el.set("uid", LOG_UID)
    log_el.set("uidWell", WELL_UID)
    log_el.set("uidWellbore", WELLBORE_UID)
    ld = etree.SubElement(log_el, f"{{{NS_DATA}}}logData")
    etree.SubElement(ld, f"{{{NS_DATA}}}mnemonicList").text = ",".join(MNEMONICS)
    etree.SubElement(ld, f"{{{NS_DATA}}}unitList").text = ",".join(UNITS)
    for row in rows:
        etree.SubElement(ld, f"{{{NS_DATA}}}data").text = _data_csv(row)
    return etree.tostring(root, encoding="unicode")


def _data_query_xml() -> str:
    """Build a data-only GetFromStore <log> query addressing our single log."""
    root = etree.Element(
        f"{{{NS_DATA}}}logs", nsmap={None: NS_DATA}, version=WITSML_VERSION
    )
    log_el = etree.SubElement(root, f"{{{NS_DATA}}}log")
    log_el.set("uid", LOG_UID)
    log_el.set("uidWell", WELL_UID)
    log_el.set("uidWellbore", WELLBORE_UID)
    for mnem in MNEMONICS:
        lci = etree.SubElement(log_el, f"{{{NS_DATA}}}logCurveInfo")
        etree.SubElement(lci, f"{{{NS_DATA}}}mnemonic").text = mnem
    ld = etree.SubElement(log_el, f"{{{NS_DATA}}}logData")
    etree.SubElement(ld, f"{{{NS_DATA}}}data")
    return etree.tostring(root, encoding="unicode")


def test_write_then_read_log_data_equality() -> None:
    store = MockStore()

    # 1. AddToStore: well + log header (with the create-time rows seeded).
    well_xml = build_well_xml(WellBody(uid=WELL_UID, name="Equality Well"))
    rc, supp = store.add_object("well", well_xml)
    assert rc == RC_SUCCESS, supp

    log_xml = build_log_xml(_log_body())
    # Inject the create-time logData into the header XML so AddToStore seeds rows.
    log_root = etree.fromstring(log_xml.encode("utf-8"))
    log_el = log_root[0]
    ld = etree.SubElement(log_el, f"{{{NS_DATA}}}logData")
    etree.SubElement(ld, f"{{{NS_DATA}}}mnemonicList").text = ",".join(MNEMONICS)
    etree.SubElement(ld, f"{{{NS_DATA}}}unitList").text = ",".join(UNITS)
    for row in CREATE_ROWS:
        etree.SubElement(ld, f"{{{NS_DATA}}}data").text = _data_csv(row)
    rc, supp = store.add_object("log", etree.tostring(log_root, encoding="unicode"))
    assert rc == RC_SUCCESS, supp

    # 2. UpdateInStore: append more rows -> growing log.
    rc, supp = store.update_object("log", _logdata_update_xml(APPEND_ROWS))
    assert rc == RC_SUCCESS, supp

    # 3. GetFromStore data-only and parse the response.
    rc, xml_out, supp = store.query(
        "log", _data_query_xml(), "returnElements=data-only"
    )
    assert rc == RC_SUCCESS, supp
    results = parse_log_data(xml_out, index_type=IndexType.MEASURED_DEPTH)
    assert len(results) == 1
    block = results[0].block

    # ── EQUALITY: mnemonics & units preserved exactly ────────────────────
    assert block.mnemonics == MNEMONICS
    assert block.units == UNITS

    # ── EQUALITY: indices & values, in increasing order, all rows present ─
    assert len(block.rows) == len(ALL_ROWS)
    for got_row, expected in zip(block.rows, ALL_ROWS, strict=True):
        # index cell (depth float)
        assert got_row[0] == expected[0]
        # value cells
        assert got_row[1] == expected[1]
        assert got_row[2] == expected[2]

    # ── EQUALITY via samples(): per-curve (index, value) round-trips ─────
    by_mnem: dict[str, list[tuple[float, float]]] = {"ROP": [], "GR": []}
    for s in block.samples():
        by_mnem.setdefault(s.mnemonic, []).append((s.index, s.value))
    assert by_mnem["ROP"] == [(r[0], r[1]) for r in ALL_ROWS]
    assert by_mnem["GR"] == [(r[0], r[2]) for r in ALL_ROWS]
    # units carried onto each sample
    rop_uoms = {s.uom for s in block.samples() if s.mnemonic == "ROP"}
    assert rop_uoms == {"m/h"}

    # ── nullValue preserved & objectGrowing true (header read-back) ──────
    rc, hdr_xml, supp = store.query(
        "log", _data_query_xml(), "returnElements=header-only"
    )
    assert rc == RC_SUCCESS, supp
    headers = parse_log_headers(hdr_xml)
    assert len(headers) == 1
    header = headers[0]
    assert header.null_value == NULL_VALUE
    assert header.object_growing is True
    assert header.mnemonics == MNEMONICS
