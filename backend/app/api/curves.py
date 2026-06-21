"""REST surface over the warm store + Postgres curve cache (ingest API).

Three of the four endpoints read from the in-memory ring buffer (the warm
store fed by the scheduler): cross-well status, recent curves, and latest
samples. The fourth (`/history`) reads `CurveSampleRow` from Postgres so the
UI can back-fill beyond the bounded ring buffer. Everything here is read-only
and import-clean — no work runs at import.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.db.models import CurveSampleRow
from app.ingestion.store import WellStatus, get_store, sample_to_wire

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _split_mnemonics(mnemonics: str | None) -> list[str] | None:
    """Parse a comma-separated mnemonics param into a clean list (or None)."""
    if not mnemonics:
        return None
    out = [m.strip() for m in mnemonics.split(",") if m.strip()]
    return out or None


def _parse_index(raw: str | None) -> float | datetime | None:
    """Accept either a numeric depth index or an ISO-8601 timestamp."""
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        pass
    iso = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


@router.get("/wells", response_model=list[WellStatus])
def list_wells() -> list[WellStatus]:
    """Cross-well status for all warm wells (keeps the 'ingest 20' visible)."""
    return get_store().well_status()


@router.get("/wells/{well_uid}/curves")
def get_curves(
    well_uid: str,
    mnemonics: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1),
) -> dict:
    """Recent samples per mnemonic from the warm ring buffer."""
    mnems = _split_mnemonics(mnemonics)
    recent = get_store().get_recent(well_uid, mnems, limit=limit)
    return {
        "wellUid": well_uid,
        "curves": {m: [sample_to_wire(s) for s in samples] for m, samples in recent.items()},
    }


@router.get("/wells/{well_uid}/latest")
def get_latest(
    well_uid: str,
    mnemonics: str | None = Query(default=None),
) -> dict:
    """Latest single sample per mnemonic (or null when no data buffered)."""
    mnems = _split_mnemonics(mnemonics)
    recent = get_store().get_recent(well_uid, mnems, limit=1)
    out: dict[str, dict | None] = {m: None for m in mnems} if mnems else {}
    for m, samples in recent.items():
        out[m] = sample_to_wire(samples[-1]) if samples else None
    return {"wellUid": well_uid, "latest": out}


@router.get("/wells/{well_uid}/history")
async def get_history(
    well_uid: str,
    mnemonics: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=200_000),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Back-fill from Postgres `curve_samples`, ordered by index.

    `start`/`end` accept a numeric depth index or an ISO timestamp; the bound
    is applied against whichever index column (float or datetime) it parses to.
    """
    mnems = _split_mnemonics(mnemonics)
    start_idx = _parse_index(start)
    end_idx = _parse_index(end)

    stmt = select(CurveSampleRow).where(CurveSampleRow.well_uid == well_uid)
    if mnems:
        stmt = stmt.where(CurveSampleRow.mnemonic.in_(mnems))

    for bound, op in ((start_idx, "ge"), (end_idx, "le")):
        if bound is None:
            continue
        col = CurveSampleRow.index_dt if isinstance(bound, datetime) else CurveSampleRow.index_float
        stmt = stmt.where(col >= bound if op == "ge" else col <= bound)

    stmt = stmt.order_by(CurveSampleRow.index_float.asc(), CurveSampleRow.index_dt.asc()).limit(
        limit
    )

    rows = (await session.execute(stmt)).scalars().all()

    curves: dict[str, list[dict]] = {}
    for row in rows:
        if row.index_dt is not None:
            idx: float = row.index_dt.timestamp() * 1000.0
        elif row.index_float is not None:
            idx = float(row.index_float)
        else:
            continue
        curves.setdefault(row.mnemonic, []).append(
            {"i": idx, "v": row.value, "t": row.text, "u": row.uom}
        )

    return {"wellUid": well_uid, "curves": curves}
