"""Parameter-catalog REST API.

CRUD over :class:`app.db.models.ParameterCatalog` — the mnemonic dictionary
with optional description, default unit, and WITS-ID cross-reference. The
mnemonic is the natural key for lookups/updates/deletes.

Mounted by the spine under ``/api`` (this router carries its own
``/parameters`` prefix), so the effective paths are ``/api/parameters`` etc.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.db.models import ParameterCatalog

router = APIRouter(prefix="/parameters", tags=["parameters"])


# ── schemas ──────────────────────────────────────────────────────────────
class ParameterOut(BaseModel):
    id: int
    mnemonic: str
    description: str | None = None
    default_unit: str | None = None
    wits_id: str | None = None

    model_config = {"from_attributes": True}


class ParameterCreate(BaseModel):
    mnemonic: str = Field(min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=300)
    default_unit: str | None = Field(default=None, max_length=40)
    wits_id: str | None = Field(default=None, max_length=10)


class ParameterUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=300)
    default_unit: str | None = Field(default=None, max_length=40)
    wits_id: str | None = Field(default=None, max_length=10)


# ── helpers ──────────────────────────────────────────────────────────────
async def _get_by_mnemonic(mnemonic: str, session: AsyncSession) -> ParameterCatalog:
    row = await session.scalar(
        select(ParameterCatalog).where(ParameterCatalog.mnemonic == mnemonic)
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="parameter not found")
    return row


# ── endpoints ────────────────────────────────────────────────────────────
@router.get("/", response_model=list[ParameterOut])
async def list_parameters(
    session: AsyncSession = Depends(get_session),
) -> list[ParameterCatalog]:
    """List all parameter-catalog rows ordered by mnemonic."""
    rows = await session.execute(select(ParameterCatalog).order_by(ParameterCatalog.mnemonic))
    return list(rows.scalars().all())


@router.get("/{mnemonic}", response_model=ParameterOut)
async def get_parameter(
    mnemonic: str,
    session: AsyncSession = Depends(get_session),
) -> ParameterCatalog:
    """Fetch a single parameter by mnemonic (404 if absent)."""
    return await _get_by_mnemonic(mnemonic, session)


@router.post("/", response_model=ParameterOut, status_code=status.HTTP_201_CREATED)
async def create_parameter(
    payload: ParameterCreate,
    session: AsyncSession = Depends(get_session),
) -> ParameterCatalog:
    """Create a parameter-catalog row (409 if the mnemonic already exists)."""
    existing = await session.scalar(
        select(ParameterCatalog).where(ParameterCatalog.mnemonic == payload.mnemonic)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="parameter with this mnemonic already exists",
        )

    row = ParameterCatalog(
        mnemonic=payload.mnemonic,
        description=payload.description,
        default_unit=payload.default_unit,
        wits_id=payload.wits_id,
    )
    session.add(row)
    try:
        await session.commit()
    except Exception as exc:  # integrity error (race on unique mnemonic), etc.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="parameter with this mnemonic already exists",
        ) from exc
    await session.refresh(row)
    return row


@router.put("/{mnemonic}", response_model=ParameterOut)
async def update_parameter(
    mnemonic: str,
    payload: ParameterUpdate,
    session: AsyncSession = Depends(get_session),
) -> ParameterCatalog:
    """Update an existing parameter's mutable fields (404 if absent)."""
    row = await _get_by_mnemonic(mnemonic, session)

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(row, field, value)

    await session.commit()
    await session.refresh(row)
    return row


@router.delete("/{mnemonic}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_parameter(
    mnemonic: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a parameter by mnemonic (404 if absent)."""
    row = await _get_by_mnemonic(mnemonic, session)
    await session.delete(row)
    await session.commit()
