"""Phase 1 discovery REST API.

Read-only endpoints that surface the WITSML store as a browsable tree:
version, capabilities, wells, wellbores, log headers and mudLogs. Every
handler talks to the store through the authoritative :class:`WitsmlClient`
(obtained via FastAPI dependency injection) and translates raw GetFromStore
return codes / transport errors into clean HTTP responses.

No background tasks, no polling — that is the ingestion layer's job. This
module only fans out one request per call and shapes the result.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.domain.models import LogHeader, MudLog, Well, Wellbore
from app.witsml.client import WitsmlClient, get_default_client
from app.witsml.constants import is_success
from app.witsml.parse import (
    ServerCap,
    parse_log_headers,
    parse_mudlogs,
    parse_wellbores,
    parse_wells,
)
from app.witsml.queries import (
    log_header_query,
    mudlog_query,
    well_query,
    wellbore_query,
)

# WitsmlError is defined alongside the SOAP client; import defensively so this
# module stays import-clean even if the symbol is renamed/absent.
try:  # pragma: no cover - trivial import guard
    from app.witsml.client import WitsmlError  # type: ignore
except Exception:  # pragma: no cover

    class WitsmlError(Exception):  # type: ignore
        """Fallback transport error type."""


log = logging.getLogger(__name__)
router = APIRouter(tags=["discovery"])


# ── client dependency ───────────────────────────────────────────────────
async def get_client() -> WitsmlClient:
    """FastAPI dependency yielding the process-wide cached client.

    The client is long-lived and cached in the client module; we never close
    it here (that would invalidate the cache for concurrent requests).
    """
    return get_default_client()


# ── error helpers ───────────────────────────────────────────────────────
def _bad_gateway(detail: str) -> HTTPException:
    """502 for upstream WITSML failures. Never echoes credentials."""
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)


async def _query(
    client: WitsmlClient,
    wml_type: str,
    query_xml: str,
    options_in: str,
    *,
    what: str,
) -> str:
    """Run a GetFromStore and return XMLout, mapping failures to HTTP 502."""
    try:
        return_code, xml_out, supp_msg = await client.get_from_store(
            wml_type, query_xml, options_in=options_in
        )
    except WitsmlError as exc:
        log.warning("WITSML error fetching %s: %s", what, exc)
        raise _bad_gateway(f"WITSML store error while fetching {what}: {exc}") from exc
    except Exception as exc:  # transport/SOAP/parse failures
        log.warning("transport error fetching %s: %s", what, exc)
        raise _bad_gateway(
            f"Failed to reach WITSML store while fetching {what}."
        ) from exc

    if not is_success(return_code) or xml_out is None:
        base = supp_msg or "no detail provided by server"
        log.warning("WITSML non-success (%s) fetching %s: %s", return_code, what, base)
        raise _bad_gateway(
            f"WITSML store returned code {return_code} while fetching {what}: {base}"
        )
    return xml_out


# ── endpoints ────────────────────────────────────────────────────────────
@router.get("/version")
async def get_version(client: WitsmlClient = Depends(get_client)) -> dict[str, str]:
    """WMLS_GetVersion — the store's supported data version(s)."""
    try:
        version = await client.get_version()
    except WitsmlError as exc:
        raise _bad_gateway(f"WITSML store error reading version: {exc}") from exc
    except Exception as exc:
        raise _bad_gateway("Failed to reach WITSML store for version.") from exc
    return {"version": version}


@router.get("/cap", response_model=ServerCap)
async def get_cap(client: WitsmlClient = Depends(get_client)) -> ServerCap:
    """WMLS_GetCap — parsed server capabilities (dataVersion=1.4.1.1)."""
    try:
        return await client.get_cap()
    except WitsmlError as exc:
        raise _bad_gateway(f"WITSML store error reading capabilities: {exc}") from exc
    except Exception as exc:
        raise _bad_gateway("Failed to reach WITSML store for capabilities.") from exc


@router.get("/wells", response_model=list[Well])
async def list_wells(client: WitsmlClient = Depends(get_client)) -> list[Well]:
    """All wells (id-only QBE -> parsed Well list)."""
    q = well_query()
    xml = await _query(client, q.wml_type, q.query_xml, q.options_in, what="wells")
    return parse_wells(xml)


@router.get("/wells/{well_uid}/wellbores", response_model=list[Wellbore])
async def list_wellbores(
    well_uid: str, client: WitsmlClient = Depends(get_client)
) -> list[Wellbore]:
    """Wellbores under one well."""
    q = wellbore_query(well_uid)
    xml = await _query(
        client,
        q.wml_type,
        q.query_xml,
        q.options_in,
        what=f"wellbores for well {well_uid}",
    )
    return parse_wellbores(xml)


@router.get(
    "/wells/{well_uid}/wellbores/{wb_uid}/logs",
    response_model=list[LogHeader],
)
async def list_logs(
    well_uid: str, wb_uid: str, client: WitsmlClient = Depends(get_client)
) -> list[LogHeader]:
    """Header-only log metadata for a wellbore."""
    q = log_header_query(well_uid, wb_uid)
    xml = await _query(
        client,
        q.wml_type,
        q.query_xml,
        q.options_in,
        what=f"logs for wellbore {wb_uid}",
    )
    return parse_log_headers(xml)


@router.get(
    "/wells/{well_uid}/wellbores/{wb_uid}/mudlogs",
    response_model=list[MudLog],
)
async def list_mudlogs(
    well_uid: str, wb_uid: str, client: WitsmlClient = Depends(get_client)
) -> list[MudLog]:
    """MudLogs (geology/lithology intervals) for a wellbore."""
    q = mudlog_query(well_uid, wb_uid)
    xml = await _query(
        client,
        q.wml_type,
        q.query_xml,
        q.options_in,
        what=f"mudLogs for wellbore {wb_uid}",
    )
    return parse_mudlogs(xml)


@router.get("/tree", response_model=list[Well])
async def get_tree(client: WitsmlClient = Depends(get_client)) -> list[Well]:
    """Wells with their wellbores nested — convenience for the WellTree UI.

    One well query plus one wellbore query per well. Wellbore failures for an
    individual well are tolerated (that well simply renders with no children)
    so a single bad well does not blank the whole tree.
    """
    wells_q = well_query()
    wells_xml = await _query(
        client, wells_q.wml_type, wells_q.query_xml, wells_q.options_in, what="wells"
    )
    wells = parse_wells(wells_xml)

    for well in wells:
        wb_q = wellbore_query(well.uid)
        try:
            wb_xml = await _query(
                client,
                wb_q.wml_type,
                wb_q.query_xml,
                wb_q.options_in,
                what=f"wellbores for well {well.uid}",
            )
            well.wellbores = parse_wellbores(wb_xml)
        except HTTPException as exc:
            log.warning(
                "tree: skipping wellbores for well %s: %s", well.uid, exc.detail
            )
            well.wellbores = []
    return wells
