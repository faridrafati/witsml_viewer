"""Domain objects — the in-memory shapes that flow between layers.

These are deliberately separate from (a) the WITSML XML wire format and
(b) the SQLAlchemy persistence models. The witsml/ layer parses XML *into*
these; the ingestion/api/ws layers pass *these* around; db/ maps these to
tables. Keeping them independent is what makes witsml/ unit-testable in
isolation (see §10 of the brief).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.witsml.constants import Direction, IndexType

# An index value is either a depth (float, with a uom) or a UTC instant.
IndexValue = float | datetime


class Measure(BaseModel):
    """A value with its unit of measure. uom may be None for unitless."""

    value: float
    uom: str | None = None


# ── Well / Wellbore ─────────────────────────────────────────────────────
class Wellbore(BaseModel):
    uid: str
    uid_well: str
    name: str | None = None
    name_well: str | None = None
    status: str | None = None
    parent_uid: str | None = None


class Well(BaseModel):
    uid: str
    name: str | None = None
    region: str | None = None
    field: str | None = None
    country: str | None = None
    operator: str | None = None
    status: str | None = None
    time_zone: str | None = None
    wellbores: list[Wellbore] = Field(default_factory=list)


# ── Log header ──────────────────────────────────────────────────────────
class LogCurveInfo(BaseModel):
    """One channel's header metadata (from a header-only query)."""

    uid: str | None = None
    mnemonic: str
    unit: str | None = None
    curve_description: str | None = None
    null_value: str | None = None
    type_log_data: str | None = None  # double | int | date time | string ...
    # Per-curve index extent (uom-bearing for depth, datetime for time logs).
    min_index: float | None = None
    max_index: float | None = None
    min_datetime_index: datetime | None = None
    max_datetime_index: datetime | None = None


class LogHeader(BaseModel):
    uid: str
    uid_well: str
    uid_wellbore: str
    name: str | None = None
    name_well: str | None = None
    name_wellbore: str | None = None
    index_type: IndexType = IndexType.MEASURED_DEPTH
    index_curve: str | None = None
    direction: Direction = Direction.INCREASING
    object_growing: bool | None = None
    null_value: str | None = None
    index_uom: str | None = None
    # Whole-log extents.
    start_index: float | None = None
    end_index: float | None = None
    start_datetime_index: datetime | None = None
    end_datetime_index: datetime | None = None
    curves: list[LogCurveInfo] = Field(default_factory=list)

    @property
    def mnemonics(self) -> list[str]:
        return [c.mnemonic for c in self.curves]

    def curve(self, mnemonic: str) -> LogCurveInfo | None:
        return next((c for c in self.curves if c.mnemonic == mnemonic), None)


# ── Log data ────────────────────────────────────────────────────────────
class CurveSample(BaseModel):
    """One normalized (null-stripped) reading of a single curve.

    `index` is the row index (depth float or UTC datetime). `value` is the
    numeric reading; string curves keep their text in `text`.
    """

    mnemonic: str
    index: IndexValue
    value: float | None = None
    text: str | None = None
    uom: str | None = None


class LogDataBlock(BaseModel):
    """Parsed `<logData>` — column headers plus row-major decoded values.

    `rows` preserves the raw comma-split cells (already null-stripped to
    None). `samples()` explodes them into per-curve CurveSample streams.
    """

    mnemonics: list[str]
    units: list[str | None]
    index_type: IndexType
    # Cell union keeps float FIRST so numeric indices aren't lax-coerced into
    # datetimes; time-log index cells are genuine datetimes.
    rows: list[list[float | str | datetime | None]] = Field(default_factory=list)

    @property
    def index_mnemonic(self) -> str:
        return self.mnemonics[0]

    def samples(self) -> list[CurveSample]:
        """Flatten to (mnemonic, index, value) samples, skipping nulls."""
        out: list[CurveSample] = []
        for row in self.rows:
            idx = row[0]
            if idx is None:
                continue
            for col, mnem in enumerate(self.mnemonics[1:], start=1):
                val = row[col] if col < len(row) else None
                if val is None:
                    continue
                sample = CurveSample(
                    mnemonic=mnem,
                    index=idx,  # type: ignore[arg-type]
                    uom=self.units[col] if col < len(self.units) else None,
                )
                if isinstance(val, str):
                    sample.text = val
                else:
                    sample.value = float(val)
                out.append(sample)
        return out


# ── mudLog / geology ────────────────────────────────────────────────────
class Lithology(BaseModel):
    uid: str | None = None
    type: str | None = None  # e.g. sandstone, shale, salt
    code_lith: str | None = None
    lith_pc: float | None = None  # percentage of the interval
    description: str | None = None
    color: str | None = None


class GeologyInterval(BaseModel):
    uid: str | None = None
    type_lithology: str | None = None
    md_top: float | None = None
    md_bottom: float | None = None
    md_uom: str | None = None
    lithologies: list[Lithology] = Field(default_factory=list)
    description: str | None = None


class MudLog(BaseModel):
    uid: str
    uid_well: str
    uid_wellbore: str
    name: str | None = None
    name_well: str | None = None
    name_wellbore: str | None = None
    object_growing: bool | None = None
    geology_intervals: list[GeologyInterval] = Field(default_factory=list)
