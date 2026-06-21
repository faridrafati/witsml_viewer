"""Idempotent seed: parameter catalog, default unit conversions, super-admin.

Run standalone (`python -m app.db.seed`) or imported by the API lifespan.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

from sqlalchemy import select

from app.auth.security import hash_password
from app.config import settings
from app.db.base import SessionLocal, init_models
from app.db.models import (
    MudProperty,
    ParameterCatalog,
    Remark,
    Report,
    UnitDef,
    User,
)

# ── Mudlogging parameter catalog (brief §7.6) ──────────────────────────
# (mnemonic, description, default_unit, WITS Level-0 id)
PARAMETER_CATALOG: list[tuple[str, str, str, str | None]] = [
    ("DEPTH", "Bit depth (measured)", "m", "0108"),
    ("ROP", "Rate of penetration", "m/h", "0113"),
    ("WOB", "Weight on bit", "klbf", "0116"),
    ("RPM", "Rotary speed", "rpm", "0114"),
    ("TORQUE", "Torque", "kN.m", None),
    ("SPP", "Standpipe pressure", "kPa", None),
    ("FLOWIN", "Mud flow in", "L/min", None),
    ("HOOKLOAD", "Hookload", "klbf", "0114"),
    ("TOTGAS", "Total gas", "%", "0140"),
    ("C1", "Methane (chromatograph)", "ppm", None),
    ("C2", "Ethane (chromatograph)", "ppm", None),
    ("C3", "Propane (chromatograph)", "ppm", None),
    ("C4", "Butane (chromatograph)", "ppm", None),
    ("C5", "Pentane (chromatograph)", "ppm", None),
    ("MW", "Mud weight / density", "sg", None),
    ("TIME", "Time index", "s", None),
]

# ── Default unit conversions (expression over __value__; SAFE eval) ─────
# (name, from_unit, to_unit, expression)
DEFAULT_UNIT_DEFS: list[tuple[str, str, str, str]] = [
    ("Specific gravity to pounds per cubic foot", "sg", "pcf", "__value__ * 62.4"),
    ("Pounds per cubic foot to pounds per gallon", "pcf", "ppg", "__value__ / 7.48"),
    ("Specific gravity to pounds per gallon", "sg", "ppg", "__value__ * 8.345"),
    ("Percent to parts per million", "percent", "ppm", "__value__ * 10000"),
    ("Parts per million to percent", "ppm", "percent", "__value__ / 10000"),
    ("Metres to feet", "m", "ft", "__value__ * 3.280839895"),
    ("Feet to metres", "ft", "m", "__value__ / 3.280839895"),
    ("Kilopascal to psi", "kPa", "psi", "__value__ * 0.1450377"),
    ("psi to Kilopascal", "psi", "kPa", "__value__ / 0.1450377"),
    ("Identity", "__value__", "__value__", "__value__"),
]


async def seed_parameter_catalog(session) -> int:
    existing = {row[0] for row in (await session.execute(select(ParameterCatalog.mnemonic))).all()}
    added = 0
    for mnemonic, desc, unit, wits in PARAMETER_CATALOG:
        if mnemonic in existing:
            continue
        session.add(
            ParameterCatalog(mnemonic=mnemonic, description=desc, default_unit=unit, wits_id=wits)
        )
        added += 1
    return added


async def seed_unit_defs(session) -> int:
    existing = {
        (r[0], r[1])
        for r in (await session.execute(select(UnitDef.from_unit, UnitDef.to_unit))).all()
    }
    added = 0
    for name, frm, to, expr in DEFAULT_UNIT_DEFS:
        if (frm, to) in existing:
            continue
        session.add(UnitDef(name=name, from_unit=frm, to_unit=to, expression=expr, is_builtin=True))
        added += 1
    return added


async def seed_superadmin(session) -> bool:
    existing = (
        await session.execute(select(User).where(User.username == settings.superadmin_username))
    ).scalar_one_or_none()
    if existing:
        return False
    session.add(
        User(
            username=settings.superadmin_username,
            password_hash=hash_password(settings.superadmin_password),
            first_name="Super",
            last_name="Admin",
            access_level="super_admin",
        )
    )
    return True


# ── Sample reporting data (brief §7.11) ────────────────────────────────
# Each entry: report header + remarks (keyword-rich) + mud-property rows.
SAMPLE_REPORTS: list[dict] = [
    {
        "report_date": date(2026, 6, 18),
        "field": "North Sea Alpha",
        "rig": "Ocean Titan",
        "well_uid": "W-1001",
        "hole_size": "12 1/4 in",
        "operation_type": "Drilling",
        "mud_system": "Water-Based Mud",
        "remarks": [
            (
                datetime(2026, 6, 18, 4, 30, tzinfo=UTC),
                2450.0,
                "Hazard",
                "Observed partial lost circulation while drilling shale; pumped LCM pill.",
            ),
            (
                datetime(2026, 6, 18, 9, 15, tzinfo=UTC),
                2510.0,
                "Operations",
                "Connection made up, circulated bottoms up, no gas show.",
            ),
        ],
        "mud_properties": [
            ("Mud Weight", "1.25", "sg"),
            ("Funnel Viscosity", "48", "s/qt"),
            ("Plastic Viscosity", "18", "cP"),
            ("Yield Point", "22", "lbf/100ft2"),
            ("pH", "9.5", None),
        ],
    },
    {
        "report_date": date(2026, 6, 19),
        "field": "North Sea Alpha",
        "rig": "Ocean Titan",
        "well_uid": "W-1001",
        "hole_size": "8 1/2 in",
        "operation_type": "Tripping",
        "mud_system": "Oil-Based Mud",
        "remarks": [
            (
                datetime(2026, 6, 19, 2, 0, tzinfo=UTC),
                3120.0,
                "Hazard",
                "Stuck pipe event during trip out; worked string free after 40 min.",
            ),
            (
                datetime(2026, 6, 19, 6, 45, tzinfo=UTC),
                3120.0,
                "Operations",
                "Resumed POOH, no further overpull, racking stands.",
            ),
        ],
        "mud_properties": [
            ("Mud Weight", "1.42", "sg"),
            ("Funnel Viscosity", "55", "s/qt"),
            ("Oil/Water Ratio", "80/20", None),
            ("Electrical Stability", "420", "V"),
        ],
    },
    {
        "report_date": date(2026, 6, 20),
        "field": "Caspian Bravo",
        "rig": "Desert Falcon",
        "well_uid": "W-2002",
        "hole_size": "17 1/2 in",
        "operation_type": "Cementing",
        "mud_system": "Water-Based Mud",
        "remarks": [
            (
                datetime(2026, 6, 20, 11, 0, tzinfo=UTC),
                1980.0,
                "Operations",
                "Cement job on surface casing completed, returns to surface observed.",
            ),
            (
                datetime(2026, 6, 20, 14, 30, tzinfo=UTC),
                1980.0,
                "Hazard",
                "Minor lost circulation during displacement; managed with low pump rate.",
            ),
        ],
        "mud_properties": [
            ("Mud Weight", "1.15", "sg"),
            ("Funnel Viscosity", "42", "s/qt"),
            ("Filtrate (API)", "6.5", "mL/30min"),
            ("pH", "10.1", None),
        ],
    },
]


async def seed_reporting(session) -> int:
    """Insert sample reports + remarks + mud properties, idempotently.

    Skips entirely if any Report already exists, so re-running the seed does
    not duplicate sample data.
    """
    existing = (await session.execute(select(Report.id).limit(1))).first()
    if existing is not None:
        return 0
    added = 0
    for spec in SAMPLE_REPORTS:
        report = Report(
            report_date=spec["report_date"],
            field=spec["field"],
            rig=spec["rig"],
            well_uid=spec["well_uid"],
            hole_size=spec["hole_size"],
            operation_type=spec["operation_type"],
            mud_system=spec["mud_system"],
        )
        report.remarks = [
            Remark(time=t, depth=d, category=cat, text=txt) for (t, d, cat, txt) in spec["remarks"]
        ]
        report.mud_properties = [
            MudProperty(name=n, value=v, unit=u) for (n, v, u) in spec["mud_properties"]
        ]
        session.add(report)
        added += 1
    return added


async def run_seed() -> None:
    await init_models()
    async with SessionLocal() as session:
        params = await seed_parameter_catalog(session)
        units = await seed_unit_defs(session)
        admin = await seed_superadmin(session)
        reports = await seed_reporting(session)
        await session.commit()
    print(
        f"[seed] parameters+={params} unit_defs+={units} "
        f"superadmin={'created' if admin else 'exists'} reports+={reports}"
    )


if __name__ == "__main__":
    asyncio.run(run_seed())
