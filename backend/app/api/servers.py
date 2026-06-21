"""Phase 7 WITSML server-connection CRUD (brief §7.12).

Admins manage the catalog of WITSML store endpoints. Passwords are stored
Fernet-encrypted (security.encrypt_secret) and NEVER returned to the client —
responses redact the credential entirely. A `/test` endpoint constructs a
live WitsmlClient with the decrypted password and probes WMLS_GetVersion.

A human wires this router into app/api/router.py separately.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_admin
from app.auth.security import decrypt_secret, encrypt_secret
from app.db.base import get_session
from app.db.models import ServerConnection, User
from app.witsml.client import WitsmlClient

# WitsmlError lives beside the SOAP client; import defensively so this module
# stays import-clean even if the symbol is renamed/absent.
try:  # pragma: no cover - trivial import guard
    from app.witsml.client import WitsmlError  # type: ignore
except Exception:  # pragma: no cover

    class WitsmlError(Exception):  # type: ignore
        """Fallback transport error type."""


log = logging.getLogger(__name__)
router = APIRouter(prefix="/servers", tags=["servers"])


# ── schemas ─────────────────────────────────────────────────────────────
class ServerBase(BaseModel):
    name: str
    url: str
    username: str
    verify_ssl: bool = True
    version: str | None = None


class ServerCreate(ServerBase):
    password: str


class ServerUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    username: str | None = None
    # Only re-encrypts when provided; omit to keep the stored credential.
    password: str | None = None
    verify_ssl: bool | None = None
    version: str | None = None


class ServerOut(ServerBase):
    """Server view with the password redacted — credential is never echoed."""

    id: int
    cap_json: dict[str, Any] | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── helpers ─────────────────────────────────────────────────────────────
async def _get_or_404(session: AsyncSession, server_id: int) -> ServerConnection:
    server = await session.get(ServerConnection, server_id)
    if server is None:
        raise HTTPException(status_code=404, detail=f"server {server_id} not found")
    return server


# ── CRUD ────────────────────────────────────────────────────────────────
@router.get("", response_model=list[ServerOut])
async def list_servers(
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[ServerConnection]:
    stmt = select(ServerConnection).order_by(ServerConnection.id)
    return list((await session.execute(stmt)).scalars().all())


@router.post("", response_model=ServerOut, status_code=201)
async def create_server(
    body: ServerCreate,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ServerConnection:
    existing = (
        await session.execute(select(ServerConnection).where(ServerConnection.name == body.name))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="server name already exists")
    server = ServerConnection(
        name=body.name,
        url=body.url,
        username=body.username,
        password_encrypted=encrypt_secret(body.password),
        verify_ssl=body.verify_ssl,
        version=body.version,
    )
    session.add(server)
    await session.commit()
    await session.refresh(server)
    return server


@router.get("/{server_id}", response_model=ServerOut)
async def get_server(
    server_id: int,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ServerConnection:
    return await _get_or_404(session, server_id)


@router.put("/{server_id}", response_model=ServerOut)
async def update_server(
    server_id: int,
    body: ServerUpdate,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ServerConnection:
    server = await _get_or_404(session, server_id)
    data = body.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    if password:
        server.password_encrypted = encrypt_secret(password)
    for field, value in data.items():
        setattr(server, field, value)
    await session.commit()
    await session.refresh(server)
    return server


@router.delete("/{server_id}", status_code=204)
async def delete_server(
    server_id: int,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    server = await _get_or_404(session, server_id)
    await session.delete(server)
    await session.commit()


# ── connectivity probe ──────────────────────────────────────────────────
@router.post("/{server_id}/test")
async def test_server(
    server_id: int,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Construct a live client and probe WMLS_GetVersion. 502 on failure."""
    server = await _get_or_404(session, server_id)
    client = WitsmlClient(
        url=server.url,
        username=server.username,
        password=decrypt_secret(server.password_encrypted),
        verify_ssl=server.verify_ssl,
    )
    try:
        version = await client.get_version()
    except WitsmlError as exc:
        log.warning("WITSML error testing server %s: %s", server_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"WITSML store error: {exc}",
        ) from exc
    except Exception as exc:  # transport/SOAP/parse failures — never echo creds
        log.warning("transport error testing server %s: %s", server_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to reach WITSML store.",
        ) from exc
    return {"version": version}
