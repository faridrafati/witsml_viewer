"""Unit-definition REST API (brief §7.6).

CRUD over :class:`app.db.models.UnitDef` plus a stateless ``/convert`` endpoint
that runs an expression through the SAFE :mod:`app.units.engine`. Stored
expressions are validated on create so an invalid/unsafe formula can never be
persisted.

Mounted by the spine under ``/api`` (this router carries its own ``/units``
prefix), so the effective paths are ``/api/units`` etc.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.db.models import UnitDef
from app.units.engine import UnitFormulaError, convert, validate

router = APIRouter(prefix="/units", tags=["units"])


# ── schemas ──────────────────────────────────────────────────────────────
class UnitDefOut(BaseModel):
    id: int
    name: str
    from_unit: str
    to_unit: str
    expression: str
    is_builtin: bool

    model_config = {"from_attributes": True}


class UnitDefCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    from_unit: str = Field(min_length=1, max_length=40)
    to_unit: str = Field(min_length=1, max_length=40)
    expression: str = Field(min_length=1, max_length=500)
    is_builtin: bool = False


class ConvertIn(BaseModel):
    value: float
    expression: str = Field(min_length=1, max_length=500)


class ConvertOut(BaseModel):
    result: float


# ── endpoints ────────────────────────────────────────────────────────────
@router.get("/", response_model=list[UnitDefOut])
async def list_units(session: AsyncSession = Depends(get_session)) -> list[UnitDef]:
    """List all stored unit definitions."""
    rows = await session.execute(select(UnitDef).order_by(UnitDef.id))
    return list(rows.scalars().all())


@router.post("/", response_model=UnitDefOut, status_code=status.HTTP_201_CREATED)
async def create_unit(
    payload: UnitDefCreate,
    session: AsyncSession = Depends(get_session),
) -> UnitDef:
    """Create a unit definition after validating its expression.

    A 400 is returned if the formula is unsafe or malformed (it is never
    persisted in that case).
    """
    ok, reason = validate(payload.expression)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid expression: {reason}",
        )

    row = UnitDef(
        name=payload.name,
        from_unit=payload.from_unit,
        to_unit=payload.to_unit,
        expression=payload.expression,
        is_builtin=payload.is_builtin,
    )
    session.add(row)
    try:
        await session.commit()
    except Exception as exc:  # integrity error (duplicate from/to pair), etc.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="unit definition already exists or violates a constraint",
        ) from exc
    await session.refresh(row)
    return row


@router.delete("/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_unit(
    unit_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a unit definition by id (404 if absent)."""
    row = await session.get(UnitDef, unit_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unit definition not found"
        )
    await session.delete(row)
    await session.commit()


@router.post("/convert", response_model=ConvertOut)
async def convert_value(payload: ConvertIn) -> ConvertOut:
    """Evaluate ``expression`` with ``__value__`` bound to ``value``.

    Stateless and DB-free. Returns 400 for any unsafe/invalid/failed formula.
    """
    try:
        result = convert(payload.value, payload.expression)
    except UnitFormulaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ConvertOut(result=result)
