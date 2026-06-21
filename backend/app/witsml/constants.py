"""WITSML 1.4.1.1 protocol constants.

Hard facts about the wire format, gathered in one place so the client,
query builders, and parsers never disagree. Where this module and the
WITSML 1.4.1.1 schema differ, the schema wins — fix it here.
"""

from __future__ import annotations

from enum import Enum

# ── Namespaces ──────────────────────────────────────────────────────────
WITSML_VERSION = "1.4.1.1"
#: Data objects (well, wellbore, log, mudLog, ...).
NS_DATA = "http://www.witsml.org/schemas/1series"
#: Store/capabilities API objects (capClients/capServer).
NS_API = "http://www.witsml.org/api/141"

#: lxml-style nsmap helpers.
NSMAP_DATA = {None: NS_DATA}
NSMAP_API = {None: NS_API}


def q_data(tag: str) -> str:
    """Clark-notation qualified name in the data namespace."""
    return f"{{{NS_DATA}}}{tag}"


def q_api(tag: str) -> str:
    """Clark-notation qualified name in the API namespace."""
    return f"{{{NS_API}}}{tag}"


# ── SOAPAction header values (Store binding) ────────────────────────────
# Many servers key dispatch off SOAPAction. zeep normally derives these from
# the WSDL; kept here for the raw-XML smoke test and as documentation.
SOAP_ACTION_BASE = "http://www.witsml.org/action/120/Store."
SOAP_ACTIONS = {
    "WMLS_GetVersion": SOAP_ACTION_BASE + "WMLS_GetVersion",
    "WMLS_GetCap": SOAP_ACTION_BASE + "WMLS_GetCap",
    "WMLS_GetFromStore": SOAP_ACTION_BASE + "WMLS_GetFromStore",
    "WMLS_AddToStore": SOAP_ACTION_BASE + "WMLS_AddToStore",
    "WMLS_UpdateInStore": SOAP_ACTION_BASE + "WMLS_UpdateInStore",
    "WMLS_DeleteFromStore": SOAP_ACTION_BASE + "WMLS_DeleteFromStore",
    "WMLS_GetBaseMsg": SOAP_ACTION_BASE + "WMLS_GetBaseMsg",
}


# ── OptionsIn keys (passed as "k1=v1;k2=v2") ────────────────────────────
class ReturnElements(str, Enum):
    ALL = "all"
    ID_ONLY = "id-only"
    HEADER_ONLY = "header-only"
    DATA_ONLY = "data-only"
    STATION_LOCATION_ONLY = "station-location-only"
    LATEST_CHANGE_ONLY = "latest-change-only"
    REQUESTED = "requested"


class IntervalRangeInclusion(str, Enum):
    """mudLog-only OptionsIn. `any-part` keeps boundary-straddling intervals."""

    MINIMUM_POINT = "minimum-point"
    WHOLE_INTERVAL = "whole-interval"
    ANY_PART = "any-part"


# OptionsIn parameter names.
OPT_RETURN_ELEMENTS = "returnElements"
OPT_MAX_RETURN_NODES = "maxReturnNodes"
OPT_REQUEST_LATEST_VALUES = "requestLatestValues"
OPT_INTERVAL_RANGE_INCLUSION = "intervalRangeInclusion"
OPT_COMPRESSION_METHOD = "compressionMethod"
OPT_DATA_VERSION = "dataVersion"  # REQUIRED for WMLS_GetCap


def options_in(**kwargs: object) -> str:
    """Build an OptionsIn string, dropping None values.

    >>> options_in(returnElements="data-only", maxReturnNodes=1000)
    'returnElements=data-only;maxReturnNodes=1000'
    """
    parts = []
    for key, value in kwargs.items():
        if value is None:
            continue
        if isinstance(value, Enum):
            value = value.value
        if isinstance(value, bool):
            value = "true" if value else "false"
        parts.append(f"{key}={value}")
    return ";".join(parts)


# ── Return codes ────────────────────────────────────────────────────────
# Positive = success; negative = error (NO valid XMLout on result <= 0).
RC_SUCCESS = 1  # +1 : full success.
RC_PARTIAL_SUCCESS = 2  # +2 : success but growing-object result TRUNCATED;
#      re-query from the new max index until +1.


def is_success(result: int) -> bool:
    return result is not None and result > 0


def is_truncated(result: int) -> bool:
    """Result indicates more data exists for a growing object."""
    return result == RC_PARTIAL_SUCCESS


def is_error(result: int) -> bool:
    return result is None or result <= 0


# ── Index types & direction ─────────────────────────────────────────────
class IndexType(str, Enum):
    DATE_TIME = "date time"
    ELAPSED_TIME = "elapsed time"
    MEASURED_DEPTH = "measured depth"
    VERTICAL_DEPTH = "vertical depth"
    OTHER = "other"

    @property
    def is_time(self) -> bool:
        return self in (IndexType.DATE_TIME, IndexType.ELAPSED_TIME)

    @property
    def is_depth(self) -> bool:
        return self in (IndexType.MEASURED_DEPTH, IndexType.VERTICAL_DEPTH)


class Direction(str, Enum):
    INCREASING = "increasing"
    DECREASING = "decreasing"


# ── Null sentinels ──────────────────────────────────────────────────────
# Curve-level nullValue overrides log-level; empty string is ALWAYS null.
DEFAULT_NULL_VALUE = "-999.25"
# Extra sentinels seen in the wild that we treat as null regardless of decl.
COMMON_NULL_SENTINELS = {"-999.25", "-9999", "-999", "NaN", "null", ""}
