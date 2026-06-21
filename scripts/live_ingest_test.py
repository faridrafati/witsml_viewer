"""Live Phase-2 integration test: real IngestionScheduler vs the mock store.

Set env BEFORE importing app.* so cached settings/engine/client pick it up.
"""

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone

os.environ["WITSML_URL"] = "http://127.0.0.1:8090/witsml/store"
os.environ["WITSML_USERNAME"] = "witsml"
os.environ["WITSML_PASSWORD"] = "witsml"
os.environ["POLL_INTERVAL_SECONDS"] = "2"
os.environ["INGEST_STAGGER_MS"] = "20"
os.environ["INGEST_CONCURRENCY"] = "4"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./_ingest_test.db"

# fresh DB
for f in ("_ingest_test.db",):
    try:
        os.remove(f)
    except FileNotFoundError:
        pass

from lxml import etree  # noqa: E402

from app.db.base import init_models  # noqa: E402
from app.ingestion.scheduler import IngestionScheduler  # noqa: E402
from app.ingestion.store import get_store  # noqa: E402
from app.witsml.client import get_default_client  # noqa: E402
from app.witsml.constants import NS_DATA, WITSML_VERSION  # noqa: E402

NS = NS_DATA
T0 = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
CURVES = [("TIME", "s"), ("ROP", "m/h"), ("WOB", "klbf")]


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _root(plural):
    r = etree.Element(f"{{{NS}}}{plural}", nsmap={None: NS})
    r.set("version", WITSML_VERSION)
    return r


def _e(p, tag, text=None, **attrib):
    el = etree.SubElement(p, f"{{{NS}}}{tag}")
    for k, v in attrib.items():
        el.set(k, v)
    if text is not None:
        el.text = text
    return el


def well_xml(uid, name):
    r = _root("wells")
    w = _e(r, "well", uid=uid)
    _e(w, "name", name)
    _e(w, "field", "IntegrationField")
    _e(w, "region", "North")
    _e(w, "statusWell", "drilling")
    return etree.tostring(r, encoding="unicode")


def wellbore_xml(uid_well, uid):
    r = _root("wellbores")
    wb = _e(r, "wellbore", uidWell=uid_well, uid=uid)
    _e(wb, "nameWell", uid_well)
    _e(wb, "name", "WB-1")
    _e(wb, "statusWellbore", "drilling")
    return etree.tostring(r, encoding="unicode")


def log_xml(uid_well, uid_wb, uid_log, n_rows, start=0):
    r = _root("logs")
    log = _e(r, "log", uidWell=uid_well, uidWellbore=uid_wb, uid=uid_log)
    _e(log, "nameWell", uid_well)
    _e(log, "nameWellbore", "WB-1")
    _e(log, "name", "Time Log")
    _e(log, "indexType", "date time")
    _e(log, "indexCurve", "TIME")
    _e(log, "direction", "increasing")
    _e(log, "nullValue", "-999.25")
    for m, u in CURVES:
        lci = _e(log, "logCurveInfo", uid=f"lci-{m}")
        _e(lci, "mnemonic", m)
        _e(lci, "unit", u)
        _e(lci, "typeLogData", "date time" if m == "TIME" else "double")
    ld = _e(log, "logData")
    _e(ld, "mnemonicList", ",".join(m for m, _ in CURVES))
    _e(ld, "unitList", ",".join(u for _, u in CURVES))
    for i in range(start, start + n_rows):
        _e(ld, "data", f"{_iso(T0 + timedelta(seconds=5*i))},{10.0+i},{20.0+i}")
    return etree.tostring(r, encoding="unicode")


def log_update_xml(uid_well, uid_wb, uid_log, start, n_rows):
    r = _root("logs")
    log = _e(r, "log", uidWell=uid_well, uidWellbore=uid_wb, uid=uid_log)
    ld = _e(log, "logData")
    _e(ld, "mnemonicList", ",".join(m for m, _ in CURVES))
    _e(ld, "unitList", ",".join(u for _, u in CURVES))
    for i in range(start, start + n_rows):
        _e(ld, "data", f"{_iso(T0 + timedelta(seconds=5*i))},{10.0+i},{20.0+i}")
    return etree.tostring(r, encoding="unicode")


_RUN = str(int(time.time()))[-6:]
WELLS = [
    (f"WELL-A-{_RUN}", "Integration Well A"),
    (f"WELL-B-{_RUN}", "Integration Well B"),
]
fails = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        fails.append(name)


async def main():
    await init_models()
    client = get_default_client()
    store = get_store()

    # ── seed two wells, each with a growing TIME log (4 rows), then make them
    #    growing via an UpdateInStore append. ──
    for uid, name in WELLS:
        rc, _ = await client.add_to_store("well", well_xml(uid, name))
        check(f"seed well {uid}", rc == 1, f"rc={rc}")
        await client.add_to_store("wellbore", wellbore_xml(uid, "WB-1"))
        await client.add_to_store("log", log_xml(uid, "WB-1", "LOG-T", n_rows=4, start=0))
        await client.update_in_store("log", log_update_xml(uid, "WB-1", "LOG-T", start=4, n_rows=2))

    # ── run scheduler for ~3 ticks ──
    sched = IngestionScheduler()
    await sched.start()
    await asyncio.sleep(7)

    statuses = {s.well_uid: s for s in store.well_status()}
    check("both wells discovered+ingested", set(WELLS_uids()) <= set(statuses), f"have={list(statuses)}")
    for uid, _ in WELLS:
        st = statuses.get(uid)
        rec = store.get_recent(uid, ["TIME", "ROP", "WOB"])
        rop = rec.get("ROP", [])
        idxs = [s.index for s in rop]
        check(f"{uid} has samples", bool(rop) and st and st.sample_count > 0, f"rop={len(rop)} count={st.sample_count if st else 0}")
        check(f"{uid} no duplicate indices", len(idxs) == len(set(idxs)), f"n={len(idxs)} uniq={len(set(idxs))}")
        check(f"{uid} growing flag", bool(st and st.growing), "")

    # capture counts, append MORE rows to the mock, wait a tick, assert growth no-dup
    before = {uid: len(store.get_recent(uid, ["ROP"]).get("ROP", [])) for uid, _ in WELLS}
    for uid, _ in WELLS:
        await client.update_in_store("log", log_update_xml(uid, "WB-1", "LOG-T", start=6, n_rows=3))
    await asyncio.sleep(5)
    for uid, _ in WELLS:
        rec = store.get_recent(uid, ["ROP"]).get("ROP", [])
        idxs = [s.index for s in rec]
        check(f"{uid} appended new rows", len(rec) > before[uid], f"{before[uid]} -> {len(rec)}")
        check(f"{uid} still no dupes after append", len(idxs) == len(set(idxs)), f"n={len(idxs)}")

    await sched.stop()

    # ── restart/resume: a NEW scheduler must resume from the Postgres snapshot
    #    (last_index), not re-pull history. ──
    from app.db.base import SessionLocal
    from app.db.models import IndexCacheSnapshot
    from sqlalchemy import select

    async with SessionLocal() as s:
        snaps = (await s.execute(select(IndexCacheSnapshot))).scalars().all()
    check("index snapshot persisted to DB", len(snaps) > 0, f"rows={len(snaps)}")

    sched2 = IngestionScheduler()
    await sched2.start()
    await asyncio.sleep(4)
    # store is process-global; after resume the series must remain dup-free
    for uid, _ in WELLS:
        rec = store.get_recent(uid, ["ROP"]).get("ROP", [])
        idxs = [s.index for s in rec]
        check(f"{uid} dup-free after restart/resume", len(idxs) == len(set(idxs)), f"n={len(idxs)}")
    await sched2.stop()
    await client.aclose()

    print("\n==== INGEST INTEGRATION:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}", "====")
    return 1 if fails else 0


def WELLS_uids():
    return [u for u, _ in WELLS]


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
