"""FastAPI SOAP 1.1 endpoint for the in-memory WITSML 1.4.1.1 mock store.

Serves the WMLS Store contract the project's zeep client speaks:

  * ``GET  {path}?wsdl`` -> the WSDL, with the single <soap:address location>
    rewritten to the live request URL so a client that loads ``{url}?wsdl``
    binds to the right endpoint.
  * ``POST {path}``      -> a SOAP 1.1 envelope. The operation is identified
    from the body child element name (falling back to the SOAPAction header),
    the parts are parsed with lxml, dispatched to :class:`mockstore.store.MockStore`,
    and a SOAP 1.1 response envelope is returned with the correct part elements.

HTTP Basic auth is accepted but never enforced — this is a dev/test rig.

Run::

    python -m mockstore.server          # uvicorn on 0.0.0.0:7070
    MOCK_STORE_PATH=/Witsml/Store python -m mockstore.server
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Request, Response
from lxml import etree

from mockstore.store import (
    RC_ERROR_BAD_INPUT,
    MockStore,
)

# ── Namespaces ──────────────────────────────────────────────────────────────
SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"
WMLS_NS = "http://www.witsml.org/wsdl/120"
WSDL_NS = "http://schemas.xmlsoap.org/wsdl/"
WSDL_SOAP_NS = "http://schemas.xmlsoap.org/wsdl/soap/"

# ── Serve path / WSDL location ──────────────────────────────────────────────
STORE_PATH = os.environ.get("MOCK_STORE_PATH", "/witsml/store")
_WSDL_FILE = os.path.join(os.path.dirname(__file__), "wmls.wsdl")

# A single shared store instance for the process lifetime.
store = MockStore()

app = FastAPI(title="WITSML 1.4.1.1 Mock Store", version="1.4.1.1")


# ── WSDL serving (location rewrite) ─────────────────────────────────────────
def _load_wsdl_bytes() -> bytes:
    with open(_WSDL_FILE, "rb") as fh:
        return fh.read()


def _wsdl_with_location(endpoint_url: str) -> bytes:
    """Return the WSDL with <soap:address location> set to endpoint_url."""
    tree = etree.fromstring(_load_wsdl_bytes())
    for addr in tree.iter(f"{{{WSDL_SOAP_NS}}}address"):
        addr.set("location", endpoint_url)
    return etree.tostring(tree, xml_declaration=True, encoding="UTF-8")


def _endpoint_url(request: Request) -> str:
    """The public endpoint URL for this request (scheme+host+path, no query)."""
    url = request.url
    scheme = request.headers.get("x-forwarded-proto", url.scheme)
    host = request.headers.get("host") or url.netloc
    return f"{scheme}://{host}{url.path}"


# ── SOAP envelope helpers ───────────────────────────────────────────────────
def _wmls(tag: str) -> str:
    return f"{{{WMLS_NS}}}{tag}"


def _find_body_op(envelope: etree._Element) -> etree._Element | None:
    """Return the first child element of <soap:Body>."""
    for body in envelope.iter(f"{{{SOAP_ENV}}}Body"):
        for child in body:
            if isinstance(child.tag, str):
                return child
    return None


def _part_text(op_el: etree._Element, local_name: str) -> str:
    """Text of a request part child by local-name (namespace-agnostic)."""
    for child in op_el:
        if isinstance(child.tag, str) and etree.QName(child).localname == local_name:
            return child.text or ""
    return ""


def _envelope(body_children: list[etree._Element]) -> bytes:
    env = etree.Element(
        f"{{{SOAP_ENV}}}Envelope", nsmap={"soap": SOAP_ENV, "wmls": WMLS_NS}
    )
    body = etree.SubElement(env, f"{{{SOAP_ENV}}}Body")
    for child in body_children:
        body.append(child)
    return etree.tostring(env, xml_declaration=True, encoding="UTF-8")


def _response_el(op_name: str, parts: list[tuple[str, str]]) -> etree._Element:
    """Build <wmls:{op}Response> with ordered (partName, text) child elements."""
    resp = etree.Element(_wmls(f"{op_name}Response"))
    for name, text in parts:
        child = etree.SubElement(resp, _wmls(name))
        child.text = text if text is not None else ""
    return resp


def _soap_fault(message: str) -> bytes:
    env = etree.Element(f"{{{SOAP_ENV}}}Envelope", nsmap={"soap": SOAP_ENV})
    body = etree.SubElement(env, f"{{{SOAP_ENV}}}Body")
    fault = etree.SubElement(body, f"{{{SOAP_ENV}}}Fault")
    code = etree.SubElement(fault, "faultcode")
    code.text = "soap:Server"
    reason = etree.SubElement(fault, "faultstring")
    reason.text = message
    return etree.tostring(env, xml_declaration=True, encoding="UTF-8")


# ── Operation dispatch ──────────────────────────────────────────────────────
def _base_msg(code: int) -> str:
    table = {
        1: "Function completed successfully.",
        2: "Partial success: function returned a truncated result set.",
        -405: "Data-object already exists in the store.",
        -407: "Missing or invalid input XML / query.",
        -411: "The query did not match an object in the store.",
    }
    return table.get(code, f"WITSML return code {code}.")


def _dispatch(op_name: str, op_el: etree._Element) -> etree._Element:
    """Run an operation and return its response element."""
    if op_name == "WMLS_GetVersion":
        return _response_el("WMLS_GetVersion", [("Result", "1.4.1.1")])

    if op_name == "WMLS_GetCap":
        cap_xml = store.capabilities_xml()
        # Standard WITSML names the GetCap output part CapabilitiesOut (the
        # client now reads it via _result_triple). Emit ONLY the standard part.
        return _response_el(
            "WMLS_GetCap",
            [
                ("Result", "1"),
                ("CapabilitiesOut", cap_xml),
                ("SuppMsgOut", ""),
            ],
        )

    if op_name == "WMLS_GetFromStore":
        wml_type = _part_text(op_el, "WMLtypeIn")
        query_in = _part_text(op_el, "QueryIn")
        options_in = _part_text(op_el, "OptionsIn")
        rc, xml_out, supp = store.query(wml_type, query_in, options_in)
        return _response_el(
            "WMLS_GetFromStore",
            [("Result", str(rc)), ("XMLout", xml_out), ("SuppMsgOut", supp or "")],
        )

    if op_name == "WMLS_AddToStore":
        wml_type = _part_text(op_el, "WMLtypeIn")
        xml_in = _part_text(op_el, "XMLin")
        rc, supp = store.add_object(wml_type, xml_in)
        return _response_el(
            "WMLS_AddToStore",
            [("Result", str(rc)), ("SuppMsgOut", supp or "")],
        )

    if op_name == "WMLS_UpdateInStore":
        wml_type = _part_text(op_el, "WMLtypeIn")
        xml_in = _part_text(op_el, "XMLin")
        rc, supp = store.update_object(wml_type, xml_in)
        return _response_el(
            "WMLS_UpdateInStore",
            [("Result", str(rc)), ("SuppMsgOut", supp or "")],
        )

    if op_name == "WMLS_DeleteFromStore":
        wml_type = _part_text(op_el, "WMLtypeIn")
        query_in = _part_text(op_el, "QueryIn")
        rc, supp = store.delete_object(wml_type, query_in)
        return _response_el(
            "WMLS_DeleteFromStore",
            [("Result", str(rc)), ("SuppMsgOut", supp or "")],
        )

    if op_name == "WMLS_GetBaseMsg":
        code = _part_text(op_el, "ReturnValueIn")
        try:
            code_i = int(code)
        except (TypeError, ValueError):
            code_i = RC_ERROR_BAD_INPUT
        return _response_el("WMLS_GetBaseMsg", [("Result", _base_msg(code_i))])

    # Unknown op: best-effort empty success-ish response.
    return _response_el(op_name, [("Result", "-425")])


def _op_name_from_action(action: str | None) -> str | None:
    if not action:
        return None
    action = action.strip().strip('"')
    if "." in action:
        return action.rsplit(".", 1)[-1]
    if "/" in action:
        return action.rsplit("/", 1)[-1]
    return action or None


# ── Routes ──────────────────────────────────────────────────────────────────
@app.get(STORE_PATH)
async def get_wsdl(request: Request) -> Response:
    """Serve the WSDL (or a WADL-ish hint) on ?wsdl."""
    if "wsdl" in request.query_params:
        endpoint = _endpoint_url(request)
        return Response(
            content=_wsdl_with_location(endpoint),
            media_type="text/xml",
        )
    return Response(
        content=b"WITSML 1.4.1.1 Mock Store. Append ?wsdl for the service definition.",
        media_type="text/plain",
    )


@app.post(STORE_PATH)
async def post_soap(request: Request) -> Response:
    """Handle a SOAP 1.1 request envelope."""
    raw = await request.body()
    try:
        envelope = etree.fromstring(raw)
    except etree.XMLSyntaxError as exc:
        return Response(
            content=_soap_fault(f"malformed SOAP envelope: {exc}"),
            media_type="text/xml",
            status_code=500,
        )

    op_el = _find_body_op(envelope)
    op_name: str | None = None
    if op_el is not None and isinstance(op_el.tag, str):
        op_name = etree.QName(op_el).localname
    if not op_name:
        op_name = _op_name_from_action(request.headers.get("soapaction"))

    if not op_name or op_el is None:
        return Response(
            content=_soap_fault("could not identify SOAP operation"),
            media_type="text/xml",
            status_code=500,
        )

    try:
        resp_el = _dispatch(op_name, op_el)
    except Exception as exc:  # noqa: BLE001 — surface as a SOAP fault
        return Response(
            content=_soap_fault(f"{op_name} failed: {exc}"),
            media_type="text/xml",
            status_code=500,
        )

    return Response(content=_envelope([resp_el]), media_type="text/xml")


# Also accept POSTs to the bare WSDL URL (some stacks post to {path}?wsdl).
@app.get("/")
async def root() -> Response:
    return Response(
        content=f"WITSML Mock Store up. POST SOAP to {STORE_PATH}; WSDL at "
        f"{STORE_PATH}?wsdl".encode(),
        media_type="text/plain",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "mockstore.server:app",
        host="0.0.0.0",
        port=7070,
        log_level="info",
    )
