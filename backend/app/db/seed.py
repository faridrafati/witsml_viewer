"""Idempotent seed: parameter catalog, default unit conversions, super-admin.

Run standalone (`python -m app.db.seed`) or imported by the API lifespan.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.auth.security import hash_password
from app.config import settings
from app.db.base import SessionLocal, init_models
from app.db.models import ParameterCatalog, UnitDef, User

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


async def run_seed() -> None:
    await init_models()
    async with SessionLocal() as session:
        params = await seed_parameter_catalog(session)
        units = await seed_unit_defs(session)
        admin = await seed_superadmin(session)
        await session.commit()
    print(
        f"[seed] parameters+={params} unit_defs+={units} "
        f"superadmin={'created' if admin else 'exists'}"
    )


if __name__ == "__main__":
    asyncio.run(run_seed())
