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
# Make the app package importable by the uvicorn console script (cwd is not on
# sys.path for console entry points).
ENV PYTHONPATH=/app

# Copy the package + project metadata, then install (editable) so `app` is a
# real importable package AND its dependencies are resolved.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && pip install -e .

# Remaining source / config.
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY tests ./tests

EXPOSE 8000

# Entrypoint runs migrations then serves. See app/entrypoint.sh.
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh
CMD ["./entrypoint.sh"]
