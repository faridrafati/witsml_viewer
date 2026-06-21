"""Dashboard 'dynamic pages' CRUD (brief §7.5).

A page is bound to a well and holds a component tree (Numeric / Chart / Strip)
plus UI and non-UI config. The component tree is stored as opaque JSON in
DashboardPage.layout — the frontend owns its shape; the backend persists,
lists, duplicates, and scopes it. Per-user page access (RBAC) is enforced in
Phase 7; for now pages are owner-tagged but readable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.db.models import DashboardPage

router = APIRouter(prefix="/pages", tags=["pages"])


# ── schemas ─────────────────────────────────────────────────────────────
class PageBase(BaseModel):
    name: str
    well_uid: str | None = None
    well_name: str | None = None
    region: str | None = None
    # Component tree: list of components, each {type: numeric|chart|strip,
    # mnemonics, root, back_config, comment_config, numerics_config,
    # chart_numeric_config, time_config, ...}. Shape owned by the frontend.
    layout: dict[str, Any] = Field(default_factory=dict)


class PageCreate(PageBase):
    owner_id: int | None = None


class PageUpdate(BaseModel):
    name: str | None = None
    well_uid: str | None = None
    well_name: str | None = None
    region: str | None = None
    layout: dict[str, Any] | None = None


class PageOut(PageBase):
    id: int
    owner_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── helpers ─────────────────────────────────────────────────────────────
async def _get_or_404(session: AsyncSession, page_id: int) -> DashboardPage:
    page = await session.get(DashboardPage, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail=f"page {page_id} not found")
    return page


# ── routes ──────────────────────────────────────────────────────────────
@router.get("", response_model=list[PageOut])
async def list_pages(
    owner_id: int | None = None,
    well_uid: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[DashboardPage]:
    stmt = select(DashboardPage)
    if owner_id is not None:
        stmt = stmt.where(DashboardPage.owner_id == owner_id)
    if well_uid is not None:
        stmt = stmt.where(DashboardPage.well_uid == well_uid)
    stmt = stmt.order_by(DashboardPage.id)
    return list((await session.execute(stmt)).scalars().all())


@router.post("", response_model=PageOut, status_code=201)
async def create_page(
    body: PageCreate, session: AsyncSession = Depends(get_session)
) -> DashboardPage:
    page = DashboardPage(
        name=body.name,
        owner_id=body.owner_id,
        well_uid=body.well_uid,
        well_name=body.well_name,
        region=body.region,
        layout=body.layout,
    )
    session.add(page)
    await session.commit()
    await session.refresh(page)
    return page


@router.get("/{page_id}", response_model=PageOut)
async def get_page(page_id: int, session: AsyncSession = Depends(get_session)) -> DashboardPage:
    return await _get_or_404(session, page_id)


@router.put("/{page_id}", response_model=PageOut)
async def update_page(
    page_id: int, body: PageUpdate, session: AsyncSession = Depends(get_session)
) -> DashboardPage:
    page = await _get_or_404(session, page_id)
    data = body.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(page, field, value)
    await session.commit()
    await session.refresh(page)
    return page


@router.delete("/{page_id}", status_code=204)
async def delete_page(page_id: int, session: AsyncSession = Depends(get_session)) -> None:
    page = await _get_or_404(session, page_id)
    await session.delete(page)
    await session.commit()


@router.post("/{page_id}/duplicate", response_model=PageOut, status_code=201)
async def duplicate_page(
    page_id: int,
    name: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> DashboardPage:
    src = await _get_or_404(session, page_id)
    copy = DashboardPage(
        name=name or f"{src.name} (copy)",
        owner_id=src.owner_id,
        well_uid=src.well_uid,
        well_name=src.well_name,
        region=src.region,
        layout=dict(src.layout or {}),
    )
    session.add(copy)
    await session.commit()
    await session.refresh(copy)
    return copy
