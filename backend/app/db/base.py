"""SQLAlchemy 2.x async engine, session factory, and declarative base.

Works against Postgres (compose default) or SQLite (zero-config dev). The
engine is created lazily from `settings.database_url`.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    kwargs: dict = {"echo": False, "future": True}
    if settings.is_sqlite:
        # check_same_thread off + StaticPool keeps an in-memory/file SQLite
        # usable across async tasks.
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20
        kwargs["pool_pre_ping"] = True
    return create_async_engine(settings.database_url, **kwargs)


engine = _make_engine()
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped async session."""
    async with SessionLocal() as session:
        yield session


async def init_models() -> None:
    """Create tables if absent (idempotent). Safe fallback to Alembic."""
    from app.db import models  # noqa: F401  (register metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
