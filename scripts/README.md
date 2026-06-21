# End-to-end test scripts

Live, full-stack checks that drive the running app over HTTP/WS. They
complement the fast, infrastructure-free unit suite (`cd backend && pytest`,
124 tests). The simplest way to run them is against the Docker stack
(`docker compose up`); they can also run against locally-started processes.

## `feature_test.py` — every feature, end-to-end

Exercises one feature per phase against a running API: discovery, ingestion +
WebSocket live push, parameter catalog, unit conversion, dashboard pages CRUD,
the write path, multi-well comparison (incl. the 4-well cap), the 8 drilling-
hydraulics formulas (Impact Force from a live mud-weight binding), Excel export,
JWT login + admin RBAC, and reporting (remarks keyword search, mud properties,
depth-of-interest).

Run the stack as local processes, then the test:

```bash
# 1) mock WITSML store on :8090
PYTHONPATH="backend:." backend/.venv/Scripts/python -m uvicorn mockstore.server:app --port 8090

# 2) feed simulator (3 growing wells) against the mock
WITSML_URL="http://127.0.0.1:8090/witsml/store" SIMULATED_WELL_COUNT=3 POLL_INTERVAL_SECONDS=2 \
  PYTHONPATH="backend:." backend/.venv/Scripts/python -m simulator.feed_simulator

# 3) API + ingestion scheduler, pointed at the mock
WITSML_URL="http://127.0.0.1:8090/witsml/store" POLL_INTERVAL_SECONDS=2 \
  DATABASE_URL="sqlite+aiosqlite:///./_feat.db" PYTHONPATH="backend" \
  backend/.venv/Scripts/python -m uvicorn app.main:app --port 8000

# 4) drive every feature
backend/.venv/Scripts/python scripts/feature_test.py
```

Expected: `==== FEATURE TEST: ALL PASS ====` (27 checks).

## `live_ingest_test.py` — ingestion correctness

Seeds two growing logs (one whose uid collides across wells), runs the real
`IngestionScheduler` against the mock, and asserts: both wells ingest, **zero
duplicate / zero gap** indices across polls, `objectGrowing` flips true, new
rows append on later ticks, and a restarted scheduler **resumes from the
Postgres index snapshot**. Needs the mock running on :8090 (step 1 above).

```bash
PYTHONPATH="backend:." backend/.venv/Scripts/python scripts/live_ingest_test.py
```

These caught two real bugs during development: tz naive/aware index comparison
(also a SQLite snapshot-resume break) and a scheduler header-key collision
(WITSML log uids are unique only within a wellbore).
