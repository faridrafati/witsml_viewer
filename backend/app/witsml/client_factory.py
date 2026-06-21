"""Convenience re-export of the cached default WITSML client.

The authoritative SOAP gateway lives in ``app.witsml.client``. This thin
module exists so API/ingestion layers can depend on a stable factory import
path without reaching into the client module's internals.
"""

from __future__ import annotations

from app.witsml.client import WitsmlClient, get_default_client

__all__ = ["WitsmlClient", "get_default_client"]
