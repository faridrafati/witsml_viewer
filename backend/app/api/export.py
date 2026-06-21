"""Export REST surface — XLSX and PDF renders of curve data (§7.9).

Two POST endpoints assemble curve samples for one well and stream a downloadable
artifact:

  * ``POST /export/xlsx`` -> one column per mnemonic (with units in the header)
    plus a leading index column (time or depth), as a .xlsx attachment.
  * ``POST /export/pdf``  -> a stacked multi-track 'Draw' view, one small line
    plot per mnemonic, as a .pdf attachment.

Data is read from the warm ring buffer (``get_store().get_recent``) and topped
up from the Postgres ``CurveSampleRow`` history when the in-memory buffer is thin
(or empty). History reads are best-effort: a DB failure degrades to warm-store
data only rather than failing the export.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.db.models import CurveSampleRow
from app.domain.models import CurveSample
from app.export.excel import assemble_rows, build_curves_xlsx
from app.export.pdf import build_tracks_pdf
from app.ingestion.store import get_store, sample_to_wire

log = logging.getLogger(__name__)

router = APIRouter(prefix="/export", tags=["export"])

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


# ── request bodies ──────────────────────────────────────────────────────
class XlsxExportRequest(BaseModel):
    well_uid: str = Field(alias="wellUid")
    mnemonics: list[str] = Field(default_factory=list)
    index_type: str = Field(default="time", alias="indexType")  # "time" | "depth"
    limit: int = Field(default=10_000, ge=1, le=200_000)

    model_config = {"populate_by_name": True}


class PdfExportRequest(BaseModel):
    well_uid: str = Field(alias="wellUid")
    mnemonics: list[str] = Field(default_factory=list)
    title: str | None = None
    index_type: str = Field(default="time", alias="indexType")
    limit: int = Field(default=10_000, ge=1, le=200_000)

    model_config = {"populate_by_name": True}


# ── data assembly ───────────────────────────────────────────────────────
def _safe_filename(stem: str, ext: str) -> str:
    cleaned = _SAFE_NAME.sub("_", stem).strip("_") or "export"
    return f"{cleaned}.{ext}"


def _row_to_sample(row: CurveSampleRow) -> CurveSample:
    """Map a persisted history row back to a domain CurveSample."""
    index: float | datetime
    if row.index_dt is not None:
        index = row.index_dt
    else:
        index = float(row.index_float) if row.index_float is not None else 0.0
    return CurveSample(
        mnemonic=row.mnemonic,
        index=index,
        value=row.value,
        text=row.text,
        uom=row.uom,
    )


async def _history_samples(
    session: AsyncSession,
    well_uid: str,
    mnemonics: list[str],
    limit: int,
) -> dict[str, list[CurveSample]]:
    """Best-effort Postgres back-fill keyed by mnemonic (oldest -> newest)."""
    stmt = select(CurveSampleRow).where(CurveSampleRow.well_uid == well_uid)
    if mnemonics:
        stmt = stmt.where(CurveSampleRow.mnemonic.in_(mnemonics))
    stmt = stmt.order_by(CurveSampleRow.index_float.asc(), CurveSampleRow.index_dt.asc()).limit(
        limit
    )

    out: dict[str, list[CurveSample]] = {}
    try:
        rows = (await session.execute(stmt)).scalars().all()
    except Exception as exc:  # pragma: no cover - DB optional / unavailable
        log.warning("export: history read failed for %s: %s", well_uid, exc)
        return out
    for row in rows:
        out.setdefault(row.mnemonic, []).append(_row_to_sample(row))
    return out


async def _gather_curves(
    session: AsyncSession,
    well_uid: str,
    mnemonics: list[str],
    limit: int,
) -> dict[str, list[CurveSample]]:
    """Merge warm-store recent samples with Postgres history per mnemonic.

    Warm-store samples win on overlap; history fills mnemonics (or stretches)
    the bounded ring buffer doesn't cover. Per-mnemonic lists end sorted by
    index so downstream pivots/plots are monotonic.
    """
    mnems = mnemonics or None
    try:
        warm = get_store().get_recent(well_uid, mnems, limit=limit)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("export: warm store read failed for %s: %s", well_uid, exc)
        warm = {}

    history = await _history_samples(session, well_uid, mnemonics, limit)

    keys = set(warm) | set(history)
    merged: dict[str, list[CurveSample]] = {}
    for mnem in keys:
        seen: set[float] = set()
        combined: list[CurveSample] = []
        for s in warm.get(mnem, []) + history.get(mnem, []):
            ts = s.index.timestamp() if isinstance(s.index, datetime) else float(s.index)
            if ts in seen:
                continue
            seen.add(ts)
            combined.append(s)
        combined.sort(
            key=lambda s: s.index.timestamp() if isinstance(s.index, datetime) else float(s.index)
        )
        if len(combined) > limit:
            combined = combined[-limit:]
        merged[mnem] = combined
    return merged


def _ordered_mnemonics(requested: list[str], curves: dict[str, list[CurveSample]]) -> list[str]:
    """Preserve the requested order; otherwise sort whatever the store had."""
    if requested:
        return [m for m in requested if m in curves] or list(curves)
    return sorted(curves)


# ── endpoints ───────────────────────────────────────────────────────────
@router.post("/xlsx")
async def export_xlsx(
    body: XlsxExportRequest,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Build a curves spreadsheet (one column per mnemonic, unit-tagged)."""
    curves = await _gather_curves(session, body.well_uid, body.mnemonics, body.limit)
    mnems = _ordered_mnemonics(body.mnemonics, curves)
    index_label = "Depth" if body.index_type == "depth" else "Time"

    columns, rows, units = assemble_rows(curves, mnems, index_label)
    data = build_curves_xlsx(body.well_uid, columns, rows, index_label, units=units)
    filename = _safe_filename(f"{body.well_uid}_curves", "xlsx")
    return Response(
        content=data,
        media_type=XLSX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/pdf")
async def export_pdf(
    body: PdfExportRequest,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Render a stacked multi-track PDF of the requested mnemonics."""
    curves = await _gather_curves(session, body.well_uid, body.mnemonics, body.limit)
    mnems = _ordered_mnemonics(body.mnemonics, curves)

    wire_curves = {m: [sample_to_wire(s) for s in curves.get(m, [])] for m in mnems}
    name = get_store_well_name(body.well_uid)
    wells_curves = [{"wellUid": body.well_uid, "name": name, "curves": wire_curves}]
    title = body.title or f"Curve Tracks — {name or body.well_uid}"
    meta = {
        "indexType": body.index_type,
        "generatedAt": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    }
    data = build_tracks_pdf(title, wells_curves, meta)
    filename = _safe_filename(f"{body.well_uid}_tracks", "pdf")
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def get_store_well_name(well_uid: str) -> str | None:
    """Best-effort display name from warm-store well metadata."""
    try:
        for row in get_store().well_status():
            if row.well_uid == well_uid:
                return row.name
    except Exception:  # pragma: no cover - defensive
        pass
    return None
