# ── WITSML 1.4.1.1 mock store image ──────────────────────────────────────
# Build context is the repo ROOT so we can reuse the backend's app.witsml.*
# constants/parse helpers (the mock conforms to the same contracts the client
# and parser enforce).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend:/app \
    MOCK_STORE_PATH=/witsml/store

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential libxml2-dev libxslt1-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Runtime deps for the mock (kept minimal; no zeep needed on the server side).
RUN pip install --upgrade pip \
    && pip install \
        "fastapi" \
        "uvicorn[standard]" \
        "lxml" \
        "pydantic" \
        "pydantic-settings"

# Reuse the backend's app package (app.witsml.* constants/parse) + the mock.
COPY backend/app ./backend/app
COPY mockstore ./mockstore

EXPOSE 7070

HEALTHCHECK --interval=10s --timeout=5s --retries=12 --start-period=10s \
    CMD curl -fsS "http://localhost:7070${MOCK_STORE_PATH}?wsdl" >/dev/null || exit 1

CMD ["uvicorn", "mockstore.server:app", "--host", "0.0.0.0", "--port", "7070"]
