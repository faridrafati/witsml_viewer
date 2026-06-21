"""Phase 4 write/curation REST API (admin).

Thin write surface over the WITSML Store. Two raw passthroughs (AddToStore /
UpdateInStore) for callers that already hold valid WITSML 1.4.1.1 XML, plus
three convenience builders (well / wellbore / log) that accept a small JSON
body, serialize valid WITSML 1.4.1.1 XML (data namespace
``http://www.witsml.org/schemas/1series``, version ``1.4.1.1``) and AddToStore.

Every handler talks to the store through the authoritative
:class:`WitsmlClient` obtained via dependency injection. Upstream WITSML
failures map to HTTP 502; malformed/empty input maps to HTTP 400. Credentials
are never echoed back to the client.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from lxml import etree
from pydantic import BaseModel, Field

from app.witsml.client import WitsmlClient, get_default_client
from app.witsml.constants import (
    NS_DATA,
    WITSML_VERSION,
    is_success,
)

# WitsmlError lives alongside the SOAP client; import defensively so this module
# stays import-clean even if the symbol is renamed/absent.
try:  # pragma: no cover - trivial import guard
    from app.witsml.client import WitsmlError  # type: ignore
except Exception:  # pragma: no cover

    class WitsmlError(Exception):  # type: ignore
        """Fallback transport error type."""


log = logging.getLogger(__name__)
router = APIRouter(prefix="/store", tags=["store-write"])


# ── client dependency ────────────────────────────────────────────────────
async def get_client() -> WitsmlClient:
    """FastAPI dependency yielding the process-wide cached client.

    The client is long-lived and cached in the client module; we never close
    it here (that would invalidate the cache for concurrent requests).
    """
    return get_default_client()


# ── error helpers ────────────────────────────────────────────────────────
def _bad_gateway(detail: str) -> HTTPException:
    """502 for upstream WITSML transport failures. Never echoes credentials."""
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)


def _bad_request(detail: str) -> HTTPException:
    """400 for malformed input or a non-success store return code."""
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


# ── request bodies ───────────────────────────────────────────────────────
class RawWrite(BaseModel):
    """A pre-built WITSML write: object type plus serialized XML."""

    wmlType: str = Field(..., description="WITSML object type, e.g. 'well', 'log'.")
    xml: str = Field(..., description="Serialized WITSML 1.4.1.1 XMLin document.")


class WellBody(BaseModel):
    uid: str
    name: str | None = None
    field: str | None = None
    region: str | None = None
    country: str | None = None
    operator: str | None = None
    timeZone: str | None = None
    statusWell: str | None = None


class WellboreBody(BaseModel):
    uid: str
    uidWell: str
    name: str | None = None
    nameWell: str | None = None
    statusWellbore: str | None = None


class CurveBody(BaseModel):
    mnemonic: str
    unit: str | None = None
    curveDescription: str | None = None
    typeLogData: str | None = None


class LogBody(BaseModel):
    uid: str
    uidWell: str
    uidWellbore: str
    name: str | None = None
    nameWell: str | None = None
    nameWellbore: str | None = None
    indexType: str = "measured depth"
    indexCurve: str | None = None
    direction: str = "increasing"
    nullValue: str | None = None
    indexUom: str | None = None
    curves: list[CurveBody] = Field(default_factory=list)


# ── XML builders (WITSML 1.4.1.1, data namespace default) ────────────────
def _root(plural: str) -> etree._Element:
    return etree.Element(
        f"{{{NS_DATA}}}{plural}", nsmap={None: NS_DATA}, version=WITSML_VERSION
    )


def _sub(
    parent: etree._Element, tag: str, text: str | None = None, **attrib: str
) -> etree._Element:
    el = etree.SubElement(parent, f"{{{NS_DATA}}}{tag}")
    for k, v in attrib.items():
        if v is not None:
            el.set(k, v)
    if text is not None:
        el.text = text
    return el


def _serialize(root: etree._Element) -> str:
    return etree.tostring(root, encoding="unicode")


def build_well_xml(body: WellBody) -> str:
    root = _root("wells")
    well = _sub(root, "well", uid=body.uid)
    if body.name is not None:
        _sub(well, "name", body.name)
    if body.field is not None:
        _sub(well, "field", body.field)
    if body.region is not None:
        _sub(well, "region", body.region)
    if body.country is not None:
        _sub(well, "country", body.country)
    if body.operator is not None:
        _sub(well, "operator", body.operator)
    if body.timeZone is not None:
        _sub(well, "timeZone", body.timeZone)
    if body.statusWell is not None:
        _sub(well, "statusWell", body.statusWell)
    return _serialize(root)


def build_wellbore_xml(body: WellboreBody) -> str:
    root = _root("wellbores")
    wb = _sub(root, "wellbore", uid=body.uid, uidWell=body.uidWell)
    if body.nameWell is not None:
        _sub(wb, "nameWell", body.nameWell)
    if body.name is not None:
        _sub(wb, "name", body.name)
    if body.statusWellbore is not None:
        _sub(wb, "statusWellbore", body.statusWellbore)
    return _serialize(root)


def build_log_xml(body: LogBody) -> str:
    root = _root("logs")
    log_el = _sub(
        root, "log", uid=body.uid, uidWell=body.uidWell, uidWellbore=body.uidWellbore
    )
    if body.nameWell is not None:
        _sub(log_el, "nameWell", body.nameWell)
    if body.nameWellbore is not None:
        _sub(log_el, "nameWellbore", body.nameWellbore)
    if body.name is not None:
        _sub(log_el, "name", body.name)
    _sub(log_el, "indexType", body.indexType)
    # Default the index curve to the first declared curve when not provided.
    index_curve = body.indexCurve or (body.curves[0].mnemonic if body.curves else None)
    if index_curve is not None:
        _sub(log_el, "indexCurve", index_curve)
    _sub(log_el, "direction", body.direction)
    if body.nullValue is not None:
        _sub(log_el, "nullValue", body.nullValue)
    for curve in body.curves:
        lci = _sub(log_el, "logCurveInfo", uid=curve.mnemonic)
        _sub(lci, "mnemonic", curve.mnemonic)
        if curve.unit is not None:
            _sub(lci, "unit", curve.unit)
        if curve.curveDescription is not None:
            _sub(lci, "curveDescription", curve.curveDescription)
        if curve.typeLogData is not None:
            _sub(lci, "typeLogData", curve.typeLogData)
    return _serialize(root)


# ── write execution ──────────────────────────────────────────────────────
async def _add(
    client: WitsmlClient, wml_type: str, xml_in: str, *, what: str
) -> dict[str, object]:
    """Run AddToStore, mapping transport errors to 502 and bad codes to 400."""
    try:
        return_code, supp_msg = await client.add_to_store(wml_type, xml_in)
    except WitsmlError as exc:
        log.warning("WITSML error adding %s: %s", what, exc)
        raise _bad_gateway(f"WITSML store error while adding {what}: {exc}") from exc
    except Exception as exc:  # transport/SOAP failures
        log.warning("transport error adding %s: %s", what, exc)
        raise _bad_gateway(
            f"Failed to reach WITSML store while adding {what}."
        ) from exc
    return _result(return_code, supp_msg, what=f"add {what}")


async def _update(
    client: WitsmlClient, wml_type: str, xml_in: str, *, what: str
) -> dict[str, object]:
    """Run UpdateInStore, mapping transport errors to 502 and bad codes to 400."""
    try:
        return_code, supp_msg = await client.update_in_store(wml_type, xml_in)
    except WitsmlError as exc:
        log.warning("WITSML error updating %s: %s", what, exc)
        raise _bad_gateway(f"WITSML store error while updating {what}: {exc}") from exc
    except Exception as exc:
        log.warning("transport error updating %s: %s", what, exc)
        raise _bad_gateway(
            f"Failed to reach WITSML store while updating {what}."
        ) from exc
    return _result(return_code, supp_msg, what=f"update {what}")


def _result(return_code: int, supp_msg: str | None, *, what: str) -> dict[str, object]:
    """Shape a write result, raising 400 on a non-success return code."""
    if not is_success(return_code):
        base = supp_msg or "no detail provided by server"
        log.warning("WITSML non-success (%s) on %s: %s", return_code, what, base)
        raise _bad_request(
            f"WITSML store returned code {return_code} on {what}: {base}"
        )
    return {"returnCode": return_code, "message": supp_msg or ""}


# ── endpoints ─────────────────────────────────────────────────────────────
@router.post("/add")
async def add_to_store(
    body: RawWrite, client: WitsmlClient = Depends(get_client)
) -> dict[str, object]:
    """WMLS_AddToStore — add a caller-supplied WITSML object."""
    return await _add(client, body.wmlType, body.xml, what=body.wmlType)


@router.post("/update")
async def update_in_store(
    body: RawWrite, client: WitsmlClient = Depends(get_client)
) -> dict[str, object]:
    """WMLS_UpdateInStore — update/append to a caller-supplied WITSML object."""
    return await _update(client, body.wmlType, body.xml, what=body.wmlType)


@router.post("/well")
async def add_well(
    body: WellBody, client: WitsmlClient = Depends(get_client)
) -> dict[str, object]:
    """Build a WITSML 1.4.1.1 <well> from JSON and AddToStore."""
    return await _add(client, "well", build_well_xml(body), what="well")


@router.post("/wellbore")
async def add_wellbore(
    body: WellboreBody, client: WitsmlClient = Depends(get_client)
) -> dict[str, object]:
    """Build a WITSML 1.4.1.1 <wellbore> from JSON and AddToStore."""
    return await _add(client, "wellbore", build_wellbore_xml(body), what="wellbore")


@router.post("/log")
async def add_log(
    body: LogBody, client: WitsmlClient = Depends(get_client)
) -> dict[str, object]:
    """Build a WITSML 1.4.1.1 <log> header from JSON and AddToStore."""
    return await _add(client, "log", build_log_xml(body), what="log")
