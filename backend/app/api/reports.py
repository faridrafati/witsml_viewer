"""P7 reporting REST API (brief §7.11).

Covers the reporting surface end-to-end for the pieces marked FULLY in the
brief, with light scaffolds for the remaining sub-modules:

  * ``GET /reports``               filtered report headers
  * ``GET /reports/remarks``       keyword search over remarks (+ context)
  * ``GET /reports/remarks/export``  the same search, as an .xlsx download
  * ``GET /reports/mud-properties``  drilling-fluid spec rows by report/well
  * ``/reports/searches`` …        saved-search CRUD + run
  * ``/reports/depths`` …          depth-of-interest CRUD
  * ``/reports/{mud-stock,well-path,time-analysis,tools}``  scaffolds

Search is deliberately permissive: a case-insensitive substring match over a
remark's ``text`` and ``category``, narrowed by the report header filters. The
``/searches/{id}/run`` endpoint replays a saved ``criteria`` blob through the
same remark-search code path so saved and ad-hoc searches stay consistent.
"""

from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.db.models import (
    DepthOfInterest,
    MudProperty,
    Remark,
    Report,
    SavedSearch,
)

router = APIRouter(prefix="/reports", tags=["reports"])

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ── schemas ─────────────────────────────────────────────────────────────
class ReportOut(BaseModel):
    id: int
    report_date: date | None = None
    field: str | None = None
    rig: str | None = None
    well_uid: str | None = None
    hole_size: str | None = None
    operation_type: str | None = None
    mud_system: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class RemarkContext(BaseModel):
    """A matching remark plus its enclosing report's header fields."""

    id: int
    report_id: int
    time: datetime | None = None
    depth: float | None = None
    category: str | None = None
    text: str | None = None
    report_date: date | None = None
    field: str | None = None
    rig: str | None = None
    well_uid: str | None = None
    operation_type: str | None = None
    mud_system: str | None = None


class MudPropertyOut(BaseModel):
    id: int
    report_id: int
    name: str
    value: str | None = None
    unit: str | None = None

    model_config = {"from_attributes": True}


class SavedSearchCreate(BaseModel):
    name: str
    module: str
    criteria: dict[str, Any] = Field(default_factory=dict)
    owner_id: int | None = None


class SavedSearchOut(BaseModel):
    id: int
    name: str
    owner_id: int | None = None
    module: str
    criteria: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class DepthCreate(BaseModel):
    well_uid: str
    depth: float
    note: str | None = None
    report_id: int | None = None


class DepthOut(BaseModel):
    id: int
    well_uid: str
    report_id: int | None = None
    depth: float
    note: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── helpers ─────────────────────────────────────────────────────────────
def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid date: {raw!r}") from exc


def _report_filters(
    stmt,
    *,
    field: str | None = None,
    rig: str | None = None,
    well_uid: str | None = None,
    operation_type: str | None = None,
    mud_system: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    """Apply the shared report-header filters to a Report-bearing select()."""
    if field:
        stmt = stmt.where(Report.field == field)
    if rig:
        stmt = stmt.where(Report.rig == rig)
    if well_uid:
        stmt = stmt.where(Report.well_uid == well_uid)
    if operation_type:
        stmt = stmt.where(Report.operation_type == operation_type)
    if mud_system:
        stmt = stmt.where(Report.mud_system == mud_system)
    if date_from:
        stmt = stmt.where(Report.report_date >= date_from)
    if date_to:
        stmt = stmt.where(Report.report_date <= date_to)
    return stmt


async def _search_remarks(
    session: AsyncSession,
    *,
    keyword: str | None = None,
    field: str | None = None,
    well_uid: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[RemarkContext]:
    """Case-insensitive substring search over remark text/category + filters."""
    stmt = select(Remark, Report).join(Report, Remark.report_id == Report.id)
    stmt = _report_filters(
        stmt, field=field, well_uid=well_uid, date_from=date_from, date_to=date_to
    )
    if keyword:
        like = f"%{keyword.lower()}%"
        from sqlalchemy import func

        stmt = stmt.where(
            or_(
                func.lower(Remark.text).like(like),
                func.lower(Remark.category).like(like),
            )
        )
    stmt = stmt.order_by(Report.report_date, Remark.id)
    rows = (await session.execute(stmt)).all()
    out: list[RemarkContext] = []
    for remark, report in rows:
        out.append(
            RemarkContext(
                id=remark.id,
                report_id=remark.report_id,
                time=remark.time,
                depth=remark.depth,
                category=remark.category,
                text=remark.text,
                report_date=report.report_date,
                field=report.field,
                rig=report.rig,
                well_uid=report.well_uid,
                operation_type=report.operation_type,
                mud_system=report.mud_system,
            )
        )
    return out


# ── reports ─────────────────────────────────────────────────────────────
@router.get("", response_model=list[ReportOut])
async def list_reports(
    field: str | None = None,
    rig: str | None = None,
    well_uid: str | None = None,
    operation_type: str | None = None,
    mud_system: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[Report]:
    stmt = _report_filters(
        select(Report),
        field=field,
        rig=rig,
        well_uid=well_uid,
        operation_type=operation_type,
        mud_system=mud_system,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
    ).order_by(Report.report_date, Report.id)
    return list((await session.execute(stmt)).scalars().all())


# ── remarks & summary ───────────────────────────────────────────────────
@router.get("/remarks", response_model=list[RemarkContext])
async def search_remarks(
    keyword: str | None = None,
    field: str | None = None,
    well_uid: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[RemarkContext]:
    return await _search_remarks(
        session,
        keyword=keyword,
        field=field,
        well_uid=well_uid,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
    )


@router.get("/remarks/export")
async def export_remarks(
    keyword: str | None = None,
    field: str | None = None,
    well_uid: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Stream the remark-search results as an .xlsx workbook."""
    from openpyxl import Workbook

    results = await _search_remarks(
        session,
        keyword=keyword,
        field=field,
        well_uid=well_uid,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Remarks"
    headers = [
        "Report Date",
        "Field",
        "Rig",
        "Well UID",
        "Operation",
        "Mud System",
        "Time",
        "Depth",
        "Category",
        "Remark",
    ]
    ws.append(headers)
    for r in results:
        ws.append(
            [
                r.report_date.isoformat() if r.report_date else None,
                r.field,
                r.rig,
                r.well_uid,
                r.operation_type,
                r.mud_system,
                r.time.isoformat() if r.time else None,
                r.depth,
                r.category,
                r.text,
            ]
        )

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="remarks.xlsx"'},
    )


# ── mud properties ──────────────────────────────────────────────────────
@router.get("/mud-properties", response_model=list[MudPropertyOut])
async def list_mud_properties(
    report_id: int | None = None,
    well_uid: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[MudProperty]:
    if report_id is None and well_uid is None:
        raise HTTPException(status_code=400, detail="report_id or well_uid is required")
    stmt = select(MudProperty)
    if report_id is not None:
        stmt = stmt.where(MudProperty.report_id == report_id)
    if well_uid is not None:
        stmt = stmt.join(Report, MudProperty.report_id == Report.id).where(
            Report.well_uid == well_uid
        )
    stmt = stmt.order_by(MudProperty.report_id, MudProperty.id)
    return list((await session.execute(stmt)).scalars().all())


# ── saved searches ──────────────────────────────────────────────────────
@router.get("/searches", response_model=list[SavedSearchOut])
async def list_searches(
    module: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[SavedSearch]:
    stmt = select(SavedSearch)
    if module is not None:
        stmt = stmt.where(SavedSearch.module == module)
    stmt = stmt.order_by(SavedSearch.id)
    return list((await session.execute(stmt)).scalars().all())


@router.post("/searches", response_model=SavedSearchOut, status_code=201)
async def create_search(
    body: SavedSearchCreate, session: AsyncSession = Depends(get_session)
) -> SavedSearch:
    search = SavedSearch(
        name=body.name,
        module=body.module,
        criteria=body.criteria,
        owner_id=body.owner_id,
    )
    session.add(search)
    await session.commit()
    await session.refresh(search)
    return search


@router.post("/searches/{search_id}/run", response_model=list[RemarkContext])
async def run_search(
    search_id: int, session: AsyncSession = Depends(get_session)
) -> list[RemarkContext]:
    """Replay a saved search's criteria through the remark-search path."""
    search = await session.get(SavedSearch, search_id)
    if search is None:
        raise HTTPException(status_code=404, detail=f"search {search_id} not found")
    c = search.criteria or {}
    return await _search_remarks(
        session,
        keyword=c.get("keyword"),
        field=c.get("field"),
        well_uid=c.get("well_uid"),
        date_from=_parse_date(c.get("date_from")),
        date_to=_parse_date(c.get("date_to")),
    )


@router.delete("/searches/{search_id}", status_code=204)
async def delete_search(search_id: int, session: AsyncSession = Depends(get_session)) -> None:
    search = await session.get(SavedSearch, search_id)
    if search is None:
        raise HTTPException(status_code=404, detail=f"search {search_id} not found")
    await session.delete(search)
    await session.commit()


# ── depths of interest ──────────────────────────────────────────────────
@router.get("/depths", response_model=list[DepthOut])
async def list_depths(
    well_uid: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[DepthOfInterest]:
    stmt = select(DepthOfInterest)
    if well_uid is not None:
        stmt = stmt.where(DepthOfInterest.well_uid == well_uid)
    stmt = stmt.order_by(DepthOfInterest.depth, DepthOfInterest.id)
    return list((await session.execute(stmt)).scalars().all())


@router.post("/depths", response_model=DepthOut, status_code=201)
async def create_depth(
    body: DepthCreate, session: AsyncSession = Depends(get_session)
) -> DepthOfInterest:
    depth = DepthOfInterest(
        well_uid=body.well_uid,
        depth=body.depth,
        note=body.note,
        report_id=body.report_id,
    )
    session.add(depth)
    await session.commit()
    await session.refresh(depth)
    return depth


@router.delete("/depths/{depth_id}", status_code=204)
async def delete_depth(depth_id: int, session: AsyncSession = Depends(get_session)) -> None:
    depth = await session.get(DepthOfInterest, depth_id)
    if depth is None:
        raise HTTPException(status_code=404, detail=f"depth {depth_id} not found")
    await session.delete(depth)
    await session.commit()


# ── scaffolds (routed placeholders for the remaining sub-modules) ───────
def _scaffold(module: str) -> dict:
    return {"module": module, "status": "scaffold", "items": []}


@router.get("/mud-stock")
async def mud_stock() -> dict:
    return _scaffold("mud-stock")


@router.get("/well-path")
async def well_path() -> dict:
    return _scaffold("well-path")


@router.get("/time-analysis")
async def time_analysis() -> dict:
    return _scaffold("time-analysis")


@router.get("/tools")
async def tools() -> dict:
    return _scaffold("tools")
