"""Query-by-example (QBE) builders for WITSML 1.4.1.1 GetFromStore.

A QBE is a skeleton object: empty elements mark what to RETURN, populated
elements FILTER. Every builder returns a `QbeQuery` carrying the WML type
(`well`, `wellbore`, `log`, `mudLog`), the serialized query XML, and the
matching `OptionsIn` string.

Hard rules encoded here (brief §6):
  * The index curve is always requested FIRST in the curve list.
  * Time logs use <startDateTimeIndex> (ISO-8601 UTC); depth logs use
    <startIndex uom="..."> — never mixed in one query.
  * Only ONE growing object per data-only/all query.

Imports are intentionally limited to lxml + constants so this module is
unit-testable without zeep or a live server.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from lxml import etree

from app.witsml.constants import (
    NS_DATA,
    OPT_DATA_VERSION,
    OPT_INTERVAL_RANGE_INCLUSION,
    OPT_MAX_RETURN_NODES,
    OPT_REQUEST_LATEST_VALUES,
    OPT_RETURN_ELEMENTS,
    WITSML_VERSION,
    IndexType,
    IntervalRangeInclusion,
    ReturnElements,
    options_in,
    q_data,
)


@dataclass(frozen=True)
class QbeQuery:
    """A ready-to-send GetFromStore request triple."""

    wml_type: str  # "well" | "wellbore" | "log" | "mudLog"
    query_xml: str  # serialized QueryIn
    options_in: str  # OptionsIn string


# ── low-level builders ──────────────────────────────────────────────────
def _root(plural: str) -> etree._Element:
    """Create a versioned plural container with the data namespace default."""
    return etree.Element(q_data(plural), nsmap={None: NS_DATA}, version=WITSML_VERSION)


def _sub(
    parent: etree._Element, tag: str, text: str | None = None, **attrib: str
) -> etree._Element:
    el = etree.SubElement(parent, q_data(tag), **attrib)
    if text is not None:
        el.text = text
    return el


def _serialize(root: etree._Element) -> str:
    return etree.tostring(root, encoding="unicode")


def _iso_utc(value: datetime | str) -> str:
    """Normalize a datetime/str to ISO-8601 UTC with milliseconds + Z."""
    if isinstance(value, str):
        return value
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ── well / wellbore ─────────────────────────────────────────────────────
def well_query(
    uid: str | None = None, *, return_elements: ReturnElements = ReturnElements.ID_ONLY
) -> QbeQuery:
    """Discover wells. Default id-only for a cheap tree pull."""
    root = _root("wells")
    well = _sub(root, "well")
    if uid:
        well.set("uid", uid)
    # Empty markers so the server returns name/region even for id-only callers
    # that bump to requested/all.
    _sub(well, "name")
    _sub(well, "field")
    _sub(well, "region")
    _sub(well, "country")
    _sub(well, "operator")
    _sub(well, "statusWell")
    _sub(well, "timeZone")
    return QbeQuery("well", _serialize(root), options_in(**{OPT_RETURN_ELEMENTS: return_elements}))


def wellbore_query(
    uid_well: str,
    uid: str | None = None,
    *,
    return_elements: ReturnElements = ReturnElements.ID_ONLY,
) -> QbeQuery:
    """List wellbores under a well."""
    root = _root("wellbores")
    wb = _sub(root, "wellbore", uidWell=uid_well)
    if uid:
        wb.set("uid", uid)
    _sub(wb, "nameWell")
    _sub(wb, "name")
    _sub(wb, "statusWellbore")
    return QbeQuery(
        "wellbore",
        _serialize(root),
        options_in(**{OPT_RETURN_ELEMENTS: return_elements}),
    )


# ── log: header-only ────────────────────────────────────────────────────
def log_header_query(uid_well: str, uid_wellbore: str, uid: str | None = None) -> QbeQuery:
    """Learn a log's curves/units/direction/nullValue (run once per log)."""
    root = _root("logs")
    log = _sub(root, "log", uidWell=uid_well, uidWellbore=uid_wellbore, uid=uid or "")
    _sub(log, "nameWell")
    _sub(log, "nameWellbore")
    _sub(log, "name")
    _sub(log, "indexType")
    _sub(log, "indexCurve")
    _sub(log, "direction")
    _sub(log, "objectGrowing")
    _sub(log, "nullValue")
    _sub(log, "startIndex", uom="")
    _sub(log, "endIndex", uom="")
    _sub(log, "startDateTimeIndex")
    _sub(log, "endDateTimeIndex")
    lci = _sub(log, "logCurveInfo", uid="")
    _sub(lci, "mnemonic")
    _sub(lci, "unit")
    _sub(lci, "curveDescription")
    _sub(lci, "typeLogData")
    _sub(lci, "minIndex", uom="")
    _sub(lci, "maxIndex", uom="")
    _sub(lci, "minDateTimeIndex")
    _sub(lci, "maxDateTimeIndex")
    return QbeQuery(
        "log",
        _serialize(root),
        options_in(**{OPT_RETURN_ELEMENTS: ReturnElements.HEADER_ONLY}),
    )


# ── log: incremental data ───────────────────────────────────────────────
def log_data_query(
    uid_well: str,
    uid_wellbore: str,
    uid: str,
    mnemonics: list[str],
    *,
    index_type: IndexType,
    start: float | datetime | str | None = None,
    end: float | datetime | str | None = None,
    index_uom: str | None = None,
    max_return_nodes: int | None = None,
) -> QbeQuery:
    """Build the realtime incremental poll (data-only) for ONE log.

    `mnemonics[0]` MUST be the index curve. `start`/`end` are interpreted by
    `index_type`: time logs render <startDateTimeIndex>, depth logs render
    <startIndex uom=...>. The ingestion engine chooses start/end per the
    log's growth direction; this builder only renders what it is given.
    """
    if not mnemonics:
        raise ValueError("log_data_query requires at least the index mnemonic")

    root = _root("logs")
    log = _sub(root, "log", uidWell=uid_well, uidWellbore=uid_wellbore, uid=uid)

    if index_type.is_time:
        if start is not None:
            _sub(log, "startDateTimeIndex", _iso_utc(start))  # type: ignore[arg-type]
        if end is not None:
            _sub(log, "endDateTimeIndex", _iso_utc(end))  # type: ignore[arg-type]
    else:
        if start is not None:
            _sub(log, "startIndex", _fmt_num(start), uom=index_uom or "")
        if end is not None:
            _sub(log, "endIndex", _fmt_num(end), uom=index_uom or "")

    for mnem in mnemonics:
        lci = _sub(log, "logCurveInfo", uid="")
        _sub(lci, "mnemonic", mnem)

    log_data = _sub(log, "logData")
    _sub(log_data, "data")

    return QbeQuery(
        "log",
        _serialize(root),
        options_in(
            **{
                OPT_RETURN_ELEMENTS: ReturnElements.DATA_ONLY,
                OPT_MAX_RETURN_NODES: max_return_nodes,
            }
        ),
    )


def latest_values_query(
    uid_well: str,
    uid_wellbore: str,
    uid: str,
    mnemonics: list[str],
    *,
    n: int = 1,
) -> QbeQuery:
    """Thin 'headline' poll: latest n values PER curve (rows come sparse).

    Ignores start/end index; capped server-side by maxRequestLatestValues.
    Merge the sparse rows by index on the client (parse.merge_sparse_rows).
    """
    if not mnemonics:
        raise ValueError("latest_values_query requires at least the index mnemonic")
    root = _root("logs")
    log = _sub(root, "log", uidWell=uid_well, uidWellbore=uid_wellbore, uid=uid)
    for mnem in mnemonics:
        lci = _sub(log, "logCurveInfo", uid="")
        _sub(lci, "mnemonic", mnem)
    log_data = _sub(log, "logData")
    _sub(log_data, "data")
    return QbeQuery(
        "log",
        _serialize(root),
        options_in(
            **{
                OPT_RETURN_ELEMENTS: ReturnElements.DATA_ONLY,
                OPT_REQUEST_LATEST_VALUES: n,
            }
        ),
    )


# ── mudLog ──────────────────────────────────────────────────────────────
def mudlog_query(
    uid_well: str,
    uid_wellbore: str,
    uid: str | None = None,
    *,
    md_top: float | None = None,
    md_bottom: float | None = None,
    md_uom: str = "m",
    interval_inclusion: IntervalRangeInclusion = IntervalRangeInclusion.ANY_PART,
) -> QbeQuery:
    """Pull lithology / geology intervals.

    `any-part` (default) keeps intervals that straddle the range boundary —
    important for monitoring so nothing is dropped at the edges.
    """
    root = _root("mudLogs")
    ml = _sub(root, "mudLog", uidWell=uid_well, uidWellbore=uid_wellbore, uid=uid or "")
    _sub(ml, "nameWell")
    _sub(ml, "nameWellbore")
    _sub(ml, "name")
    _sub(ml, "objectGrowing")
    gi = _sub(ml, "geologyInterval", uid="")
    _sub(gi, "typeLithology")
    if md_top is not None:
        _sub(gi, "mdTop", _fmt_num(md_top), uom=md_uom)
    else:
        _sub(gi, "mdTop", uom="")
    if md_bottom is not None:
        _sub(gi, "mdBottom", _fmt_num(md_bottom), uom=md_uom)
    else:
        _sub(gi, "mdBottom", uom="")
    _sub(gi, "description")
    lith = _sub(gi, "lithology", uid="")
    _sub(lith, "type")
    _sub(lith, "codeLith")
    _sub(lith, "lithPc", uom="")
    _sub(lith, "description")
    return QbeQuery(
        "mudLog",
        _serialize(root),
        options_in(**{OPT_INTERVAL_RANGE_INCLUSION: interval_inclusion}),
    )


# ── capabilities ────────────────────────────────────────────────────────
def get_cap_options() -> str:
    """OptionsIn for WMLS_GetCap — dataVersion is REQUIRED (brief §11.4)."""
    return options_in(**{OPT_DATA_VERSION: WITSML_VERSION})


# ── helpers ─────────────────────────────────────────────────────────────
def _fmt_num(value: float | datetime | str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return _iso_utc(value)
    # Trim trailing zeros but keep integers clean.
    if float(value).is_integer():
        return str(int(value))
    return repr(float(value))
