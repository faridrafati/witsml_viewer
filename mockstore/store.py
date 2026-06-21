"""In-memory WITSML 1.4.1.1 store.

Holds wells, wellbores, logs (header + growing logData rows) and mudLogs
(geologyInterval / lithology). Parses incoming WITSML XML with lxml and serves
GetFromStore queries honouring the OptionsIn semantics the project's client and
parser rely on (returnElements, maxReturnNodes +2 truncation,
requestLatestValues, inclusive index ranges, direction, intervalRangeInclusion).

Namespace-agnostic on the way IN (matching is by local-name, like
app.witsml.parse) and emits the data namespace as the default on the way OUT so
app.witsml.parse reads it back without a prefix.

Return codes follow app.witsml.constants:
  +1  full success                  (RC_SUCCESS)
  +2  success but result truncated  (RC_PARTIAL_SUCCESS) — drives the client +2 loop
  <0  error                         (negative; SuppMsgOut carries the reason)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

from lxml import etree

from app.witsml.constants import (
    DEFAULT_NULL_VALUE,
    NS_API,
    NS_DATA,
    WITSML_VERSION,
    Direction,
    IndexType,
)

# ── Return codes (mirror app.witsml.constants RC_*) ─────────────────────────
RC_SUCCESS = 1
RC_PARTIAL_SUCCESS = 2
RC_ERROR_DUPLICATE = -405  # WITSML "object already exists"
RC_ERROR_NOT_FOUND = -411  # query matched nothing addressable
RC_ERROR_BAD_INPUT = -407  # malformed XMLin / QueryIn

XmlLike = str | bytes | etree._Element


# ── lxml local-name helpers (mirror app.witsml.parse) ───────────────────────
def _to_tree(xml: XmlLike) -> etree._Element:
    if isinstance(xml, etree._Element):
        return xml
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
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


def _root_or_first(root: etree._Element, name: str) -> etree._Element | None:
    """The object element: a `<name>` child, or `root` itself if it IS one.

    Uses explicit `is not None` — never element truth-testing (deprecated in
    lxml and false for childless elements).
    """
    el = _first(root, name)
    if el is None and _local(root) == name:
        el = root
    return el


def _text(parent: etree._Element, name: str) -> str | None:
    el = _first(parent, name)
    if el is None or el.text is None:
        return None
    txt = el.text.strip()
    return txt or None


def _descendants(root: etree._Element, name: str) -> list[etree._Element]:
    return [e for e in root.iter() if isinstance(e.tag, str) and _local(e) == name]


# ── OptionsIn parsing ───────────────────────────────────────────────────────
def parse_options(options_in: str | None) -> dict[str, str]:
    """Parse a "k1=v1;k2=v2" OptionsIn string into a dict (case-insensitive keys)."""
    out: dict[str, str] = {}
    if not options_in:
        return out
    for part in options_in.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, _, value = part.partition("=")
        out[key.strip().lower()] = value.strip()
    return out


# ── Index value coercion ────────────────────────────────────────────────────
def _parse_index(token: str | None, index_type: IndexType) -> float | datetime | None:
    if token is None:
        return None
    s = token.strip()
    if not s:
        return None
    if index_type.is_time:
        return _parse_dt(s)
    try:
        return float(s)
    except ValueError:
        return None


def _parse_dt(value: str) -> datetime | None:
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


# ── Stored object models ────────────────────────────────────────────────────
@dataclass
class CurveMeta:
    mnemonic: str
    unit: str | None = None
    description: str | None = None
    type_log_data: str | None = None
    null_value: str | None = None


@dataclass
class StoredLog:
    uid: str
    uid_well: str
    uid_wellbore: str
    name: str | None = None
    name_well: str | None = None
    name_wellbore: str | None = None
    index_type: IndexType = IndexType.MEASURED_DEPTH
    index_curve: str | None = None
    direction: Direction = Direction.INCREASING
    null_value: str = DEFAULT_NULL_VALUE
    index_uom: str | None = None
    object_growing: bool = False
    curves: list[CurveMeta] = field(default_factory=list)
    # rows: index value (float|datetime) -> list of raw string cells (incl. index)
    rows: dict[object, list[str]] = field(default_factory=dict)

    @property
    def mnemonics(self) -> list[str]:
        return [c.mnemonic for c in self.curves]

    @property
    def units(self) -> list[str | None]:
        return [c.unit for c in self.curves]

    def sorted_indices(self, direction: Direction | None = None) -> list[object]:
        d = direction or self.direction
        return sorted(self.rows.keys(), reverse=(d == Direction.DECREASING))


@dataclass
class StoredMudLog:
    uid: str
    uid_well: str
    uid_wellbore: str
    name: str | None = None
    name_well: str | None = None
    name_wellbore: str | None = None
    object_growing: bool = False
    # raw <geologyInterval> elements, kept verbatim for faithful echo-back
    intervals: list[etree._Element] = field(default_factory=list)


@dataclass
class StoredWell:
    uid: str
    element: etree._Element  # verbatim <well>


@dataclass
class StoredWellbore:
    uid: str
    uid_well: str
    element: etree._Element  # verbatim <wellbore>


# ── The store ───────────────────────────────────────────────────────────────
class MockStore:
    """Thread-safe in-memory WITSML 1.4.1.1 store."""

    def __init__(
        self,
        *,
        server_name: str = "WITSML Mock Store",
        max_data_nodes: int = 100000,
        max_data_points: int = 1000000,
        max_request_latest_values: int = 10000,
        growing_timeout_period: int = 300,
        change_detection_period: int = 5,
    ) -> None:
        self._lock = threading.RLock()
        self.wells: dict[str, StoredWell] = {}
        self.wellbores: dict[str, StoredWellbore] = {}
        self.logs: dict[str, StoredLog] = {}
        self.mudlogs: dict[str, StoredMudLog] = {}
        self.server_name = server_name
        self.max_data_nodes = max_data_nodes
        self.max_data_points = max_data_points
        self.max_request_latest_values = max_request_latest_values
        self.growing_timeout_period = growing_timeout_period
        self.change_detection_period = change_detection_period

    # ── keys ────────────────────────────────────────────────────────────────
    @staticmethod
    def _log_key(uid_well: str, uid_wellbore: str, uid: str) -> tuple[str, str, str]:
        return (uid_well, uid_wellbore, uid)

    # ════════════════════════════════════════════════════════════════════════
    #  AddToStore
    # ════════════════════════════════════════════════════════════════════════
    def add_object(self, wml_type: str, xml: str) -> tuple[int, str | None]:
        """Dispatch AddToStore by WMLtypeIn. Returns (return_code, supp_msg)."""
        wml_type = (wml_type or "").strip().lower()
        try:
            root = _to_tree(xml)
        except Exception as exc:  # noqa: BLE001
            return RC_ERROR_BAD_INPUT, f"malformed XMLin: {exc}"
        if root is None:
            return RC_ERROR_BAD_INPUT, "empty XMLin"

        with self._lock:
            if wml_type == "well":
                return self._add_well(root)
            if wml_type == "wellbore":
                return self._add_wellbore(root)
            if wml_type == "log":
                return self._add_log(root)
            if wml_type == "mudlog":
                return self._add_mudlog(root)
        return RC_ERROR_BAD_INPUT, f"unsupported WMLtypeIn '{wml_type}'"

    def _add_well(self, root: etree._Element) -> tuple[int, str | None]:
        el = _root_or_first(root, "well")
        if el is None:
            return RC_ERROR_BAD_INPUT, "no <well> element in XMLin"
        uid = el.get("uid") or ""
        if not uid:
            return RC_ERROR_BAD_INPUT, "<well> missing uid"
        if uid in self.wells:
            return RC_ERROR_DUPLICATE, f"well uid '{uid}' already exists"
        self.wells[uid] = StoredWell(uid=uid, element=el)
        return RC_SUCCESS, None

    def _add_wellbore(self, root: etree._Element) -> tuple[int, str | None]:
        el = _root_or_first(root, "wellbore")
        if el is None:
            return RC_ERROR_BAD_INPUT, "no <wellbore> element in XMLin"
        uid = el.get("uid") or ""
        uid_well = el.get("uidWell") or ""
        if not uid:
            return RC_ERROR_BAD_INPUT, "<wellbore> missing uid"
        key = f"{uid_well}/{uid}"
        if key in self.wellbores:
            return RC_ERROR_DUPLICATE, f"wellbore uid '{uid}' already exists"
        self.wellbores[key] = StoredWellbore(uid=uid, uid_well=uid_well, element=el)
        return RC_SUCCESS, None

    def _add_log(self, root: etree._Element) -> tuple[int, str | None]:
        el = _root_or_first(root, "log")
        if el is None:
            return RC_ERROR_BAD_INPUT, "no <log> element in XMLin"
        uid = el.get("uid") or ""
        uid_well = el.get("uidWell") or ""
        uid_wellbore = el.get("uidWellbore") or ""
        if not uid:
            return RC_ERROR_BAD_INPUT, "<log> missing uid"
        key = self._log_key(uid_well, uid_wellbore, uid)
        if key in self.logs:
            return RC_ERROR_DUPLICATE, f"log uid '{uid}' already exists"

        index_type = _index_type(_text(el, "indexType"))
        log = StoredLog(
            uid=uid,
            uid_well=uid_well,
            uid_wellbore=uid_wellbore,
            name=_text(el, "name"),
            name_well=_text(el, "nameWell"),
            name_wellbore=_text(el, "nameWellbore"),
            index_type=index_type,
            index_curve=_text(el, "indexCurve"),
            direction=_direction(_text(el, "direction")),
            null_value=_text(el, "nullValue") or DEFAULT_NULL_VALUE,
        )
        # index uom from startIndex/endIndex (depth logs)
        si = _first(el, "startIndex")
        if si is not None and si.get("uom"):
            log.index_uom = si.get("uom")

        for lci in _children(el, "logCurveInfo"):
            log.curves.append(
                CurveMeta(
                    mnemonic=_text(lci, "mnemonic") or "",
                    unit=_text(lci, "unit"),
                    description=_text(lci, "curveDescription"),
                    type_log_data=_text(lci, "typeLogData"),
                    null_value=_text(lci, "nullValue"),
                )
            )
        if not log.index_curve and log.curves:
            log.index_curve = log.curves[0].mnemonic
        if log.index_uom is None and log.curves:
            log.index_uom = log.curves[0].unit

        # seed any data rows shipped with the create
        self._ingest_logdata(log, el)
        self.logs[key] = log
        return RC_SUCCESS, None

    def _add_mudlog(self, root: etree._Element) -> tuple[int, str | None]:
        el = _root_or_first(root, "mudLog")
        if el is None:
            return RC_ERROR_BAD_INPUT, "no <mudLog> element in XMLin"
        uid = el.get("uid") or ""
        uid_well = el.get("uidWell") or ""
        uid_wellbore = el.get("uidWellbore") or ""
        if not uid:
            return RC_ERROR_BAD_INPUT, "<mudLog> missing uid"
        key = self._log_key(uid_well, uid_wellbore, uid)
        if key in self.mudlogs:
            return RC_ERROR_DUPLICATE, f"mudLog uid '{uid}' already exists"
        ml = StoredMudLog(
            uid=uid,
            uid_well=uid_well,
            uid_wellbore=uid_wellbore,
            name=_text(el, "name"),
            name_well=_text(el, "nameWell"),
            name_wellbore=_text(el, "nameWellbore"),
        )
        for gi in _children(el, "geologyInterval"):
            ml.intervals.append(gi)
        self.mudlogs[key] = ml
        return RC_SUCCESS, None

    # ════════════════════════════════════════════════════════════════════════
    #  UpdateInStore (append growing-log rows)
    # ════════════════════════════════════════════════════════════════════════
    def update_object(self, wml_type: str, xml: str) -> tuple[int, str | None]:
        wml_type = (wml_type or "").strip().lower()
        try:
            root = _to_tree(xml)
        except Exception as exc:  # noqa: BLE001
            return RC_ERROR_BAD_INPUT, f"malformed XMLin: {exc}"
        if root is None:
            return RC_ERROR_BAD_INPUT, "empty XMLin"

        with self._lock:
            if wml_type == "log":
                return self._update_log(root)
            if wml_type == "mudlog":
                return self._update_mudlog(root)
            if wml_type in ("well", "wellbore"):
                # No-op acceptance for header updates we don't model in detail.
                return RC_SUCCESS, None
        return RC_ERROR_BAD_INPUT, f"unsupported WMLtypeIn '{wml_type}'"

    def _update_log(self, root: etree._Element) -> tuple[int, str | None]:
        el = _root_or_first(root, "log")
        if el is None:
            return RC_ERROR_BAD_INPUT, "no <log> element in XMLin"
        uid = el.get("uid") or ""
        uid_well = el.get("uidWell") or ""
        uid_wellbore = el.get("uidWellbore") or ""
        key = self._log_key(uid_well, uid_wellbore, uid)
        log = self.logs.get(key)
        if log is None:
            return RC_ERROR_NOT_FOUND, f"log uid '{uid}' not found for update"
        added = self._ingest_logdata(log, el)
        if added:
            log.object_growing = True
        return RC_SUCCESS, None

    def _update_mudlog(self, root: etree._Element) -> tuple[int, str | None]:
        el = _root_or_first(root, "mudLog")
        if el is None:
            return RC_ERROR_BAD_INPUT, "no <mudLog> element in XMLin"
        uid = el.get("uid") or ""
        uid_well = el.get("uidWell") or ""
        uid_wellbore = el.get("uidWellbore") or ""
        key = self._log_key(uid_well, uid_wellbore, uid)
        ml = self.mudlogs.get(key)
        if ml is None:
            return RC_ERROR_NOT_FOUND, f"mudLog uid '{uid}' not found for update"
        new = _children(el, "geologyInterval")
        if new:
            ml.intervals.extend(new)
            ml.object_growing = True
        return RC_SUCCESS, None

    def _ingest_logdata(self, log: StoredLog, log_el: etree._Element) -> int:
        """Parse a <logData> block under log_el and merge rows into the store.

        Aligns incoming columns to the stored curve order via mnemonicList.
        Returns the number of rows added/updated.
        """
        ld = _first(log_el, "logData")
        if ld is None:
            return 0
        mnem_list = _text(ld, "mnemonicList")
        if mnem_list:
            incoming = [m.strip() for m in mnem_list.split(",")]
        else:
            incoming = log.mnemonics
        if not incoming:
            return 0

        # Build a column permutation: store column j <- incoming column src[j]
        store_cols = log.mnemonics or incoming
        index_pos = 0  # index curve is always first
        added = 0
        for data_el in _children(ld, "data"):
            if data_el.text is None:
                continue
            cells = [c.strip() for c in data_el.text.split(",")]
            if not cells:
                continue
            # map incoming cells by mnemonic
            value_by_mnem = {
                incoming[i]: cells[i] for i in range(min(len(incoming), len(cells)))
            }
            index_token = cells[index_pos] if cells else ""
            idx_val = _parse_index(index_token, log.index_type)
            if idx_val is None:
                continue
            # assemble a full row in store column order
            row = [value_by_mnem.get(m, log.null_value) for m in store_cols]
            # store index cell verbatim (preserve the exact token written)
            row[0] = index_token
            log.rows[idx_val] = row
            added += 1
        return added

    # ════════════════════════════════════════════════════════════════════════
    #  DeleteFromStore (minimal: by uid)
    # ════════════════════════════════════════════════════════════════════════
    def delete_object(self, wml_type: str, query_xml: str) -> tuple[int, str | None]:
        wml_type = (wml_type or "").strip().lower()
        try:
            root = _to_tree(query_xml)
        except Exception as exc:  # noqa: BLE001
            return RC_ERROR_BAD_INPUT, f"malformed QueryIn: {exc}"
        with self._lock:
            if wml_type == "well":
                el = _first(root, "well")
                uid = el.get("uid") if el is not None else None
                if uid and uid in self.wells:
                    del self.wells[uid]
                    return RC_SUCCESS, None
            elif wml_type == "wellbore":
                el = _first(root, "wellbore")
                if el is not None:
                    key = f"{el.get('uidWell') or ''}/{el.get('uid') or ''}"
                    if key in self.wellbores:
                        del self.wellbores[key]
                        return RC_SUCCESS, None
            elif wml_type in ("log", "mudlog"):
                tag = "log" if wml_type == "log" else "mudLog"
                target = self.logs if wml_type == "log" else self.mudlogs
                el = _first(root, tag)
                if el is not None:
                    key = self._log_key(
                        el.get("uidWell") or "",
                        el.get("uidWellbore") or "",
                        el.get("uid") or "",
                    )
                    if key in target:
                        del target[key]
                        return RC_SUCCESS, None
        return RC_ERROR_NOT_FOUND, "nothing matched the delete query"

    # ════════════════════════════════════════════════════════════════════════
    #  GetFromStore
    # ════════════════════════════════════════════════════════════════════════
    def query(
        self, wml_type: str, query_xml: str, options_in: str | None
    ) -> tuple[int, str, str | None]:
        """Dispatch GetFromStore. Returns (return_code, xml_out, supp_msg)."""
        wml_type = (wml_type or "").strip().lower()
        opts = parse_options(options_in)
        try:
            root = _to_tree(query_xml)
        except Exception as exc:  # noqa: BLE001
            return RC_ERROR_BAD_INPUT, "", f"malformed QueryIn: {exc}"

        with self._lock:
            if wml_type == "well":
                return self._query_wells(root, opts)
            if wml_type == "wellbore":
                return self._query_wellbores(root, opts)
            if wml_type == "log":
                return self._query_logs(root, opts)
            if wml_type == "mudlog":
                return self._query_mudlogs(root, opts)
        return RC_ERROR_BAD_INPUT, "", f"unsupported WMLtypeIn '{wml_type}'"

    # ── wells / wellbores ─────────────────────────────────────────────────
    def _query_wells(
        self, root: etree._Element, opts: dict[str, str]
    ) -> tuple[int, str, str | None]:
        q = _first(root, "well")
        want_uid = q.get("uid") if q is not None else None
        out = _new_root("wells")
        for w in self.wells.values():
            if want_uid and w.uid != want_uid:
                continue
            out.append(_clone(w.element))
        return RC_SUCCESS, _serialize(out), None

    def _query_wellbores(
        self, root: etree._Element, opts: dict[str, str]
    ) -> tuple[int, str, str | None]:
        q = _first(root, "wellbore")
        want_uid = q.get("uid") if q is not None else None
        want_well = q.get("uidWell") if q is not None else None
        out = _new_root("wellbores")
        for wb in self.wellbores.values():
            if want_uid and wb.uid != want_uid:
                continue
            if want_well and wb.uid_well != want_well:
                continue
            out.append(_clone(wb.element))
        return RC_SUCCESS, _serialize(out), None

    # ── logs ──────────────────────────────────────────────────────────────
    def _query_logs(
        self, root: etree._Element, opts: dict[str, str]
    ) -> tuple[int, str, str | None]:
        q = _first(root, "log")
        if q is None:
            return RC_ERROR_BAD_INPUT, "", "QueryIn has no <log> element"
        want_uid = q.get("uid") or None
        want_well = q.get("uidWell") or None
        want_wellbore = q.get("uidWellbore") or None

        return_elements = opts.get("returnelements", "all").lower()
        max_nodes = _int(opts.get("maxreturnnodes"))
        latest_n = _int(opts.get("requestlatestvalues"))

        matches: list[StoredLog] = []
        for log in self.logs.values():
            if want_uid and log.uid != want_uid:
                continue
            if want_well and log.uid_well != want_well:
                continue
            if want_wellbore and log.uid_wellbore != want_wellbore:
                continue
            matches.append(log)

        out = _new_root("logs")
        truncated = False
        for log in matches:
            # Parse requested start/end from the query element (time vs depth)
            start, end = _query_range(q, log.index_type)
            direction = log.direction
            log_el, was_truncated = self._render_log(
                log,
                return_elements=return_elements,
                start=start,
                end=end,
                direction=direction,
                max_nodes=max_nodes,
                latest_n=latest_n,
            )
            out.append(log_el)
            truncated = truncated or was_truncated

        rc = RC_PARTIAL_SUCCESS if truncated else RC_SUCCESS
        return rc, _serialize(out), None

    def _render_log(
        self,
        log: StoredLog,
        *,
        return_elements: str,
        start: object,
        end: object,
        direction: Direction,
        max_nodes: int | None,
        latest_n: int | None,
    ) -> tuple[etree._Element, bool]:
        log_el = _data_el(
            "log",
            uid=log.uid,
            uidWell=log.uid_well,
            uidWellbore=log.uid_wellbore,
        )
        want_header = return_elements in ("all", "header-only", "requested")
        want_data = return_elements in ("all", "data-only", "requested")
        id_only = return_elements == "id-only"

        if id_only:
            # identity only — attributes already set; add nameWell etc for tree
            _sub(log_el, "nameWell", log.name_well)
            _sub(log_el, "nameWellbore", log.name_wellbore)
            _sub(log_el, "name", log.name)
            return log_el, False

        if want_header:
            _sub(log_el, "nameWell", log.name_well)
            _sub(log_el, "nameWellbore", log.name_wellbore)
            _sub(log_el, "name", log.name)
            _sub(log_el, "indexType", log.index_type.value)
            _sub(log_el, "indexCurve", log.index_curve)
            _sub(log_el, "direction", log.direction.value)
            _sub(log_el, "objectGrowing", "true" if log.object_growing else "false")
            _sub(log_el, "nullValue", log.null_value)
            self._emit_extents(log_el, log)
            for c in log.curves:
                lci = _sub(log_el, "logCurveInfo")
                _sub(lci, "mnemonic", c.mnemonic)
                _sub(lci, "unit", c.unit)
                if c.description:
                    _sub(lci, "curveDescription", c.description)
                if c.type_log_data:
                    _sub(lci, "typeLogData", c.type_log_data)
                _sub(lci, "nullValue", c.null_value or log.null_value)
                self._emit_curve_extents(lci, log, c.mnemonic)

        truncated = False
        if want_data:
            rows, truncated = self._select_rows(
                log,
                start=start,
                end=end,
                direction=direction,
                max_nodes=max_nodes,
                latest_n=latest_n,
            )
            if rows:
                ld = _sub(log_el, "logData")
                _sub(ld, "mnemonicList", ",".join(log.mnemonics))
                _sub(ld, "unitList", ",".join(u or "" for u in log.units))
                for row in rows:
                    _sub(ld, "data", ",".join(row))
        return log_el, truncated

    def _select_rows(
        self,
        log: StoredLog,
        *,
        start: object,
        end: object,
        direction: Direction,
        max_nodes: int | None,
        latest_n: int | None,
    ) -> tuple[list[list[str]], bool]:
        """Return (rows, truncated) honouring range, direction, latest, cap."""
        # requestLatestValues: latest n PER curve, ignore start/end.
        if latest_n is not None and latest_n > 0:
            return self._latest_value_rows(log, latest_n), False

        ordered = log.sorted_indices(direction)
        selected: list[object] = []
        for idx in ordered:
            if start is not None and _before(idx, start, direction):
                continue
            if end is not None and _after(idx, end, direction):
                continue
            selected.append(idx)

        truncated = False
        if max_nodes is not None and max_nodes > 0 and len(selected) > max_nodes:
            selected = selected[:max_nodes]
            truncated = True

        rows = [log.rows[idx] for idx in selected]
        return rows, truncated

    def _latest_value_rows(self, log: StoredLog, n: int) -> list[list[str]]:
        """Latest n values PER non-index curve, emitted as sparse rows.

        For each curve, take the n most-recent rows (by direction) whose cell
        is non-null. Emit one sparse row per (index) carrying only the curves
        that have a value at that index; index is always present.
        """
        n = min(n, self.max_request_latest_values)
        ordered = log.sorted_indices(log.direction)  # newest first if decreasing?
        # "latest" = highest index for increasing, lowest for decreasing.
        # sorted_indices already applies that ordering with reverse for decreasing,
        # so the LAST element is the newest. Reverse to get newest-first.
        newest_first = list(reversed(ordered))
        nulls = self._null_set(log)

        keep_indices: set[object] = set()
        cols = log.mnemonics
        for col in range(1, len(cols)):
            count = 0
            for idx in newest_first:
                row = log.rows[idx]
                if col >= len(row):
                    continue
                cell = row[col].strip()
                if cell == "" or cell in nulls:
                    continue
                keep_indices.add(idx)
                count += 1
                if count >= n:
                    break

        # Emit sparse rows: for kept indices, blank out cells that are null so
        # the client's merge_sparse_rows can recombine.
        out: list[list[str]] = []
        for idx in sorted(keep_indices, key=_sort_key):
            row = log.rows[idx]
            sparse = [row[0]]
            for col in range(1, len(cols)):
                cell = row[col] if col < len(row) else ""
                if cell.strip() in nulls:
                    sparse.append(log.null_value)
                else:
                    sparse.append(cell)
            out.append(sparse)
        return out

    def _null_set(self, log: StoredLog) -> set[str]:
        nulls = {log.null_value, DEFAULT_NULL_VALUE, ""}
        for c in log.curves:
            if c.null_value:
                nulls.add(c.null_value)
        return nulls

    def _emit_extents(self, log_el: etree._Element, log: StoredLog) -> None:
        idxs = list(log.rows.keys())
        if not idxs:
            return
        lo, hi = min(idxs), max(idxs)
        if log.index_type.is_time:
            _sub(log_el, "startDateTimeIndex", log.rows[lo][0])
            _sub(log_el, "endDateTimeIndex", log.rows[hi][0])
        else:
            _sub(log_el, "startIndex", log.rows[lo][0], uom=log.index_uom or "")
            _sub(log_el, "endIndex", log.rows[hi][0], uom=log.index_uom or "")

    def _emit_curve_extents(
        self, lci: etree._Element, log: StoredLog, mnemonic: str
    ) -> None:
        col = log.mnemonics.index(mnemonic) if mnemonic in log.mnemonics else -1
        if col < 0 or not log.rows:
            return
        nulls = self._null_set(log)
        present: list[object] = []
        for idx, row in log.rows.items():
            if col >= len(row):
                continue
            if row[col].strip() in nulls and col != 0:
                continue
            present.append(idx)
        if not present:
            return
        lo, hi = min(present), max(present)
        if log.index_type.is_time:
            _sub(lci, "minDateTimeIndex", log.rows[lo][0])
            _sub(lci, "maxDateTimeIndex", log.rows[hi][0])
        else:
            _sub(lci, "minIndex", log.rows[lo][0], uom=log.index_uom or "")
            _sub(lci, "maxIndex", log.rows[hi][0], uom=log.index_uom or "")

    # ── mudLogs ───────────────────────────────────────────────────────────
    def _query_mudlogs(
        self, root: etree._Element, opts: dict[str, str]
    ) -> tuple[int, str, str | None]:
        q = _first(root, "mudLog")
        want_uid = q.get("uid") or None if q is not None else None
        want_well = q.get("uidWell") or None if q is not None else None
        want_wellbore = q.get("uidWellbore") or None if q is not None else None

        inclusion = opts.get("intervalrangeinclusion", "any-part").lower()
        md_top, md_bottom = _mudlog_range(q)

        out = _new_root("mudLogs")
        for ml in self.mudlogs.values():
            if want_uid and ml.uid != want_uid:
                continue
            if want_well and ml.uid_well != want_well:
                continue
            if want_wellbore and ml.uid_wellbore != want_wellbore:
                continue
            ml_el = _data_el(
                "mudLog",
                uid=ml.uid,
                uidWell=ml.uid_well,
                uidWellbore=ml.uid_wellbore,
            )
            _sub(ml_el, "nameWell", ml.name_well)
            _sub(ml_el, "nameWellbore", ml.name_wellbore)
            _sub(ml_el, "name", ml.name)
            _sub(ml_el, "objectGrowing", "true" if ml.object_growing else "false")
            for gi in ml.intervals:
                if not _interval_in_range(gi, md_top, md_bottom, inclusion):
                    continue
                ml_el.append(_clone(gi))
            out.append(ml_el)
        return RC_SUCCESS, _serialize(out), None

    # ════════════════════════════════════════════════════════════════════════
    #  GetCap
    # ════════════════════════════════════════════════════════════════════════
    def capabilities_xml(self) -> str:
        """Build a <capServer> doc parse_cap can read (NS_API namespace)."""
        ns = NS_API
        root = etree.Element(f"{{{ns}}}capServers", nsmap={None: ns})
        root.set("version", WITSML_VERSION)
        server = etree.SubElement(root, f"{{{ns}}}capServer")
        server.set("apiVers", WITSML_VERSION)

        def _e(parent: etree._Element, tag: str, text: str) -> etree._Element:
            child = etree.SubElement(parent, f"{{{ns}}}{tag}")
            child.text = text
            return child

        _e(server, "name", self.server_name)
        _e(server, "vendor", "Mock")
        _e(server, "version", WITSML_VERSION)
        _e(server, "schemaVersion", WITSML_VERSION)
        _e(server, "growingTimeoutPeriod", str(self.growing_timeout_period))
        _e(server, "maxDataNodes", str(self.max_data_nodes))
        _e(server, "maxDataPoints", str(self.max_data_points))
        _e(server, "changeDetectionPeriod", str(self.change_detection_period))
        _e(server, "maxRequestLatestValues", str(self.max_request_latest_values))

        supported = ["well", "wellbore", "log", "mudLog", "trajectory"]
        for fn_name in (
            "WMLS_AddToStore",
            "WMLS_GetFromStore",
            "WMLS_UpdateInStore",
            "WMLS_DeleteFromStore",
        ):
            fn = etree.SubElement(server, f"{{{ns}}}function")
            fn.set("name", fn_name)
            for obj in supported:
                _e(fn, "dataObject", obj)
        return etree.tostring(root, encoding="unicode")


# ── module-level XML emit helpers (data namespace default) ──────────────────
def _new_root(plural: str) -> etree._Element:
    root = etree.Element(f"{{{NS_DATA}}}{plural}", nsmap={None: NS_DATA})
    root.set("version", WITSML_VERSION)
    return root


def _data_el(tag: str, **attrib: str) -> etree._Element:
    el = etree.Element(f"{{{NS_DATA}}}{tag}")
    for k, v in attrib.items():
        if v is not None:
            el.set(k, v)
    return el


def _sub(
    parent: etree._Element, tag: str, text: str | None = None, **attrib: str
) -> etree._Element:
    el = etree.SubElement(parent, f"{{{NS_DATA}}}{tag}")
    for k, v in attrib.items():
        el.set(k, v)
    if text is not None:
        el.text = text
    return el


def _clone(el: etree._Element) -> etree._Element:
    """Deep-copy an element into the data namespace default for clean echo."""
    return etree.fromstring(etree.tostring(el))


def _serialize(root: etree._Element) -> str:
    return etree.tostring(root, encoding="unicode")


# ── small coercion helpers ──────────────────────────────────────────────────
def _int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value.strip()))
    except (ValueError, AttributeError):
        return None


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


def _sort_key(value: object):
    return value


def _before(idx: object, start: object, direction: Direction) -> bool:
    """True if idx is BEFORE the inclusive start boundary for the direction."""
    if direction == Direction.INCREASING:
        return idx < start  # type: ignore[operator]
    return idx > start  # type: ignore[operator]


def _after(idx: object, end: object, direction: Direction) -> bool:
    """True if idx is AFTER the inclusive end boundary for the direction."""
    if direction == Direction.INCREASING:
        return idx > end  # type: ignore[operator]
    return idx < end  # type: ignore[operator]


def _query_range(q: etree._Element, index_type: IndexType) -> tuple[object, object]:
    """Extract (start, end) from a <log> query element, typed by index."""
    if index_type.is_time:
        start = (
            _parse_dt(_text(q, "startDateTimeIndex") or "")
            if _text(q, "startDateTimeIndex")
            else None
        )
        end = (
            _parse_dt(_text(q, "endDateTimeIndex") or "")
            if _text(q, "endDateTimeIndex")
            else None
        )
        return start, end
    s = _text(q, "startIndex")
    e = _text(q, "endIndex")
    start = float(s) if s is not None else None
    end = float(e) if e is not None else None
    return start, end


def _mudlog_range(q: etree._Element | None) -> tuple[float | None, float | None]:
    if q is None:
        return None, None
    md_top = None
    md_bottom = None
    for gi in _children(q, "geologyInterval"):
        t = _text(gi, "mdTop")
        b = _text(gi, "mdBottom")
        if t:
            try:
                md_top = float(t)
            except ValueError:
                pass
        if b:
            try:
                md_bottom = float(b)
            except ValueError:
                pass
    return md_top, md_bottom


def _interval_in_range(
    gi: etree._Element,
    md_top: float | None,
    md_bottom: float | None,
    inclusion: str,
) -> bool:
    """Decide whether a geologyInterval overlaps the requested range."""
    if md_top is None and md_bottom is None:
        return True
    gt = _text(gi, "mdTop")
    gb = _text(gi, "mdBottom")
    try:
        i_top = float(gt) if gt else None
        i_bottom = float(gb) if gb else None
    except ValueError:
        return True
    if i_top is None and i_bottom is None:
        return True
    lo = md_top if md_top is not None else float("-inf")
    hi = md_bottom if md_bottom is not None else float("inf")
    i_lo = i_top if i_top is not None else i_bottom
    i_hi = i_bottom if i_bottom is not None else i_top
    if inclusion == "whole-interval":
        return i_lo >= lo and i_hi <= hi
    if inclusion == "minimum-point":
        return i_lo >= lo and i_lo <= hi
    # any-part (default): keep anything overlapping the range, incl. boundary.
    return i_hi >= lo and i_lo <= hi
