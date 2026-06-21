"""Comprehensive live feature test — drives the whole stack over HTTP/WS.

Assumes (started separately): the mock WITSML store, the feed simulator, and
the API (uvicorn) all running and pointed at the same mock. Exercises every
phase's features end-to-end and prints PASS/FAIL per feature.
"""

import asyncio
import json
import sys
import time

import httpx

_RUN = int(time.time())

API = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000/ws"
fails: list[str] = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + str(detail)) if detail else ''}")
    if not ok:
        fails.append(name)


async def wait_for_api(client):
    for _ in range(60):
        try:
            r = await client.get(f"{API}/health", timeout=3)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


async def wait_for_ingest(client, min_wells=1, min_samples=1):
    """Poll until the scheduler has ingested data from the simulator."""
    for _ in range(40):
        try:
            r = await client.get(f"{API}/api/ingest/wells", timeout=5)
            wells = r.json() if r.status_code == 200 else []
            warm = [w for w in wells if w.get("sample_count", 0) >= min_samples]
            if len(warm) >= min_wells:
                return warm
        except Exception:
            pass
        await asyncio.sleep(2)
    return []


async def main():
    async with httpx.AsyncClient() as c:
        check("API reachable (/health)", await wait_for_api(c))

        # ── Phase 1: discovery ──
        r = await c.get(f"{API}/api/version")
        check("GET /api/version -> 1.4.1.1", r.status_code == 200 and "1.4.1.1" in str(r.json()), r.text[:80])
        r = await c.get(f"{API}/api/cap")
        check("GET /api/cap", r.status_code == 200 and "version" in r.json())
        r = await c.get(f"{API}/api/wells")
        wells = r.json() if r.status_code == 200 else []
        check("GET /api/wells (discovery)", r.status_code == 200 and len(wells) >= 1, f"{len(wells)} wells")
        r = await c.get(f"{API}/api/tree")
        check("GET /api/tree (nested wellbores)", r.status_code == 200 and len(r.json()) >= 1)

        # ── Phase 2: ingestion + curves ──
        warm = await wait_for_ingest(c, min_wells=1, min_samples=2)
        check("Ingestion: wells warm with samples", len(warm) >= 1, f"{len(warm)} warm wells")
        # Prefer an ACTIVELY-growing simulator well (sim-well-*, most samples) so
        # the live-WS/curves checks see fresh deltas, not a stale leftover well.
        live = sorted(
            [w for w in warm if str(w.get("well_uid", "")).startswith("sim-well")],
            key=lambda w: w.get("sample_count", 0),
            reverse=True,
        )
        sel = live or sorted(warm, key=lambda w: w.get("sample_count", 0), reverse=True)
        well_uid = sel[0]["well_uid"] if sel else (wells[0]["uid"] if wells else None)
        print(f"   (selected live well: {well_uid})")
        if well_uid:
            r = await c.get(f"{API}/api/ingest/wells/{well_uid}/curves", params={"limit": 50})
            curves = r.json().get("curves", {}) if r.status_code == 200 else {}
            total = sum(len(v) for v in curves.values())
            check("GET /ingest/.../curves has data", r.status_code == 200 and total > 0, f"{len(curves)} curves, {total} pts")
            r = await c.get(f"{API}/api/ingest/wells/{well_uid}/latest")
            check("GET /ingest/.../latest", r.status_code == 200)

        # ── Phase 2: WebSocket live push ──
        if well_uid:
            try:
                import websockets
                async with websockets.connect(WS) as ws:
                    await ws.send(json.dumps({"type": "subscribe", "wellUid": well_uid}))
                    got_snapshot = got_data = False
                    for _ in range(8):
                        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
                        if msg.get("type") == "snapshot":
                            got_snapshot = True
                        if msg.get("type") == "data":
                            got_data = True
                        if got_snapshot and got_data:
                            break
                    check("WebSocket snapshot + live data", got_snapshot and got_data, f"snap={got_snapshot} data={got_data}")
            except Exception as exc:
                check("WebSocket snapshot + live data", False, repr(exc))

        # ── Phase 3: parameters + units + pages ──
        r = await c.get(f"{API}/api/parameters/")
        params = r.json() if r.status_code == 200 else []
        check("GET /api/parameters (catalog)", r.status_code == 200 and any(p["mnemonic"] == "ROP" for p in params), f"{len(params)} params")
        r = await c.post(f"{API}/api/units/convert", json={"value": 1.0, "expression": "__value__ * 62.4"})
        check("POST /api/units/convert (sg->pcf)", r.status_code == 200 and abs(r.json().get("result", 0) - 62.4) < 0.01, r.text[:80])
        # pages CRUD
        r = await c.post(f"{API}/api/pages", json={"name": "Feature Test Page", "well_uid": well_uid, "layout": {"components": []}})
        page = r.json() if r.status_code in (200, 201) else {}
        pid = page.get("id")
        check("POST /api/pages (create)", bool(pid), r.text[:80])
        if pid:
            r = await c.post(f"{API}/api/pages/{pid}/duplicate")
            dup = r.json() if r.status_code in (200, 201) else {}
            check("POST /api/pages/{id}/duplicate", bool(dup.get("id")))
            r = await c.put(f"{API}/api/pages/{pid}", json={"name": "Renamed"})
            check("PUT /api/pages/{id}", r.status_code == 200 and r.json().get("name") == "Renamed")
            await c.delete(f"{API}/api/pages/{pid}")
            if dup.get("id"):
                await c.delete(f"{API}/api/pages/{dup['id']}")

        # ── Phase 4: write path ──
        r = await c.post(f"{API}/api/store/well", json={"uid": f"FEAT-W-{_RUN}", "name": "Feature Write Well"})
        check("POST /api/store/well (write path)", r.status_code in (200, 201) and r.json().get("returnCode", 0) == 1, r.text[:100])

        # ── Phase 5: comparison ──
        if len(warm) >= 1:
            uids = ",".join(w["well_uid"] for w in warm[:3])
            r = await c.get(f"{API}/api/comparison/", params={"wells": uids, "mnemonics": "ROP,WOB"})
            check("GET /api/comparison (<=4 wells)", r.status_code == 200 and "wells" in r.json(), f"{len(r.json().get('wells', []))} wells")
        r = await c.get(f"{API}/api/comparison/", params={"wells": "A,B,C,D,E"})
        check("Comparison rejects >4 wells (400)", r.status_code == 400)

        # ── Phase 6: formulas + export ──
        r = await c.get(f"{API}/api/formulas/")
        check("GET /api/formulas (8 formulas)", r.status_code == 200 and len(r.json()) == 8, f"{len(r.json())} formulas")
        r = await c.post(f"{API}/api/formulas/impact_force/compute", json={"values": {"MW": 9.5, "JV": 250}})
        check("POST impact_force/compute ~147.5", r.status_code == 200 and abs(r.json().get("result", 0) - 147.5) < 0.5, r.text[:120])
        if well_uid:
            r = await c.post(f"{API}/api/export/xlsx", json={"wellUid": well_uid, "mnemonics": ["ROP", "WOB"]})
            ok = r.status_code == 200 and r.content[:2] == b"PK"
            check("POST /api/export/xlsx (xlsx bytes)", ok, f"status={r.status_code} {len(r.content)}B")

        # ── Phase 7: auth + RBAC ──
        r = await c.post(f"{API}/api/auth/login", data={"username": "admin", "password": "admin"})
        token = r.json().get("access_token") if r.status_code == 200 else None
        check("POST /api/auth/login (admin)", bool(token))
        H = {"Authorization": f"Bearer {token}"} if token else {}
        r = await c.get(f"{API}/api/auth/me", headers=H)
        check("GET /api/auth/me (bearer)", r.status_code == 200 and r.json().get("access_level") == "super_admin", r.text[:80])
        r = await c.get(f"{API}/api/auth/me")
        check("GET /api/auth/me without token -> 401", r.status_code == 401)
        r = await c.get(f"{API}/api/admin/users", headers=H)
        check("GET /api/admin/users (super-admin)", r.status_code == 200)

        # ── Phase 7: reporting ──
        r = await c.get(f"{API}/api/reports/remarks", params={"keyword": "lost"})
        rows = r.json() if r.status_code == 200 else []
        check("GET /api/reports/remarks?keyword=lost", r.status_code == 200 and len(rows) >= 1, f"{len(rows)} remarks")
        r = await c.get(f"{API}/api/reports/mud-properties", params={"well_uid": "any"})
        check("GET /api/reports/mud-properties", r.status_code in (200, 400))
        r = await c.post(f"{API}/api/reports/depths", json={"well_uid": well_uid or "X", "depth": 1234.5, "note": "feature test"})
        check("POST /api/reports/depths (depth-of-interest)", r.status_code in (200, 201))

    print("\n==== FEATURE TEST:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}", "====")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
