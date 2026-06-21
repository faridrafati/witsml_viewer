"""Phase 3.5 API tests: parameter catalog CRUD + multi-well comparison cap.

These run against the real ASGI app (``app.main:app``) via Starlette's
``TestClient`` used as a context manager so the FastAPI lifespan fires — that
lifespan creates the schema and seeds the parameter catalog into the local
sqlite dev DB. No network and no live WITSML store are required:

  * the parameter-catalog endpoints are pure DB CRUD, and
  * the comparison "more than 4 wells" guard rejects the request *before* any
    store query is attempted, so the cap test never touches the network.

The one place real wells *would* need the WITSML client, we stay lenient:
status in (200, 502) and — when 200 — a ``wells`` list in the body.

The comparison router is mounted defensively by the spine and may not yet be
wired in ``app.api.router`` while the phase is mid-build. To keep this suite
self-contained, the fixtures ensure it is included on the app under ``/api``
exactly once, regardless of wiring state.
"""

from __future__ import annotations

import uuid

import pytest
from starlette.testclient import TestClient

from app.main import app

# ── seeded catalog mnemonics we assert are present (subset of the full seed) ──
SEEDED_MNEMONICS = ["DEPTH", "ROP", "WOB", "TOTGAS", "RPM", "MW"]


def _comparison_is_mounted() -> bool:
    """True if a GET to /api/comparison/ resolves to a route (not a 404)."""
    with TestClient(app) as client:
        # No `wells` param -> the endpoint itself raises 422/400; a missing
        # route would instead yield 404 "Not Found".
        resp = client.get("/api/comparison/")
        return resp.status_code != 404


def _ensure_comparison_mounted() -> None:
    """Include the comparison router under /api if the spine hasn't yet."""
    if _comparison_is_mounted():
        return
    import app.api.comparison as comparison  # local import: optional during build

    app.include_router(comparison.router, prefix="/api")


@pytest.fixture(scope="module", autouse=True)
def _mount_comparison() -> None:
    _ensure_comparison_mounted()


@pytest.fixture()
def client() -> TestClient:
    """Lifespan-aware TestClient (context-managed so startup seeding runs)."""
    with TestClient(app) as c:
        yield c


# ── parameters API ───────────────────────────────────────────────────────
def test_list_parameters_returns_seeded_catalog(client: TestClient) -> None:
    resp = client.get("/api/parameters")
    assert resp.status_code == 200
    rows = resp.json()
    assert isinstance(rows, list) and rows

    mnemonics = {row["mnemonic"] for row in rows}
    for expected in SEEDED_MNEMONICS:
        assert expected in mnemonics, f"{expected} missing from seeded catalog"

    # Each row carries the documented shape.
    sample = next(r for r in rows if r["mnemonic"] == "DEPTH")
    assert set(sample) >= {"id", "mnemonic", "description", "default_unit", "wits_id"}
    assert sample["default_unit"] == "m"


def test_get_single_seeded_parameter(client: TestClient) -> None:
    resp = client.get("/api/parameters/ROP")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mnemonic"] == "ROP"
    assert body["default_unit"] == "m/h"


def test_get_missing_parameter_is_404(client: TestClient) -> None:
    resp = client.get(f"/api/parameters/NOPE_{uuid.uuid4().hex[:8]}")
    assert resp.status_code == 404


def test_create_then_get_then_delete_roundtrip(client: TestClient) -> None:
    # Throwaway mnemonic so we never collide with (or mutate) the seed.
    mnem = f"TST_{uuid.uuid4().hex[:8].upper()}"
    payload = {
        "mnemonic": mnem,
        "description": "phase 3.5 throwaway",
        "default_unit": "m",
        "wits_id": "9999",
    }

    # CREATE
    created = client.post("/api/parameters", json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["mnemonic"] == mnem
    assert body["default_unit"] == "m"
    assert isinstance(body["id"], int)

    # GET /{mnemonic}
    fetched = client.get(f"/api/parameters/{mnem}")
    assert fetched.status_code == 200
    assert fetched.json()["mnemonic"] == mnem

    # it now shows up in the list
    listed = client.get("/api/parameters")
    assert mnem in {r["mnemonic"] for r in listed.json()}

    # DELETE removes it (204)
    deleted = client.delete(f"/api/parameters/{mnem}")
    assert deleted.status_code == 204

    # gone afterwards
    after = client.get(f"/api/parameters/{mnem}")
    assert after.status_code == 404


def test_create_duplicate_mnemonic_conflicts(client: TestClient) -> None:
    # Re-creating a seeded mnemonic must be rejected as a conflict.
    resp = client.post(
        "/api/parameters",
        json={"mnemonic": "DEPTH", "description": "dup", "default_unit": "m"},
    )
    assert resp.status_code == 409


# ── comparison cap ───────────────────────────────────────────────────────
def test_comparison_rejects_more_than_four_wells(client: TestClient) -> None:
    # Guard fires before any store query, so this needs no live server.
    resp = client.get("/api/comparison/", params={"wells": "A,B,C,D,E"})
    assert resp.status_code == 400
    assert "4" in resp.json()["detail"]


def test_comparison_zero_wells_is_400(client: TestClient) -> None:
    resp = client.get("/api/comparison/", params={"wells": ""})
    assert resp.status_code == 400


# ── comparison shape (lenient — may touch the WITSML client) ──────────────
def test_comparison_single_well_shape_is_lenient() -> None:
    """A real well_uid may need the live store; stay lenient on transport.

    Per-well store/lithology failures degrade to empty (the endpoint is
    best-effort), so with no live store this returns 200 + an empty bundle;
    if the upstream client cannot be reached at all we tolerate a 502. When
    200, the documented per-well shape must hold.
    """
    with TestClient(app) as c:
        resp = c.get("/api/comparison/", params={"wells": "WELL-1"})
    assert resp.status_code in (200, 502)
    if resp.status_code == 200:
        body = resp.json()
        assert isinstance(body.get("wells"), list)
        for entry in body["wells"]:
            assert {"wellUid", "curves", "lithology"} <= set(entry)
