"""Parse WITSML 1.4.1.1 XMLout into domain objects.

Namespace-agnostic: matching is by local-name, so it works whether a server
returns the data namespace as the default or behind a prefix. Imports only
lxml + constants + domain, so it is unit-testable without zeep.

Correctness rules enforced here (brief §6 / §11):
  * nullValue handling — curve-level overrides log-level; empty string is
    always null; common sentinels (-999.25, ...) are stripped defensively.
  * Time logs are parsed to timezone-aware UTC datetimes.
  * Index direction is read, never assumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from lxml import etree

from app.domain.models import (
    GeologyInterval,
    Lithology,
    LogCurveInfo,
    LogDataBlock,
    LogHeader,
    MudLog,
    Well,
    Wellbore,
)
from app.witsml.constants import (
    COMMON_NULL_SENTINELS,
    Direction,
    IndexType,
)

XmlLike = str | bytes | etree._Element


# ── tree helpers ────────────────────────────────────────────────────────
def to_tree(xml: XmlLike) -> etree._Element:
    if isinstance(xml, etree._Element):
        return xml
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    # `recover` tolerates the minor non-conformance real servers emit.
    parser = etree.XMLParser(recover=True, huge_tree=True)
    return etree.fromstring(xml, parser=parser)


def _local(el: etree._Element) -> str:
    return etree.QName(el).localname


def _children(parent: etree._Element, name: str) -> list[etree._Element]:
    return [c for c in parent if isinstance(c.tag, str) and _local(c) == name]


def _first(parent: etree._Element, name: str) -> etree._Element | None:
    for c in parent:
        if isinstance(c.tag, str) and _local(c) == name:
            return c
    return None


def _text(parent: etree._Element, name: str) -> str | None:
    el = _first(parent, name)
    if el is None or el.text is None:
        return None
    txt = el.text.strip()
    return txt or None


def _attr_uom(parent: etree._Element, name: str) -> str | None:
    el = _first(parent, name)
    if el is None:
        return None
    uom = el.get("uom")
    return uom.strip() if uom else None


def _descendants(root: etree._Element, name: str) -> list[etree._Element]:
    return [e for e in root.iter() if isinstance(e.tag, str) and _local(e) == name]


# ── scalar coercion ─────────────────────────────────────────────────────
def parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.strip().lower() in ("true", "1", "yes")


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.strip())
    except (ValueError, AttributeError):
        return None


def parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO-8601 to a UTC-aware datetime. Tolerates trailing Z."""
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _index_type(value: str | None) -> IndexType:
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


def _direction(value: str | None) -> Direction:
    if value and value.strip().lower() == "decreasing":
        return Direction.DECREASING
    return Direction.INCREASING


# ── wells / wellbores ───────────────────────────────────────────────────
def parse_wells(xml: XmlLike) -> list[Well]:
    root = to_tree(xml)
    out: list[Well] = []
    for el in _descendants(root, "well"):
        out.append(
            Well(
                uid=el.get("uid", ""),
                name=_text(el, "name"),
                region=_text(el, "region"),
                field=_text(el, "field"),
                country=_text(el, "country"),
                operator=_text(el, "operator"),
                status=_text(el, "statusWell"),
                time_zone=_text(el, "timeZone"),
            )
        )
    return out


def parse_wellbores(xml: XmlLike) -> list[Wellbore]:
    root = to_tree(xml)
    out: list[Wellbore] = []
    for el in _descendants(root, "wellbore"):
        out.append(
            Wellbore(
                uid=el.get("uid", ""),
                uid_well=el.get("uidWell", ""),
                name=_text(el, "name"),
                name_well=_text(el, "nameWell"),
                status=_text(el, "statusWellbore"),
            )
        )
    return out


# ── log header ──────────────────────────────────────────────────────────
def parse_log_headers(xml: XmlLike) -> list[LogHeader]:
    root = to_tree(xml)
    out: list[LogHeader] = []
    for el in _descendants(root, "log"):
        index_type = _index_type(_text(el, "indexType"))
        curves: list[LogCurveInfo] = []
        for lci in _children(el, "logCurveInfo"):
            curves.append(
                LogCurveInfo(
                    uid=lci.get("uid") or None,
                    mnemonic=_text(lci, "mnemonic") or "",
                    unit=_text(lci, "unit"),
                    curve_description=_text(lci, "curveDescription"),
                    type_log_data=_text(lci, "typeLogData"),
                    null_value=_text(lci, "nullValue"),
                    min_index=parse_float(_text(lci, "minIndex")),
                    max_index=parse_float(_text(lci, "maxIndex")),
                    min_datetime_index=parse_datetime(_text(lci, "minDateTimeIndex")),
                    max_datetime_index=parse_datetime(_text(lci, "maxDateTimeIndex")),
                )
            )
        out.append(
            LogHeader(
                uid=el.get("uid", ""),
                uid_well=el.get("uidWell", ""),
                uid_wellbore=el.get("uidWellbore", ""),
                name=_text(el, "name"),
                name_well=_text(el, "nameWell"),
                name_wellbore=_text(el, "nameWellbore"),
                index_type=index_type,
                index_curve=_text(el, "indexCurve"),
                direction=_direction(_text(el, "direction")),
                object_growing=parse_bool(_text(el, "objectGrowing")),
                null_value=_text(el, "nullValue"),
                index_uom=_attr_uom(el, "startIndex"),
                start_index=parse_float(_text(el, "startIndex")),
                end_index=parse_float(_text(el, "endIndex")),
                start_datetime_index=parse_datetime(_text(el, "startDateTimeIndex")),
                end_datetime_index=parse_datetime(_text(el, "endDateTimeIndex")),
                curves=curves,
            )
        )
    return out


# ── log data ────────────────────────────────────────────────────────────
@dataclass
class LogDataResult:
    """One log's parsed, null-stripped data block plus its identity."""

    uid: str
    uid_well: str
    uid_wellbore: str
    index_type: IndexType
    block: LogDataBlock


def _null_tokens(log_el: etree._Element, header_null: str | None) -> set[str]:
    tokens = set(COMMON_NULL_SENTINELS)
    log_null = _text(log_el, "nullValue") or header_null
    if log_null:
        tokens.add(log_null.strip())
    return tokens


def _decode_cell(raw: str, is_index: bool, index_type: IndexType, nulls: set[str]):
    val = raw.strip()
    if val in nulls or val == "":
        return None
    if is_index and index_type.is_time:
        return parse_datetime(val)
    num = parse_float(val)
    return num if num is not None else val  # keep text for string curves


def parse_log_data(
    xml: XmlLike,
    *,
    index_type: IndexType | None = None,
    header_null: str | None = None,
) -> list[LogDataResult]:
    """Parse data-only/all <logData> blocks, stripping nulls.

    `index_type` overrides what the response declares (a data-only response
    may omit indexType — pass it from the header query). Rows whose index is
    null are dropped entirely.
    """
    root = to_tree(xml)
    results: list[LogDataResult] = []
    for log_el in _descendants(root, "log"):
        ld = _first(log_el, "logData")
        if ld is None:
            continue
        mnem_list = _text(ld, "mnemonicList")
        unit_list = _text(ld, "unitList")
        if not mnem_list:
            continue
        mnemonics = [m.strip() for m in mnem_list.split(",")]
        units: list[str | None] = (
            [u.strip() or None for u in unit_list.split(",")]
            if unit_list
            else [None] * len(mnemonics)
        )
        # pad units to mnemonic length
        if len(units) < len(mnemonics):
            units += [None] * (len(mnemonics) - len(units))

        itype = index_type or _index_type(_text(log_el, "indexType"))
        nulls = _null_tokens(log_el, header_null)

        rows: list[list[float | str | datetime | None]] = []
        for data_el in _children(ld, "data"):
            if data_el.text is None:
                continue
            cells = data_el.text.split(",")
            decoded: list[float | str | datetime | None] = []
            for col, raw in enumerate(cells):
                decoded.append(_decode_cell(raw, col == 0, itype, nulls))
            rows.append(decoded)

        block = LogDataBlock(mnemonics=mnemonics, units=units, index_type=itype, rows=rows)
        results.append(
            LogDataResult(
                uid=log_el.get("uid", ""),
                uid_well=log_el.get("uidWell", ""),
                uid_wellbore=log_el.get("uidWellbore", ""),
                index_type=itype,
                block=block,
            )
        )
    return results


def merge_sparse_rows(block: LogDataBlock) -> LogDataBlock:
    """Collapse requestLatestValues sparse rows (one curve populated per row)
    into dense rows keyed by index. Last write wins for a given index.
    """
    by_index: dict[object, list[float | str | datetime | None]] = {}
    width = len(block.mnemonics)
    for row in block.rows:
        idx = row[0]
        if idx is None:
            continue
        dense = by_index.setdefault(idx, [idx] + [None] * (width - 1))
        for col in range(1, width):
            if col < len(row) and row[col] is not None:
                dense[col] = row[col]
    merged_rows = [by_index[k] for k in sorted(by_index.keys(), key=_sort_key)]
    return LogDataBlock(
        mnemonics=block.mnemonics,
        units=block.units,
        index_type=block.index_type,
        rows=merged_rows,
    )


def _sort_key(value):
    # datetimes and floats are each orderable within themselves.
    return value


# ── mudLog / geology ────────────────────────────────────────────────────
def parse_mudlogs(xml: XmlLike) -> list[MudLog]:
    root = to_tree(xml)
    out: list[MudLog] = []
    for ml in _descendants(root, "mudLog"):
        intervals: list[GeologyInterval] = []
        for gi in _children(ml, "geologyInterval"):
            liths: list[Lithology] = []
            for lith in _children(gi, "lithology"):
                liths.append(
                    Lithology(
                        uid=lith.get("uid") or None,
                        type=_text(lith, "type"),
                        code_lith=_text(lith, "codeLith"),
                        lith_pc=parse_float(_text(lith, "lithPc")),
                        description=_text(lith, "description"),
                        color=_text(lith, "color"),
                    )
                )
            intervals.append(
                GeologyInterval(
                    uid=gi.get("uid") or None,
                    type_lithology=_text(gi, "typeLithology"),
                    md_top=parse_float(_text(gi, "mdTop")),
                    md_bottom=parse_float(_text(gi, "mdBottom")),
                    md_uom=_attr_uom(gi, "mdTop") or _attr_uom(gi, "mdBottom"),
                    description=_text(gi, "description"),
                    lithologies=liths,
                )
            )
        out.append(
            MudLog(
                uid=ml.get("uid", ""),
                uid_well=ml.get("uidWell", ""),
                uid_wellbore=ml.get("uidWellbore", ""),
                name=_text(ml, "name"),
                name_well=_text(ml, "nameWell"),
                name_wellbore=_text(ml, "nameWellbore"),
                object_growing=parse_bool(_text(ml, "objectGrowing")),
                geology_intervals=intervals,
            )
        )
    return out


# ── capabilities ────────────────────────────────────────────────────────
@dataclass
class ServerCap:
    name: str | None = None
    version: str | None = None
    growing_timeout_period: int | None = None
    change_detection_period: int | None = None
    max_request_latest_values: int | None = None
    supported_objects: dict[str, set[str]] = field(default_factory=dict)
    raw: str | None = None


def parse_cap(xml: XmlLike) -> ServerCap:
    """Parse capServer from a GetCap response (best-effort across servers)."""
    root = to_tree(xml)
    cap = ServerCap()
    server = next((e for e in _descendants(root, "capServer")), None)
    if server is None:
        cap.raw = etree.tostring(root, encoding="unicode")
        return cap
    cap.version = server.get("apiVers") or _text(server, "apiVers")
    cap.name = _text(server, "name")
    cap.growing_timeout_period = _int(_text(server, "growingTimeoutPeriod"))
    cap.change_detection_period = _int(_text(server, "changeDetectionPeriod"))
    cap.max_request_latest_values = _int(_text(server, "maxRequestLatestValues"))
    for fn in _descendants(server, "function"):
        fname = fn.get("name") or ""
        objs = {_text(o, "dataObject") or o.text or "" for o in _children(fn, "dataObject")}
        objs |= {(o.text or "").strip() for o in _descendants(fn, "dataObject")}
        cap.supported_objects[fname] = {o for o in objs if o}
    cap.raw = etree.tostring(root, encoding="unicode")
    return cap


def _int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value.strip()))
    except (ValueError, AttributeError):
        return None
