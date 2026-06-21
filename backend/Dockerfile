# ── Backend (FastAPI BFF) image ──────────────────────────────────────────
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# lxml / asyncpg / cryptography build + runtime deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential libxml2-dev libxslt1-dev libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first for layer caching.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

# App source.
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY tests ./tests

EXPOSE 8000

# Entrypoint runs migrations then serves. See app/entrypoint.sh.
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh
CMD ["./entrypoint.sh"]
