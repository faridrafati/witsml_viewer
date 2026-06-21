"""Async SOAP gateway over the WITSML 1.4.1.1 Store WSDL.

Wraps the WMLS_* operations behind a small, typed surface the rest of the app
consumes. zeep does the SOAP marshalling; an httpx-backed AsyncTransport keeps
every call awaitable. The WSDL is loaded lazily on first use so importing this
module never touches the network (brief §10).

Correctness rules implemented here:
  * GetCap always sends OptionsIn `dataVersion=1.4.1.1` (queries.get_cap_options).
  * get_log_data runs the +2 truncation loop: re-query from the continuation
    index until the server reports full success (+1), merging batches with
    polling.merge_blocks (brief §11.2).
  * Any non-positive return code raises WitsmlError with a best-effort message.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from zeep import AsyncClient
from zeep import Settings as ZeepSettings
from zeep.transports import AsyncTransport

from app.config import settings as app_settings
from app.domain.models import LogDataBlock
from app.witsml import polling, queries
from app.witsml.constants import (
    Direction,
    IndexType,
    is_error,
    is_success,
    is_truncated,
)
from app.witsml.parse import (
    LogDataResult,
    ServerCap,
    parse_cap,
    parse_log_data,
)

#: Hard cap on +2-loop iterations, so a misbehaving server can't hang ingestion.
_MAX_TRUNCATION_ITERATIONS = 1000


class WitsmlError(RuntimeError):
    """A WMLS_* operation returned a non-success (<= 0) result code."""

    def __init__(self, return_code: int | None, message: str | None = None) -> None:
        self.return_code = return_code
        self.message = message or ""
        super().__init__(f"WITSML error {return_code}: {self.message}".rstrip(": "))


def _result_triple(response: Any) -> tuple[int | None, str | None, str | None]:
    """Normalize a WMLS_* compound response to (Result, XMLout, SuppMsgOut).

    zeep may expose the output as attributes on a CompoundValue or as a plain
    tuple/list depending on the binding — support both shapes defensively.
    """
    if isinstance(response, (tuple, list)):
        result = response[0] if len(response) > 0 else None
        xml_out = response[1] if len(response) > 1 else None
        supp = response[2] if len(response) > 2 else None
        return _as_int(result), _as_str(xml_out), _as_str(supp)

    result = getattr(response, "Result", None)
    if result is None:
        result = getattr(response, "result", None)
    xml_out = getattr(response, "XMLout", None)
    if xml_out is None:
        xml_out = getattr(response, "xmlOut", None)
    if xml_out is None:
        # WMLS_GetCap names its output part CapabilitiesOut (not XMLout).
        xml_out = getattr(response, "CapabilitiesOut", None)
    if xml_out is None:
        xml_out = getattr(response, "capabilitiesOut", None)
    supp = getattr(response, "SuppMsgOut", None)
    if supp is None:
        supp = getattr(response, "suppMsgOut", None)
    return _as_int(result), _as_str(xml_out), _as_str(supp)


def _result_pair(response: Any) -> tuple[int | None, str | None]:
    """Normalize an Add/Update/Delete response to (Result, SuppMsgOut)."""
    if isinstance(response, (tuple, list)):
        result = response[0] if len(response) > 0 else None
        supp = response[1] if len(response) > 1 else None
        return _as_int(result), _as_str(supp)
    result = getattr(response, "Result", getattr(response, "result", None))
    supp = getattr(response, "SuppMsgOut", getattr(response, "suppMsgOut", None))
    return _as_int(result), _as_str(supp)


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


class WitsmlClient:
    """Thin async SOAP client for a single WITSML Store endpoint."""

    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        verify_ssl: bool = True,
        wsdl_path: str | None = None,
    ) -> None:
        self._url = url
        self._username = username
        self._password = password
        self._verify_ssl = verify_ssl
        # WSDL location: explicit path wins, else derive from the endpoint URL.
        # Plain concatenation (NOT an f-string) so no '${...}' template leaks in.
        self._wsdl = wsdl_path or (url + "?wsdl")

        self._httpx: httpx.AsyncClient | None = None
        self._zeep: AsyncClient | None = None
        self._lock = asyncio.Lock()

    @classmethod
    def from_settings(cls) -> WitsmlClient:
        return cls(
            url=app_settings.witsml_url,
            username=app_settings.witsml_username,
            password=app_settings.witsml_password,
            verify_ssl=app_settings.witsml_verify_ssl,
            wsdl_path=app_settings.witsml_wsdl_path,
        )

    # ── lazy wiring ─────────────────────────────────────────────────────
    async def _client(self) -> AsyncClient:
        if self._zeep is not None:
            return self._zeep
        async with self._lock:
            if self._zeep is not None:  # double-checked under the lock
                return self._zeep
            self._httpx = httpx.AsyncClient(
                auth=httpx.BasicAuth(self._username, self._password),
                verify=self._verify_ssl,
                timeout=httpx.Timeout(60.0),
            )
            # A sync client is required by zeep for the WSDL fetch; give it the
            # same auth/verify so an http(s)-served WSDL loads too.
            wsdl_client = httpx.Client(
                auth=httpx.BasicAuth(self._username, self._password),
                verify=self._verify_ssl,
                timeout=httpx.Timeout(60.0),
            )
            transport = AsyncTransport(client=self._httpx, wsdl_client=wsdl_client)
            zeep_settings = ZeepSettings(strict=False, xml_huge_tree=True)
            self._zeep = AsyncClient(
                self._wsdl, transport=transport, settings=zeep_settings
            )
        return self._zeep

    async def _service(self) -> Any:
        client = await self._client()
        return client.service

    # ── version / capabilities ──────────────────────────────────────────
    async def get_version(self) -> str:
        service = await self._service()
        response = await service.WMLS_GetVersion()
        # Some bindings wrap the version in a compound result; most return the
        # bare string. Handle both.
        if isinstance(response, str):
            return response
        result = getattr(response, "Result", None)
        return _as_str(result) or _as_str(response) or ""

    async def get_cap(self) -> ServerCap:
        service = await self._service()
        options_in = queries.get_cap_options()  # dataVersion=1.4.1.1 (required)
        response = await service.WMLS_GetCap(OptionsIn=options_in)
        result, xml_out, supp = _result_triple(response)
        if is_error(result):  # type: ignore[arg-type]
            raise await self._error(result, supp)
        return parse_cap(xml_out or "")

    # ── store CRUD ──────────────────────────────────────────────────────
    async def get_from_store(
        self,
        wml_type: str,
        query_xml: str,
        options_in: str = "",
        capabilities_in: str = "",
    ) -> tuple[int, str | None, str | None]:
        service = await self._service()
        response = await service.WMLS_GetFromStore(
            WMLtypeIn=wml_type,
            QueryIn=query_xml,
            OptionsIn=options_in,
            CapabilitiesIn=capabilities_in,
        )
        result, xml_out, supp = _result_triple(response)
        return (result if result is not None else 0), xml_out, supp

    async def add_to_store(
        self, wml_type: str, xml_in: str, options_in: str = ""
    ) -> tuple[int, str | None]:
        service = await self._service()
        response = await service.WMLS_AddToStore(
            WMLtypeIn=wml_type, XMLin=xml_in, OptionsIn=options_in, CapabilitiesIn=""
        )
        result, supp = _result_pair(response)
        return (result if result is not None else 0), supp

    async def update_in_store(
        self, wml_type: str, xml_in: str, options_in: str = ""
    ) -> tuple[int, str | None]:
        service = await self._service()
        response = await service.WMLS_UpdateInStore(
            WMLtypeIn=wml_type, XMLin=xml_in, OptionsIn=options_in, CapabilitiesIn=""
        )
        result, supp = _result_pair(response)
        return (result if result is not None else 0), supp

    async def delete_from_store(
        self, wml_type: str, query_xml: str, options_in: str = ""
    ) -> tuple[int, str | None]:
        service = await self._service()
        response = await service.WMLS_DeleteFromStore(
            WMLtypeIn=wml_type,
            QueryIn=query_xml,
            OptionsIn=options_in,
            CapabilitiesIn="",
        )
        result, supp = _result_pair(response)
        return (result if result is not None else 0), supp

    async def get_base_msg(self, return_code: int) -> str | None:
        service = await self._service()
        try:
            response = await service.WMLS_GetBaseMsg(ReturnValueIn=return_code)
        except Exception:  # noqa: BLE001 — base-msg lookup is best-effort only
            return None
        if isinstance(response, str):
            return response or None
        result = getattr(response, "Result", None)
        return _as_str(result) or _as_str(response)

    # ── log data with +2 truncation loop ────────────────────────────────
    async def get_log_data(
        self,
        *,
        uid_well: str,
        uid_wellbore: str,
        uid: str,
        mnemonics: list[str],
        index_type: IndexType,
        direction: Direction,
        start: float | Any = None,
        end: float | Any = None,
        index_uom: str | None = None,
        max_return_nodes: int | None = None,
    ) -> LogDataResult:
        """Fetch one log's data, resolving +2 truncation into a single block.

        Repeatedly queries data-only from the running continuation index until
        the server reports full success (+1), merging batches with
        polling.merge_blocks. Loops are bounded and stop early when the
        continuation index is None or fails to advance.
        """
        blocks: list[LogDataBlock] = []
        cursor: float | Any = start
        last_index: float | Any = None
        index_type_seen = index_type

        identity_uid = uid
        identity_well = uid_well
        identity_wellbore = uid_wellbore

        for _ in range(_MAX_TRUNCATION_ITERATIONS):
            qbe = queries.log_data_query(
                uid_well,
                uid_wellbore,
                uid,
                mnemonics,
                index_type=index_type,
                start=cursor,
                end=end,
                index_uom=index_uom,
                max_return_nodes=max_return_nodes,
            )
            result, xml_out, supp = await self.get_from_store(
                qbe.wml_type, qbe.query_xml, qbe.options_in
            )
            if is_error(result):
                raise await self._error(result, supp)

            batch = parse_log_data(xml_out or "", index_type=index_type)
            if batch:
                first = batch[0]
                index_type_seen = first.index_type
                identity_uid = first.uid or identity_uid
                identity_well = first.uid_well or identity_well
                identity_wellbore = first.uid_wellbore or identity_wellbore
                blocks.append(first.block)
                next_index = polling.continuation_index(first.block, direction)
            else:
                next_index = None

            # Full success: nothing more to fetch.
            if is_success(result) and not is_truncated(result):
                break

            # Truncated (+2): advance the cursor and re-query. Stop if we can't.
            if not is_truncated(result):
                break
            if next_index is None or next_index == last_index:
                break
            last_index = next_index
            cursor = next_index

        if blocks:
            merged = polling.merge_blocks(blocks)
        else:
            merged = LogDataBlock(
                mnemonics=mnemonics,
                units=[None] * len(mnemonics),
                index_type=index_type_seen,
                rows=[],
            )

        return LogDataResult(
            uid=identity_uid,
            uid_well=identity_well,
            uid_wellbore=identity_wellbore,
            index_type=index_type_seen,
            block=merged,
        )

    # ── errors / teardown ───────────────────────────────────────────────
    async def _error(
        self, return_code: int | None, supp_msg: str | None
    ) -> WitsmlError:
        """Build a WitsmlError, enriching with the server's base message."""
        parts: list[str] = []
        if return_code is not None:
            base = await self.get_base_msg(return_code)
            if base:
                parts.append(base)
        if supp_msg:
            parts.append(supp_msg)
        return WitsmlError(return_code, " | ".join(parts) if parts else None)

    async def aclose(self) -> None:
        if self._httpx is not None:
            await self._httpx.aclose()
            self._httpx = None
        self._zeep = None


# ── module-level cached default client ──────────────────────────────────
_default_client: WitsmlClient | None = None


def get_default_client() -> WitsmlClient:
    """Return a process-wide cached client built from settings (lazy)."""
    global _default_client
    if _default_client is None:
        _default_client = WitsmlClient.from_settings()
    return _default_client


async def close_default_client() -> None:
    """Close and discard the cached default client (e.g. on app shutdown)."""
    global _default_client
    if _default_client is not None:
        await _default_client.aclose()
        _default_client = None
