# ── Feed simulator image ─────────────────────────────────────────────────
# Build context is the repo ROOT so we can reuse the backend's WITSML client
# (the simulator dogfoods the same Add/UpdateToStore code path).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend:/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential libxml2-dev libxslt1-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Reuse backend deps (zeep, lxml, etc.).
COPY backend/pyproject.toml ./backend/pyproject.toml
RUN pip install --upgrade pip && pip install ./backend

COPY backend/app ./backend/app
COPY simulator ./simulator

CMD ["python", "-m", "simulator.feed_simulator"]
