"""Multi-well comparison REST API.

A single endpoint that aligns up to four wells side-by-side: recent curve
data pulled from the warm ring buffer plus per-well lithology fetched live
from the WITSML store's mudLogs. The shape is intentionally flat (one entry
per well, curves keyed by mnemonic, lithology flattened one row per entry)
so the frontend can lay wells out in parallel tracks without reshaping.

Resilience is the priority: a single well whose mudLog query fails, or that
has no buffered curves, must never 500 the whole comparison. Per-well
failures degrade to empty `curves` / `lithology` for that well only.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status

from app.ingestion.store import get_store, sample_to_wire
from app.witsml.client import get_default_client
from app.witsml.constants import is_success
from app.witsml.parse import parse_mudlogs, parse_wellbores
from app.witsml.queries import mudlog_query, wellbore_query

log = logging.getLogger(__name__)

router = APIRouter(prefix="/comparison", tags=["comparison"])

MAX_WELLS = 4


def _split_csv(raw: str | None) -> list[str]:
    """Parse a comma-separated param into a clean, de-duplicated list."""
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        item = item.strip()
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


async def _run_query(client, wml_type: str, query_xml: str, options_in: str) -> str | None:
    """Run one GetFromStore, returning XMLout or None on any failure.

    Comparison is best-effort: callers swallow None into an empty result for
    that well rather than surfacing an upstream error to the whole request.
    """
    try:
        return_code, xml_out, supp_msg = await client.get_from_store(
            wml_type, query_xml, options_in=options_in
        )
    except Exception as exc:  # transport / SOAP / parse failures
        log.warning("comparison: store query failed: %s", exc)
        return None
    if not is_success(return_code) or xml_out is None:
        log.warning(
            "comparison: store non-success (%s): %s",
            return_code,
            supp_msg or "no detail",
        )
        return None
    return xml_out


async def _wellbore_uids(client, well_uid: str) -> list[str]:
    """Discover wellbore uids under a well (empty list if discovery fails)."""
    q = wellbore_query(well_uid)
    xml = await _run_query(client, q.wml_type, q.query_xml, q.options_in)
    if xml is None:
        return []
    try:
        return [wb.uid for wb in parse_wellbores(xml) if wb.uid]
    except Exception as exc:  # pragma: no cover - defensive parse guard
        log.warning("comparison: parse wellbores failed for %s: %s", well_uid, exc)
        return []


async def _lithology_for_well(client, well_uid: str) -> list[dict]:
    """Flatten every mudLog's geology intervals into per-lithology rows.

    One output row per `<lithology>` entry, carrying its parent interval's
    mdTop / mdBottom / uom. Intervals with no explicit lithologies still emit
    a single row so the depth band is not lost.
    """
    wellbore_uids = await _wellbore_uids(client, well_uid)
    if not wellbore_uids:
        return []

    rows: list[dict] = []
    for wb_uid in wellbore_uids:
        q = mudlog_query(well_uid, wb_uid)
        xml = await _run_query(client, q.wml_type, q.query_xml, q.options_in)
        if xml is None:
            continue
        try:
            mudlogs = parse_mudlogs(xml)
        except Exception as exc:  # pragma: no cover - defensive parse guard
            log.warning("comparison: parse mudlogs failed for %s: %s", well_uid, exc)
            continue
        for ml in mudlogs:
            for gi in ml.geology_intervals:
                base = {
                    "mdTop": gi.md_top,
                    "mdBottom": gi.md_bottom,
                    "uom": gi.md_uom,
                }
                if gi.lithologies:
                    for lith in gi.lithologies:
                        rows.append(
                            {
                                **base,
                                "type": lith.type,
                                "codeLith": lith.code_lith,
                                "lithPc": lith.lith_pc,
                                "description": lith.description or gi.description,
                            }
                        )
                else:
                    rows.append(
                        {
                            **base,
                            "type": gi.type_lithology,
                            "codeLith": None,
                            "lithPc": None,
                            "description": gi.description,
                        }
                    )
    return rows


def _curves_for_well(well_uid: str, mnemonics: list[str], limit: int) -> dict:
    """Recent samples per mnemonic from the warm store (empty on miss)."""
    try:
        recent = get_store().get_recent(well_uid, mnemonics or None, limit=limit)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("comparison: warm store read failed for %s: %s", well_uid, exc)
        return {}
    return {m: [sample_to_wire(s) for s in samples] for m, samples in recent.items()}


def _well_name(well_uid: str) -> str | None:
    """Best-effort display name from warm-store well metadata."""
    try:
        for status_row in get_store().well_status():
            if status_row.well_uid == well_uid:
                return status_row.name
    except Exception:  # pragma: no cover - defensive
        pass
    return None


@router.get("/")
async def compare(
    wells: str = Query(..., description="Comma-separated well_uids (max 4)."),
    mnemonics: str | None = Query(default=None),
    limit: int = Query(default=2000, ge=1),
) -> dict:
    """Depth/time-aligned curve + lithology bundle for up to four wells."""
    well_uids = _split_csv(wells)
    if not well_uids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one well_uid is required.",
        )
    if len(well_uids) > MAX_WELLS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"At most {MAX_WELLS} wells may be compared at once.",
        )

    mnems = _split_csv(mnemonics)
    client = get_default_client()

    out_wells: list[dict] = []
    for well_uid in well_uids:
        curves = _curves_for_well(well_uid, mnems, limit)
        try:
            lithology = await _lithology_for_well(client, well_uid)
        except Exception as exc:  # pragma: no cover - belt-and-suspenders
            log.warning("comparison: lithology failed for %s: %s", well_uid, exc)
            lithology = []
        out_wells.append(
            {
                "wellUid": well_uid,
                "name": _well_name(well_uid),
                "curves": curves,
                "lithology": lithology,
            }
        )

    return {"wells": out_wells}
