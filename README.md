# WITSML Mudlogging Monitor

A real-time mudlogging **monitoring & data-management Backend-for-Frontend (BFF)** for
WITSML **1.4.1.1** servers. It connects to a WITSML Store over SOAP, continuously
ingests growing mudlogging objects (logs, mudlogs, trajectories) by **polling** — WITSML
1.x has no push/streaming, so freshness comes from a coordinated short-interval poll loop
— normalizes the data (units, null sentinels, index direction) and serves a clean REST +
WebSocket API to a React frontend. The goal is to make a notoriously fiddly oilfield
protocol behave like a tidy, live, well-by-well data feed.

---

## Quickstart

```bash
cp .env.example .env          # single source of truth for all settings
docker compose up             # build + start the full stack
```

`docker compose up` brings up six services:

| Service     | What it is                                                        | URL / Port                       |
|-------------|-------------------------------------------------------------------|----------------------------------|
| `postgres`  | Postgres 16 — durable history                                     | `localhost:5432`                 |
| `redis`     | Redis 7 — warm ring buffer + WebSocket pub/sub                    | `localhost:6379`                 |
| `drillflow` | Drillflow WITSML 1.4.1.1 test server (SOAP Store)                 | `localhost:7070/Witsml/Store`    |
| `api`       | FastAPI BFF                                                       | `localhost:8000`                 |
| `simulator` | Perpetual test rig: creates 20 wells, appends a row to each log @5s | (no port)                      |
| `web`       | React / Vite frontend                                             | `localhost:5173`                 |

Key URLs once up:

- API docs (Swagger): http://localhost:8000/docs
- Health probe: http://localhost:8000/health
- Frontend: http://localhost:5173

### Running the backend tests

```bash
cd backend
pip install -e ".[dev]"
pytest
```

---

## Architecture

This is a **Backend-for-Frontend**: the browser never talks WITSML/SOAP. The backend
absorbs all protocol complexity and exposes a narrow, frontend-shaped REST + WebSocket API.

**Data flow:**

```
WITSML Store (SOAP)
      │  GetFromStore (QBE)
      ▼
SOAP gateway  (app/witsml/client.py — zeep)
      │
      ▼
Ingestion loop  (~5 s coordinated poll tick, staggered across wells)
      │
      ▼
Normalize  →  units · null sentinels · index direction · UTC timestamps
      │
      ├──► Index cache  (last-seen continuation index per growing object)
      ├──► Postgres     (durable history)
      └──► Redis ring buffer  (last ~6 h warm cache)
                 │
                 ▼
           WebSocket hub  ──►  React / Vite UI
```

**"Ingest 20, view 1" hybrid strategy.** The ingestion engine continuously polls **all**
wells (20 in the simulated stack) so history and alarms stay complete, but the UI subscribes
to **one** well at a time for a dense live view. Background wells are kept fresh and summarized;
the focused well streams full-resolution curve data over the WebSocket. This keeps the WITSML
server load bounded (concurrency + stagger) while the user gets a real-time experience.

---

## Repository layout

```
WITSML viewer/
├── README.md
├── docker-compose.yml            # full testable stack (6 services)
├── .env.example                  # env template → cp to .env
├── backend/
│   ├── pyproject.toml            # deps + dev tooling (pytest, ruff, black, mypy)
│   ├── Dockerfile
│   └── app/
│       ├── main.py               # FastAPI app: health + /api, lifespan wiring
│       ├── config.py             # pydantic-settings (single source of truth)
│       ├── api/
│       │   ├── router.py         # /api router, includes discovery
│       │   ├── health.py         # /health
│       │   └── discovery.py      # wells / wellbores / logs (READ)
│       ├── witsml/               # protocol layer
│       │   ├── client.py         # SOAP gateway (zeep) — WitsmlClient
│       │   ├── constants.py      # NS, ReturnElements, OptionsIn, return codes
│       │   ├── queries.py        # QBE builders (well/wellbore/log/mudlog/getCap)
│       │   ├── parse.py          # lxml parsers → domain models; merge_sparse_rows
│       │   └── polling.py        # continuation/dedupe/merge/beyond helpers
│       ├── domain/models.py      # Well, Wellbore, LogHeader, LogDataBlock, MudLog …
│       ├── auth/security.py      # password hash, JWT, Fernet encrypt/decrypt
│       ├── db/                   # SQLAlchemy base, init_models, seed
│       ├── ingestion/            # poll scheduler (Phase 2)
│       └── ws/                   # WebSocket hub (Phase 2)
├── simulator/                    # 20-well perpetual feed (Dockerfile + driver)
└── frontend/                     # React / Vite app
```

---

## WITSML protocol rules implemented

WITSML 1.4.1.1 is full of sharp edges. The protocol layer (`app/witsml/`) encodes them
explicitly so the rest of the app never has to think about them:

- **Inclusive-boundary dedupe.** WITSML index ranges are *inclusive* on both ends, so the
  first row of each new poll repeats the last row of the previous poll. `polling.dedupe_boundary`
  / `merge_blocks` drop the duplicate boundary sample so the merged series has **no dupes and no gaps**.
- **"+2" truncation loop.** A server may return a partial result (`RC_PARTIAL_SUCCESS` / truncated).
  We detect truncation, advance the start index just past the last returned node, and re-query until
  the server reports completion — never assuming one response is the whole range.
- **One growing object per data-only query.** A `returnElements="data-only"` log query must target
  exactly one growing object (one log); queries are built per-object accordingly.
- **GetCap with `dataVersion=1.4.1.1`.** `WMLS_GetCap` OptionsIn must carry `dataVersion=1.4.1.1`,
  otherwise capability negotiation is undefined.
- **Never infer units from the mnemonic.** Units come **only** from the server's `<logCurveInfo>/unit`
  (or `uom` attributes), never guessed from a mnemonic name like `ROP` or `DEPT`.
- **Null sentinels.** Each log declares its own `nullValue` (commonly `-999.25`); those sentinels are
  converted to real nulls during normalization, not treated as data.
- **Index direction.** Logs may be `increasing` or `decreasing`; continuation logic and range
  comparisons respect the declared `Direction`/`IndexType` rather than assuming ascending depth/time.
- **UTC.** Time-indexed data is normalized to UTC end-to-end.
- **Lag-depth caveat.** Mudlog gas/lithology samples are recorded at *lag depth* (sample return depth),
  not bit depth; the depth axis is treated as reported and **not** silently re-aligned to bit depth.

---

## How we validated correctness

- **Protocol-layer smoke tests.** `GetVersion` (connectivity — must contain `1.4.1.1`) and `GetCap`
  confirm the SOAP gateway and capability negotiation against the live Drillflow server.
- **pytest suite.** Unit tests over `queries` (QBE shape / OptionsIn), `parse` (XML → domain models,
  sparse-row merge, null handling) and `polling`, with explicit **no-duplicates / no-gaps** assertions
  across simulated multi-poll sequences.
- **Cross-validation against reference clients.** Output is checked against
  [Equinor WITSML Explorer](https://github.com/equinor/witsml-explorer) and
  **PDS WITSML Studio Desktop**, pointed at the **same Drillflow server**, to confirm we read the same
  wells, curves, units and values a known-good client does.

---

## Build status

- **Phase 0 — Scaffold / bootable.** ✅ Done. Full compose stack, config, domain models, security
  primitives, health probe, CI tooling — `docker compose up` boots end-to-end.
- **Phase 1 — WITSML client + discovery (READ).** ✅ Done. SOAP `WitsmlClient`, QBE query builders,
  lxml parsers, polling helpers, and read-only discovery endpoints (wells / wellbores / log headers / data).

**Planned (2–7):**

- **Phase 2 — Live ingestion & WebSocket.** 5 s poll scheduler, ring buffer, normalize pipeline, WS hub.
- **Phase 3 — Persistence & history.** Postgres history store, backfill, time/depth range queries.
- **Phase 4 — Mudlog & geology.** Lithology / geology intervals, gas, lag-depth handling, mudlog views.
- **Phase 5 — Auth & multi-tenant connections.** User/role auth, per-connection encrypted credentials.
- **Phase 6 — Write-back (Add/Update/Delete).** Data management against the Store with conformance guards.
- **Phase 7 — Export & reporting.** Excel (openpyxl) and PDF (reportlab) exports, scheduled reports.

---

## Alternative production path (.NET)

For teams already invested in .NET, the most **spec-complete** path is a **.NET 8** backend built on
**PDS WITSMLstudio** with the **Energistics.DataAccess** object model — the same foundation Equinor's
WITSML Explorer uses. It provides battle-tested, fully-typed WITSML 1.3.1.1 / 1.4.1.1 / 2.0 data
objects and Store client behavior. This repository deliberately takes the **Python/FastAPI** route for a
lighter, async, BFF-shaped service; the .NET option is noted as the recommended choice when maximum
conformance and an existing .NET stack matter more than runtime homogeneity. It is **not built here**.

---

## Security

WITSML server credentials are **Fernet-encrypted at rest** using `CREDENTIAL_ENCRYPTION_KEY`
(`app/auth/security.py`: `encrypt_secret` / `decrypt_secret`) and are **never sent to the browser** —
the BFF holds them server-side and the frontend only ever sees normalized data. Generate a key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

User sessions use JWT (`SECRET_KEY`, `JWT_ALG`, `JWT_EXPIRE_MINUTES`); passwords are hashed with bcrypt.
```
