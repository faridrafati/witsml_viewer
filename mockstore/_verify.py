"""End-to-end verification of the mock store against the real zeep client.

Run AFTER starting `uvicorn mockstore.server:app` on 127.0.0.1:7070.
Exercises all 7 acceptance checks through app.witsml.client.WitsmlClient.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from lxml import etree

from app.witsml.client import WitsmlClient
from app.witsml.constants import NS_DATA, WITSML_VERSION, Direction, IndexType

import os

URL = os.environ.get("MOCK_URL", "http://127.0.0.1:7070/witsml/store")
NS = NS_DATA

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


def _record(name: str, ok: bool, detail: str) -> None:
    results.append((name, PASS if ok else FAIL, detail))
    print(f"[{PASS if ok else FAIL}] {name}: {detail}")


def _e(parent, tag, text=None, **attrib):
    el = etree.SubElement(parent, f"{{{NS}}}{tag}")
    for k, v in attrib.items():
        el.set(k, v)
    if text is not None:
        el.text = text
    return el


def _root(plural):
    r = etree.Element(f"{{{NS}}}{plural}", nsmap={None: NS})
    r.set("version", WITSML_VERSION)
    return r


def well_xml() -> str:
    r = _root("wells")
    w = _e(r, "well", uid="W-1")
    _e(w, "name", "Mock Well 1")
    _e(w, "field", "Test Field")
    _e(w, "country", "US")
    _e(w, "operator", "Mock Op")
    _e(w, "statusWell", "drilling")
    _e(w, "timeZone", "+00:00")
    return etree.tostring(r, encoding="unicode")


def wellbore_xml() -> str:
    r = _root("wellbores")
    wb = _e(r, "wellbore", uidWell="W-1", uid="WB-1")
    _e(wb, "nameWell", "Mock Well 1")
    _e(wb, "name", "Wellbore 1")
    _e(wb, "statusWellbore", "drilling")
    return etree.tostring(r, encoding="unicode")


CURVES = [("TIME", "s"), ("ROP", "m/h"), ("WOB", "klbf")]
T0 = datetime(2026, 6, 21, 12, 0, 0, tzinfo=UTC)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def log_create_xml() -> str:
    r = _root("logs")
    log = _e(r, "log", uidWell="W-1", uidWellbore="WB-1", uid="LOG-T")
    _e(log, "nameWell", "Mock Well 1")
    _e(log, "nameWellbore", "Wellbore 1")
    _e(log, "name", "Time Log")
    _e(log, "indexType", "date time")
    _e(log, "indexCurve", "TIME")
    _e(log, "direction", "increasing")
    _e(log, "nullValue", "-999.25")
    _e(log, "startDateTimeIndex", iso(T0))
    _e(log, "endDateTimeIndex", iso(T0))
    for m, u in CURVES:
        lci = _e(log, "logCurveInfo", uid=f"lci-{m}")
        _e(lci, "mnemonic", m)
        _e(lci, "unit", u)
        _e(lci, "typeLogData", "date time" if m == "TIME" else "double")
        _e(lci, "nullValue", "-999.25")
    ld = _e(log, "logData")
    _e(ld, "mnemonicList", ",".join(m for m, _ in CURVES))
    _e(ld, "unitList", ",".join(u for _, u in CURVES))
    _e(ld, "data", f"{iso(T0)},10.0,20.0")
    return etree.tostring(r, encoding="unicode")


def log_update_xml(rows: list[tuple[datetime, float, float]]) -> str:
    r = _root("logs")
    log = _e(r, "log", uidWell="W-1", uidWellbore="WB-1", uid="LOG-T")
    ld = _e(log, "logData")
    _e(ld, "mnemonicList", ",".join(m for m, _ in CURVES))
    _e(ld, "unitList", ",".join(u for _, u in CURVES))
    for dt, rop, wob in rows:
        _e(ld, "data", f"{iso(dt)},{rop},{wob}")
    return etree.tostring(r, encoding="unicode")


def mudlog_xml() -> str:
    r = _root("mudLogs")
    ml = _e(r, "mudLog", uidWell="W-1", uidWellbore="WB-1", uid="ML-1")
    _e(ml, "nameWell", "Mock Well 1")
    _e(ml, "nameWellbore", "Wellbore 1")
    _e(ml, "name", "Geology MudLog")
    gi = _e(ml, "geologyInterval", uid="gi-1")
    _e(gi, "typeLithology", "cuttings")
    _e(gi, "mdTop", "1500", uom="m")
    _e(gi, "mdBottom", "1525", uom="m")
    _e(gi, "description", "sandstone / shale")
    lith = _e(gi, "lithology", uid="gi-1-l1")
    _e(lith, "type", "sandstone")
    _e(lith, "codeLith", "SND")
    _e(lith, "lithPc", "70", uom="%")
    _e(lith, "description", "Sandstone, fine-medium")
    return etree.tostring(r, encoding="unicode")


async def main() -> int:
    client = WitsmlClient(url=URL, username="witsml", password="witsml")

    # 1. get_version
    try:
        v = await client.get_version()
        _record("1 get_version", "1.4.1.1" in v, f"version={v!r}")
    except Exception as exc:  # noqa: BLE001
        _record("1 get_version", False, f"raised {exc!r}")

    # 2. get_cap
    try:
        cap = await client.get_cap()
        ok = cap.version == "1.4.1.1" and bool(cap.supported_objects)
        objs = sorted({o for s in cap.supported_objects.values() for o in s})
        _record(
            "2 get_cap",
            ok,
            f"apiVers={cap.version} name={cap.name!r} objects={objs}",
        )
    except Exception as exc:  # noqa: BLE001
        _record("2 get_cap", False, f"raised {exc!r}")

    # 3. add well / wellbore / log
    try:
        rcw, sw = await client.add_to_store("well", well_xml())
        rcb, sb = await client.add_to_store("wellbore", wellbore_xml())
        rcl, sl = await client.add_to_store("log", log_create_xml())
        ok = rcw == 1 and rcb == 1 and rcl == 1
        _record(
            "3 add_to_store",
            ok,
            f"well={rcw} wellbore={rcb} log={rcl}",
        )
    except Exception as exc:  # noqa: BLE001
        _record("3 add_to_store", False, f"raised {exc!r}")

    # idempotent duplicate check
    try:
        rcdup, sdup = await client.add_to_store("well", well_xml())
        ok = rcdup < 0 and sdup and "already exist" in sdup.lower()
        _record(
            "3b duplicate-uid rejection",
            bool(ok),
            f"rc={rcdup} supp={sdup!r}",
        )
    except Exception as exc:  # noqa: BLE001
        _record("3b duplicate-uid rejection", False, f"raised {exc!r}")

    # 4. update_in_store: append 5 rows; objectGrowing flips true
    try:
        rows = [
            (T0 + timedelta(seconds=5 * i), 10.0 + i, 20.0 + i) for i in range(1, 6)
        ]
        rcu, su = await client.update_in_store("log", log_update_xml(rows))
        # read header to verify objectGrowing
        from app.witsml.queries import log_header_query
        from app.witsml.parse import parse_log_headers

        hq = log_header_query("W-1", "WB-1", "LOG-T")
        _, hx, _ = await client.get_from_store(hq.wml_type, hq.query_xml, hq.options_in)
        headers = parse_log_headers(hx or "")
        growing = headers[0].object_growing if headers else None
        ok = rcu == 1 and growing is True
        _record(
            "4 update_in_store",
            ok,
            f"rc={rcu} objectGrowing={growing}",
        )
    except Exception as exc:  # noqa: BLE001
        _record("4 update_in_store", False, f"raised {exc!r}")

    # 5. get_log_data reads rows back; values/units/index correct, no dup/missing
    try:
        res = await client.get_log_data(
            uid_well="W-1",
            uid_wellbore="WB-1",
            uid="LOG-T",
            mnemonics=["TIME", "ROP", "WOB"],
            index_type=IndexType.DATE_TIME,
            direction=Direction.INCREASING,
        )
        block = res.block
        rows = block.rows
        # Expect 6 rows: seed (T0,10,20) + 5 updates.
        idxs = [r[0] for r in rows]
        expected_idxs = [T0 + timedelta(seconds=5 * i) for i in range(0, 6)]
        rop_vals = [r[1] for r in rows]
        wob_vals = [r[2] for r in rows]
        ok = (
            block.mnemonics == ["TIME", "ROP", "WOB"]
            and block.units == ["s", "m/h", "klbf"]
            and idxs == expected_idxs
            and rop_vals == [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
            and wob_vals == [20.0, 21.0, 22.0, 23.0, 24.0, 25.0]
            and len(idxs) == len(set(idxs))  # no duplicates
        )
        _record(
            "5 get_log_data round-trip",
            ok,
            f"rows={len(rows)} units={block.units} "
            f"rop={rop_vals} wob={wob_vals} dup={len(idxs)!=len(set(idxs))}",
        )
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        _record("5 get_log_data round-trip", False, f"raised {exc!r}")

    # 6. small max_return_nodes -> +2 loop still returns ALL rows
    try:
        res2 = await client.get_log_data(
            uid_well="W-1",
            uid_wellbore="WB-1",
            uid="LOG-T",
            mnemonics=["TIME", "ROP", "WOB"],
            index_type=IndexType.DATE_TIME,
            direction=Direction.INCREASING,
            max_return_nodes=2,
        )
        rows = res2.block.rows
        idxs = [r[0] for r in rows]
        expected_idxs = [T0 + timedelta(seconds=5 * i) for i in range(0, 6)]
        ok = idxs == expected_idxs and len(idxs) == len(set(idxs))
        _record(
            "6 +2 truncation loop (maxReturnNodes=2)",
            ok,
            f"rows={len(rows)} all_present={idxs == expected_idxs} "
            f"dup={len(idxs)!=len(set(idxs))}",
        )
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        _record("6 +2 truncation loop (maxReturnNodes=2)", False, f"raised {exc!r}")

    # 7. mudLog round-trip
    try:
        rcm, sm = await client.add_to_store("mudLog", mudlog_xml())
        from app.witsml.queries import mudlog_query
        from app.witsml.parse import parse_mudlogs

        mq = mudlog_query("W-1", "WB-1", "ML-1")
        _, mx, _ = await client.get_from_store(mq.wml_type, mq.query_xml, mq.options_in)
        muds = parse_mudlogs(mx or "")
        ok = False
        detail = f"add_rc={rcm}"
        if muds:
            ml = muds[0]
            gi = ml.geology_intervals[0] if ml.geology_intervals else None
            if gi and gi.lithologies:
                lith = gi.lithologies[0]
                ok = (
                    rcm == 1
                    and gi.md_top == 1500.0
                    and gi.md_bottom == 1525.0
                    and lith.type == "sandstone"
                    and lith.lith_pc == 70.0
                )
                detail = (
                    f"add_rc={rcm} intervals={len(ml.geology_intervals)} "
                    f"mdTop={gi.md_top} mdBottom={gi.md_bottom} "
                    f"lith={lith.type} lithPc={lith.lith_pc}"
                )
        _record("7 mudLog round-trip", ok, detail)
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        _record("7 mudLog round-trip", False, f"raised {exc!r}")

    await client.aclose()

    print("\n==== SUMMARY ====")
    n_pass = sum(1 for _, s, _ in results if s == PASS)
    for name, status, detail in results:
        print(f"  [{status}] {name}")
    print(f"  {n_pass}/{len(results)} checks passed")
    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
