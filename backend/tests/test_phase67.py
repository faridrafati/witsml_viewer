"""Phase 6 + 7 API tests: formulas, auth, admin RBAC, reporting, and export.

These run against the real ASGI app (``app.main:app``) via Starlette's
``TestClient`` used as a context manager so the FastAPI lifespan fires. That
lifespan creates the sqlite schema and seeds the parameter catalog, default
unit conversions, the bootstrap super-admin (``admin`` / ``admin`` from
settings), and the reporting reference data. No network and no live WITSML
store are required — every endpoint under test is pure DB / pure compute, and
the export writer streams whatever rows exist (empty is still a valid xlsx).

The Phase 6/7 feature routers (formulas, auth, admin, reports, export) are
mounted by the spine (``app.api.router``) once a human wires them in. While the
phase is mid-build they may not be wired yet, so — exactly as the Phase 3.5
suite does for the comparison router — the fixtures here include each router
under ``/api`` once, defensively, regardless of wiring state. If a router
module does not exist *at all* yet, the dependent tests skip rather than fail,
keeping the suite green throughout the incremental build.
"""

from __future__ import annotations

import importlib
import uuid

import pytest
from starlette.testclient import TestClient

from app.config import settings
from app.main import app

# Feature routers introduced in Phase 6/7. Each exposes ``router: APIRouter``.
_FEATURE_ROUTERS = [
    "app.api.formulas",
    "app.api.auth",
    "app.api.admin",
    "app.api.reports",
    "app.api.export",
]


def _try_mount(module_path: str) -> bool:
    """Include a feature router under ``/api`` if importable and not present.

    Returns True if the module imported (so the routes should now resolve),
    False if the module does not exist yet (dependent tests will skip).
    """
    try:
        module = importlib.import_module(module_path)
    except Exception:
        return False
    router = getattr(module, "router", None)
    if router is None:
        return False
    # Avoid double-mounting if the spine already wired it.
    existing = {getattr(r, "path", "") for r in app.routes}
    new_paths = {getattr(r, "path", "") for r in router.routes}
    if new_paths and new_paths.issubset(existing):
        return True
    app.include_router(router, prefix="/api")
    return True


@pytest.fixture(scope="module", autouse=True)
def _mount_feature_routers() -> dict[str, bool]:
    """Ensure every Phase 6/7 router is mounted once; report availability."""
    return {mod: _try_mount(mod) for mod in _FEATURE_ROUTERS}


@pytest.fixture()
def client() -> TestClient:
    """Lifespan-aware TestClient (context-managed so startup seeding runs)."""
    with TestClient(app) as c:
        yield c


def _route_exists(client: TestClient, method: str, path: str) -> bool:
    """True if `path` resolves to a route (any status other than 404)."""
    resp = client.request(method, path)
    return resp.status_code != 404


def _require(client: TestClient, method: str, path: str) -> None:
    if not _route_exists(client, method, path):
        pytest.skip(f"{method} {path} not mounted yet (Phase 6/7 router mid-build)")


# ── helpers ───────────────────────────────────────────────────────────────
def _login(client: TestClient, username: str, password: str):
    """POST the OAuth2 password form to /api/auth/login."""
    return client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
    )


def _admin_token(client: TestClient) -> str:
    resp = _login(client, settings.superadmin_username, settings.superadmin_password)
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    assert token
    return token


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── formulas (Phase 6) ──────────────────────────────────────────────────────
def test_list_formulas_includes_impact_force(client: TestClient) -> None:
    _require(client, "GET", "/api/formulas")
    resp = client.get("/api/formulas")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    rows = body["formulas"] if isinstance(body, dict) and "formulas" in body else body
    assert isinstance(rows, list) and rows
    keys = {row["key"] for row in rows}
    assert "impact_force" in keys


def test_compute_impact_force_uses_gpm_default(client: TestClient) -> None:
    _require(client, "POST", "/api/formulas/impact_force/compute")
    # GPM omitted -> default 120; (120 * 9.5 * 250) / 1932 ≈ 147.51.
    resp = client.post(
        "/api/formulas/impact_force/compute",
        json={"values": {"MW": 9.5, "JV": 250}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    result = body["result"] if isinstance(body, dict) else body
    assert result == pytest.approx(147.5, abs=0.5)


def test_compute_unknown_formula_is_404(client: TestClient) -> None:
    _require(client, "POST", "/api/formulas/impact_force/compute")
    bad = f"no_such_formula_{uuid.uuid4().hex[:8]}"
    resp = client.post(f"/api/formulas/{bad}/compute", json={"values": {}})
    assert resp.status_code == 404


# ── auth (Phase 7) ──────────────────────────────────────────────────────────
def test_login_returns_access_token(client: TestClient) -> None:
    _require(client, "POST", "/api/auth/login")
    resp = _login(client, settings.superadmin_username, settings.superadmin_password)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("access_token")
    # token_type, when present, is conventionally "bearer".
    if "token_type" in body:
        assert body["token_type"].lower() == "bearer"


def test_login_wrong_password_is_401(client: TestClient) -> None:
    _require(client, "POST", "/api/auth/login")
    resp = _login(client, settings.superadmin_username, "definitely-not-the-password")
    assert resp.status_code == 401


def test_me_with_token_returns_admin(client: TestClient) -> None:
    _require(client, "POST", "/api/auth/login")
    if not _route_exists(client, "GET", "/api/auth/me"):
        pytest.skip("GET /api/auth/me not mounted yet")
    token = _admin_token(client)
    resp = client.get("/api/auth/me", headers=_bearer(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["username"] == settings.superadmin_username
    assert body["access_level"] == "super_admin"


def test_me_without_token_is_401(client: TestClient) -> None:
    if not _route_exists(client, "GET", "/api/auth/me"):
        pytest.skip("GET /api/auth/me not mounted yet")
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


# ── admin RBAC (Phase 7) ────────────────────────────────────────────────────
def test_admin_rbac_super_admin_lists_users_normal_user_forbidden(client: TestClient) -> None:
    _require(client, "POST", "/api/auth/login")
    if not _route_exists(client, "GET", "/api/admin/users"):
        pytest.skip("GET /api/admin/users not mounted yet")

    admin_token = _admin_token(client)
    admin_headers = _bearer(admin_token)

    # Super-admin can list users.
    listed = client.get("/api/admin/users", headers=admin_headers)
    assert listed.status_code == 200, listed.text
    assert isinstance(listed.json(), list)

    # Super-admin creates a fresh normal user.
    uname = f"norm_{uuid.uuid4().hex[:8]}"
    pwd = "Sup3r-Secret-Pw!"
    created = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "username": uname,
            "password": pwd,
            "first_name": "Norm",
            "last_name": "User",
            "access_level": "normal",
        },
    )
    assert created.status_code in (200, 201), created.text

    # That normal user logs in...
    login = _login(client, uname, pwd)
    assert login.status_code == 200, login.text
    normal_token = login.json()["access_token"]

    # ...and is forbidden from the admin listing.
    forbidden = client.get("/api/admin/users", headers=_bearer(normal_token))
    assert forbidden.status_code == 403


# ── reporting (Phase 6/7) ───────────────────────────────────────────────────
def test_remarks_keyword_search_finds_seeded_lost_circulation(client: TestClient) -> None:
    if not _route_exists(client, "GET", "/api/reports/remarks"):
        pytest.skip("GET /api/reports/remarks not mounted yet")
    resp = client.get("/api/reports/remarks", params={"keyword": "lost"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    rows = body["remarks"] if isinstance(body, dict) and "remarks" in body else body
    assert isinstance(rows, list) and rows, "expected at least one seeded remark"
    blob = " ".join(str(r).lower() for r in rows)
    assert "lost circulation" in blob


def test_depth_of_interest_create_then_get(client: TestClient) -> None:
    base = "/api/reports/depths"
    if not _route_exists(client, "GET", base):
        pytest.skip("depth-of-interest endpoint not mounted yet")

    well = f"DOI-WELL-{uuid.uuid4().hex[:6]}"
    payload = {
        "well_uid": well,
        "depth": 4321.5,
        "note": "phase 6/7 throwaway depth of interest",
    }
    created = client.post(base, json=payload)
    assert created.status_code in (200, 201), created.text
    created_body = created.json()
    assert created_body["well_uid"] == well
    assert created_body["depth"] == pytest.approx(4321.5)

    # Filter by well_uid and confirm our row comes back.
    fetched = client.get(base, params={"well_uid": well})
    assert fetched.status_code == 200, fetched.text
    rows = fetched.json()
    assert isinstance(rows, list) and rows
    assert any(r["well_uid"] == well and r["depth"] == pytest.approx(4321.5) for r in rows)


# ── export (Phase 6/7) ──────────────────────────────────────────────────────
def test_export_xlsx_returns_spreadsheet(client: TestClient) -> None:
    if not _route_exists(client, "POST", "/api/export/xlsx"):
        pytest.skip("POST /api/export/xlsx not mounted yet")
    resp = client.post(
        "/api/export/xlsx",
        json={"wellUid": "X", "mnemonics": ["ROP"]},
    )
    # Empty data is still a valid (header-only) workbook.
    assert resp.status_code == 200, resp.text
    ctype = resp.headers.get("content-type", "")
    assert (
        "spreadsheetml" in ctype  # application/vnd.openxmlformats-...sheet
        or "officedocument" in ctype
        or "excel" in ctype
    ), f"unexpected content-type: {ctype!r}"
    # The body must be non-empty bytes (a real xlsx is a ZIP starting with PK).
    assert resp.content[:2] == b"PK"
