"""SQLAlchemy ORM models — single metadata home.

Core schema for Phase 0/1: server connections, well metadata, parameter
catalog, unit definitions, dashboard pages, users + page grants, the
time-series curve cache, and the ingestion index-cache snapshot. Later
phases (formulas, reporting) add classes to THIS module so `create_all` and
Alembic autogenerate see one metadata object.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ── WITSML server connections ───────────────────────────────────────────
class ServerConnection(Base):
    __tablename__ = "server_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    url: Mapped[str] = mapped_column(String(500))
    username: Mapped[str] = mapped_column(String(200))
    # Fernet-encrypted; never returned to the client in plaintext.
    password_encrypted: Mapped[str] = mapped_column(Text)
    verify_ssl: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cap_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ── Basic Well Information (app-owned metadata, linked by uid) ───────────
class WellMeta(Base):
    __tablename__ = "well_meta"
    __table_args__ = (UniqueConstraint("server_id", "well_uid", name="uq_well_meta"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("server_connections.id"))
    well_uid: Mapped[str] = mapped_column(String(200), index=True)
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    region: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # App-only fields with no direct WITSML home (alias, bit code/IADC, hole
    # sizes, coordinates, RTE/GLE/sea depth, casing/liner, kick-off, ...).
    info: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


# ── Parameter catalog (mnemonic dictionary with WITS-ID cross-ref) ──────
class ParameterCatalog(Base):
    __tablename__ = "parameter_catalog"

    id: Mapped[int] = mapped_column(primary_key=True)
    mnemonic: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    default_unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    wits_id: Mapped[str | None] = mapped_column(String(10), nullable=True)


# ── Unit definitions (formula-based conversion over __value__) ──────────
class UnitDef(Base):
    __tablename__ = "unit_defs"
    __table_args__ = (UniqueConstraint("from_unit", "to_unit", name="uq_unit_conv"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    from_unit: Mapped[str] = mapped_column(String(40))
    to_unit: Mapped[str] = mapped_column(String(40))
    # e.g. "__value__ * 62.4". Evaluated with a SAFE evaluator, never eval().
    expression: Mapped[str] = mapped_column(String(500))
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)


# ── Dashboard pages (dynamic pages with draggable components) ───────────
class DashboardPage(Base):
    __tablename__ = "dashboard_pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    well_uid: Mapped[str | None] = mapped_column(String(200), nullable=True)
    well_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    region: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Full component tree: list of {type, mnemonic(s), root, back_config,
    # comment_config, numerics_config, chart_numeric_config, time_config, ...}
    layout: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


# ── Users + RBAC ────────────────────────────────────────────────────────
ACCESS_LEVELS = ("normal", "admin", "super_admin")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    position: Mapped[str | None] = mapped_column(String(120), nullable=True)
    access_level: Mapped[str] = mapped_column(String(20), default="normal")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    page_grants: Mapped[list[PageGrant]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class PageGrant(Base):
    __tablename__ = "page_grants"
    __table_args__ = (UniqueConstraint("user_id", "page_id", name="uq_page_grant"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    page_id: Mapped[int] = mapped_column(ForeignKey("dashboard_pages.id", ondelete="CASCADE"))
    user: Mapped[User] = relationship(back_populates="page_grants")


# ── Time-series curve cache (Postgres persistence of ingested data) ─────
class CurveSampleRow(Base):
    __tablename__ = "curve_samples"
    __table_args__ = (
        Index("ix_curve_lookup", "well_uid", "mnemonic", "index_float"),
        Index("ix_curve_lookup_dt", "well_uid", "mnemonic", "index_dt"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(Integer, index=True)
    well_uid: Mapped[str] = mapped_column(String(200))
    wellbore_uid: Mapped[str] = mapped_column(String(200))
    log_uid: Mapped[str] = mapped_column(String(200))
    mnemonic: Mapped[str] = mapped_column(String(60))
    index_float: Mapped[float | None] = mapped_column(Float, nullable=True)
    index_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    text: Mapped[str | None] = mapped_column(String(300), nullable=True)
    uom: Mapped[str | None] = mapped_column(String(40), nullable=True)


# ── Ingestion index-cache snapshot (resume without re-pulling history) ──
class IndexCacheSnapshot(Base):
    __tablename__ = "index_cache"
    __table_args__ = (
        UniqueConstraint(
            "server_id",
            "well_uid",
            "wellbore_uid",
            "log_uid",
            "mnemonic",
            name="uq_index_cache",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(Integer, index=True)
    well_uid: Mapped[str] = mapped_column(String(200))
    wellbore_uid: Mapped[str] = mapped_column(String(200))
    log_uid: Mapped[str] = mapped_column(String(200))
    mnemonic: Mapped[str] = mapped_column(String(60))
    last_index_float: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_index_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    uom: Mapped[str | None] = mapped_column(String(40), nullable=True)
    direction: Mapped[str] = mapped_column(String(20), default="increasing")
    index_type: Mapped[str] = mapped_column(String(20), default="measured depth")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


# ── P7 reporting (brief §7.11): daily reports, remarks, mud spec ─────────
class Report(Base):
    """A daily drilling / mudlogging report header.

    Carries the operational context (field, rig, well, hole size, operation
    type, mud system) used to filter and group remarks and mud properties.
    """

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    field: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    rig: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    well_uid: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    hole_size: Mapped[str | None] = mapped_column(String(60), nullable=True)
    operation_type: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    mud_system: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    remarks: Mapped[list[Remark]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    mud_properties: Mapped[list[MudProperty]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )


class Remark(Base):
    """A free-text remark / observation attached to a report.

    `text` and `category` are the searchable fields (keyword substring); the
    optional `time`/`depth` anchor the remark to a moment / position.
    """

    __tablename__ = "remarks"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    depth: Mapped[float | None] = mapped_column(Float, nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)

    report: Mapped[Report] = relationship(back_populates="remarks")


class MudProperty(Base):
    """One row of the drilling-fluid spec table for a report (name/value/unit)."""

    __tablename__ = "mud_properties"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    value: Mapped[str | None] = mapped_column(String(120), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)

    report: Mapped[Report] = relationship(back_populates="mud_properties")


class SavedSearch(Base):
    """A reusable, named search (criteria as opaque JSON) scoped to a module."""

    __tablename__ = "saved_searches"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    module: Mapped[str] = mapped_column(String(60), index=True)
    criteria: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class DepthOfInterest(Base):
    """A user-flagged depth (optionally tied to a report) with a free-text note."""

    __tablename__ = "depths_of_interest"

    id: Mapped[int] = mapped_column(primary_key=True)
    well_uid: Mapped[str] = mapped_column(String(200), index=True)
    report_id: Mapped[int | None] = mapped_column(
        ForeignKey("reports.id", ondelete="SET NULL"), nullable=True
    )
    depth: Mapped[float] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
