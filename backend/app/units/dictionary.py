"""Canonical UOM normalization for common mudlogging quantities.

This is a small, *data-driven* lookup that maps the many aliases a WITSML feed
may use for a unit onto a single canonical unit per physical quantity, plus the
linear factor (and optional offset) needed to convert into that canonical unit.

It is intentionally separate from :mod:`app.units.engine`:

* :mod:`engine` evaluates arbitrary operator-entered formulas safely.
* this module holds the *built-in*, hard-coded conversions the app ships with
  so common curves (depth, pressure, density, ...) line up without anyone
  having to type a formula.

Each entry is ``alias -> (canonical_unit, factor, offset)`` meaning::

    canonical_value = raw_value * factor + offset

Aliases are matched case-insensitively after trimming. Canonical units are the
SI-ish / oilfield-conventional choice per quantity:

==============  =========  ===========================================
Quantity        Canonical  Notes
==============  =========  ===========================================
length/depth    m          metres; ft = 0.3048 m
pressure        kPa        psi = 6.894757 kPa, bar = 100 kPa
density         sg         specific gravity (water=1); ppg, pcf, kg/m3
fraction        percent    percent; ppm = percent / 10000
force           N          newton; klbf, lbf, kgf
==============  =========  ===========================================
"""

from __future__ import annotations

from dataclasses import dataclass

# Density conversions into specific gravity (water == 1.0 sg == 1000 kg/m3):
#   ppg  : 1 ppg  = 0.1198264 sg   (US gal)
#   pcf  : 1 sg   = 62.4 pcf  ->  1 pcf = 1/62.4 sg
#   kg/m3: 1 sg   = 1000 kg/m3
_PCF_PER_SG = 62.4
_PPG_PER_SG = 8.345404  # US pounds per gallon of water


@dataclass(frozen=True)
class _Conv:
    """A linear conversion ``canonical = raw * factor + offset``."""

    canonical: str
    factor: float
    offset: float = 0.0


# Per-quantity alias tables. Keys are lowercased; callers normalize the input.
_QUANTITIES: dict[str, dict[str, _Conv]] = {
    "length": {
        "m": _Conv("m", 1.0),
        "meter": _Conv("m", 1.0),
        "metre": _Conv("m", 1.0),
        "ft": _Conv("m", 0.3048),
        "feet": _Conv("m", 0.3048),
        "foot": _Conv("m", 0.3048),
        "in": _Conv("m", 0.0254),
        "inch": _Conv("m", 0.0254),
        "cm": _Conv("m", 0.01),
        "mm": _Conv("m", 0.001),
        "km": _Conv("m", 1000.0),
    },
    "pressure": {
        "kpa": _Conv("kPa", 1.0),
        "pa": _Conv("kPa", 0.001),
        "mpa": _Conv("kPa", 1000.0),
        "psi": _Conv("kPa", 6.894757),
        "bar": _Conv("kPa", 100.0),
        "mbar": _Conv("kPa", 0.1),
        "atm": _Conv("kPa", 101.325),
    },
    "density": {
        "sg": _Conv("sg", 1.0),
        "g/cm3": _Conv("sg", 1.0),
        "g/cc": _Conv("sg", 1.0),
        "ppg": _Conv("sg", 1.0 / _PPG_PER_SG),
        "lb/gal": _Conv("sg", 1.0 / _PPG_PER_SG),
        "pcf": _Conv("sg", 1.0 / _PCF_PER_SG),
        "lb/ft3": _Conv("sg", 1.0 / _PCF_PER_SG),
        "kg/m3": _Conv("sg", 0.001),
    },
    "fraction": {
        "percent": _Conv("percent", 1.0),
        "%": _Conv("percent", 1.0),
        "pct": _Conv("percent", 1.0),
        "fraction": _Conv("percent", 100.0),
        "ppm": _Conv("percent", 1.0 / 10000.0),
        "ppk": _Conv("percent", 0.1),
    },
    "force": {
        "n": _Conv("N", 1.0),
        "newton": _Conv("N", 1.0),
        "kn": _Conv("N", 1000.0),
        "lbf": _Conv("N", 4.4482216),
        "klbf": _Conv("N", 4448.2216),
        "kgf": _Conv("N", 9.80665),
        "dan": _Conv("N", 10.0),
    },
}

# Flat alias -> _Conv index for direct lookups, built once at import time.
_ALIAS_INDEX: dict[str, _Conv] = {
    alias: conv for table in _QUANTITIES.values() for alias, conv in table.items()
}


def _key(uom: str | None) -> str:
    return (uom or "").strip().lower()


def canonical_unit(from_uom: str) -> str | None:
    """Return the canonical unit symbol for ``from_uom``, or ``None``."""
    conv = _ALIAS_INDEX.get(_key(from_uom))
    return conv.canonical if conv else None


def is_known(from_uom: str) -> bool:
    """True if ``from_uom`` is a recognized alias."""
    return _key(from_uom) in _ALIAS_INDEX


def to_canonical(value: float, from_uom: str) -> tuple[float, str]:
    """Convert ``value`` from ``from_uom`` into its canonical unit.

    Returns ``(converted_value, canonical_unit)``. Raises :class:`KeyError`
    if the unit alias is unknown.
    """
    conv = _ALIAS_INDEX.get(_key(from_uom))
    if conv is None:
        raise KeyError(f"unknown unit: {from_uom!r}")
    return value * conv.factor + conv.offset, conv.canonical


def normalize(value: float, from_uom: str, to_canonical: str | None = None) -> float:
    """Normalize ``value`` from ``from_uom`` to a canonical unit.

    If ``to_canonical`` is given it must match the canonical unit that
    ``from_uom`` maps to (a guard against accidentally mixing quantities);
    otherwise the natural canonical unit is used.

    Raises :class:`KeyError` for an unknown ``from_uom`` and :class:`ValueError`
    if ``to_canonical`` disagrees with the alias's canonical unit.
    """
    converted, canon = to_canonical_value(value, from_uom)
    if to_canonical is not None and _key(to_canonical) != canon.lower():
        raise ValueError(f"{from_uom!r} normalizes to {canon!r}, not {to_canonical!r}")
    return converted


# Internal alias kept distinct from the public ``to_canonical`` name so
# ``normalize`` can reuse the (value, unit) tuple form unambiguously.
to_canonical_value = to_canonical
