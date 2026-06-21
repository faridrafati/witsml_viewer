"""In-memory, schema-faithful WITSML 1.4.1.1 SOAP mock store.

A self-contained dev/test WITSML Store server that speaks the same SOAP 1.1
document/literal contract the project's real zeep client expects. Replaces the
Drillflow container as the default `docker compose up` test server.

Public surface:
  * :mod:`mockstore.store`  — the in-memory store (CRUD + QBE GetFromStore).
  * :mod:`mockstore.server` — the FastAPI SOAP endpoint (`app`).
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.4.1.1"
