"""Perpetual WITSML 1.4.1.1 feed simulator (test rig).

This module dogfoods the backend's authoritative ``WitsmlClient`` SOAP gateway
(``app.witsml.client``) via ``WMLS_AddToStore`` / ``WMLS_UpdateInStore``. It
seeds a small fleet of wells/wellbores/logs/mudLogs into the store and then
appends a fresh data row to every log on a fixed cadence so the rest of the
stack (poller, +2 truncation path, websocket fan-out, frontend charts) always
has live, smoothly-evolving data to consume.

Run as a module (see ``simulator/Dockerfile``)::

    python -m simulator.feed_simulator

PYTHONPATH includes ``backend/`` so ``app.*`` imports resolve.

Brief §9 behaviour implemented here:
  * Startup: create ``settings.simulated_well_count`` wells, 1 wellbore each.
  * Per wellbore: a TIME log + a DEPTH log (~10 mudlogging curves each, index
    curve FIRST), plus a mudLog with a couple of geology/lithology rows.
  * One well's DEPTH log is ``direction=decreasing`` (pulling-out variant).
  * Every ``settings.poll_interval_seconds`` (5s default): append ONE new row
    to every log via UpdateInStore.
  * An occasional null (-999.25) is injected on a non-index curve.
  * Periodically (~every 12 ticks) one well gets a BURST of many rows in a
    single update so a small ``maxReturnNodes`` reader exercises the +2 path.

XML is built with lxml directly, reusing ``app.witsml.constants`` for the data
namespace. Timestamps are UTC ISO-8601 with millisecond precision and a ``Z``
suffix.

Robustness: AddToStore "already exists" is treated as success (idempotent-ish
startup); transient WITSML errors are logged and the loop keeps running.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime

from lxml import etree

from app.config import settings
from app.witsml.client import WitsmlClient
from app.witsml.constants import (
    DEFAULT_NULL_VALUE,
    NS_DATA,
    WITSML_VERSION,
    Direction,
    IndexType,
    is_success,
    q_data,
)

logger = logging.getLogger("feed_simulator")

# ── Tunables ─────────────────────────────────────────────────────────────
NULL_VALUE = DEFAULT_NULL_VALUE  # "-999.25"
NULL_INJECT_PROB = 0.03  # chance a single non-index cell is nulled
BURST_EVERY_TICKS = 12  # push a multi-row burst this often
BURST_ROWS = 250  # rows in a burst (> typical maxReturnNodes)
DEPTH_STEP_M = 0.5  # nominal depth increment per depth-log row


# ── Curve catalog ────────────────────────────────────────────────────────
# (mnemonic, unit, description). The index curve is listed FIRST per log so
# every consumer can rely on position 0 being the index. Units match the
# mudlogging catalog the backend expects.
@dataclass(frozen=True)
class Curve:
    mnemonic: str
    unit: str
    description: str


TIME_INDEX = Curve("TIME", "s", "Date time index")
DEPTH_INDEX = Curve("DEPTH", "m", "Measured depth index")

# TIME log: TIME index + DEPTH,ROP,WOB,RPM,TORQUE,SPP,FLOWIN,HOOKLOAD,TOTGAS,C1
TIME_CURVES: list[Curve] = [
    TIME_INDEX,
    Curve("DEPTH", "m", "Measured depth"),
    Curve("ROP", "m/h", "Rate of penetration"),
    Curve("WOB", "klbf", "Weight on bit"),
    Curve("RPM", "rpm", "Rotary speed"),
    Curve("TORQUE", "kN.m", "Surface torque"),
    Curve("SPP", "kPa", "Standpipe pressure"),
    Curve("FLOWIN", "L/min", "Flow in"),
    Curve("HOOKLOAD", "klbf", "Hookload"),
    Curve("TOTGAS", "%", "Total gas"),
    Curve("C1", "ppm", "Methane"),
]

# DEPTH log: DEPTH index + ROP,WOB,RPM,TORQUE,TOTGAS,C1,C2,C3,C4
DEPTH_CURVES: list[Curve] = [
    DEPTH_INDEX,
    Curve("ROP", "m/h", "Rate of penetration"),
    Curve("WOB", "klbf", "Weight on bit"),
    Curve("RPM", "rpm", "Rotary speed"),
    Curve("TORQUE", "kN.m", "Surface torque"),
    Curve("TOTGAS", "%", "Total gas"),
    Curve("C1", "ppm", "Methane"),
    Curve("C2", "ppm", "Ethane"),
    Curve("C3", "ppm", "Propane"),
    Curve("C4", "ppm", "Butane"),
]


# ── Timestamp helpers ────────────────────────────────────────────────────
def iso_utc(dt: datetime) -> str:
    """UTC ISO-8601 with millisecond precision and a Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_num(value: float) -> str:
    """Compact numeric rendering (clean integers, trimmed floats)."""
    if value != value:  # NaN guard
        return NULL_VALUE
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.3f}".rstrip("0").rstrip(".")


# ── Physical signal model ────────────────────────────────────────────────
@dataclass
class LogState:
    """Mutable evolving state for one log within one wellbore."""

    wml_uid: str
    name: str
    index_type: IndexType
    direction: Direction
    curves: list[Curve]
    # evolving channels
    depth: float = 1500.0
    last_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    phase: float = field(default_factory=lambda: random.uniform(0, math.tau))
    rows_written: int = 0

    @property
    def is_time(self) -> bool:
        return self.index_type.is_time

    @property
    def mnemonics(self) -> list[str]:
        return [c.mnemonic for c in self.curves]

    @property
    def units(self) -> list[str]:
        return [c.unit for c in self.curves]


@dataclass
class WellboreState:
    uid_well: str
    name_well: str
    uid_wellbore: str
    name_wellbore: str
    time_log: LogState
    depth_log: LogState
    mudlog_uid: str
    mudlog_name: str
    mudlog_md: float = 1500.0  # running bottom for mudLog geology growth

    @property
    def logs(self) -> list[LogState]:
        return [self.time_log, self.depth_log]


def _channel_value(curve: Curve, state: LogState, t: float) -> float:
    """Smoothly-evolving, physically-plausible value for a channel.

    ``t`` is a slowly advancing phase so successive rows trend rather than
    jump. Ranges per the brief: gas 0-5%, WOB klbf, RPM ~120, SPP kPa, etc.
    """
    wobble = math.sin(t + state.phase)
    m = curve.mnemonic
    if m == "DEPTH":
        return state.depth
    if m == "ROP":
        return max(2.0, 18.0 + 6.0 * wobble + random.uniform(-1.5, 1.5))
    if m == "WOB":
        return max(
            0.0, 25.0 + 8.0 * math.sin(t * 0.7 + state.phase) + random.uniform(-2, 2)
        )
    if m == "RPM":
        return max(0.0, 120.0 + 15.0 * wobble + random.uniform(-4, 4))
    if m == "TORQUE":
        return max(0.0, 12.0 + 4.0 * wobble + random.uniform(-1, 1))
    if m == "SPP":
        return max(0.0, 21000.0 + 2500.0 * wobble + random.uniform(-300, 300))
    if m == "FLOWIN":
        return max(0.0, 2200.0 + 200.0 * wobble + random.uniform(-50, 50))
    if m == "HOOKLOAD":
        return max(
            0.0, 210.0 + 20.0 * math.sin(t * 0.5 + state.phase) + random.uniform(-5, 5)
        )
    if m == "TOTGAS":
        # 0-5 % with occasional kicks.
        base = 1.2 + 1.4 * (math.sin(t * 0.3 + state.phase) + 1)
        return min(5.0, max(0.0, base + random.uniform(-0.3, 0.5)))
    if m == "C1":
        return max(0.0, 4500.0 + 1500.0 * wobble + random.uniform(-300, 300))
    if m == "C2":
        return max(0.0, 900.0 + 300.0 * wobble + random.uniform(-80, 80))
    if m == "C3":
        return max(0.0, 350.0 + 120.0 * wobble + random.uniform(-40, 40))
    if m == "C4":
        return max(0.0, 120.0 + 50.0 * wobble + random.uniform(-20, 20))
    # Unknown channel — keep it benign.
    return 0.0


def _advance(state: LogState) -> None:
    """Advance the evolving index/depth before emitting a row."""
    rop = max(2.0, 18.0 + 6.0 * math.sin(state.rows_written * 0.05 + state.phase))
    if state.index_type.is_depth:
        # Depth index marches with growth direction.
        step = DEPTH_STEP_M
        if state.direction is Direction.DECREASING:
            state.depth = max(0.0, state.depth - step)
        else:
            state.depth += step
    else:
        # Time index advances; depth channel still drills ahead with ROP.
        dt_seconds = max(0.5, settings.poll_interval_seconds)
        state.last_time = datetime.now(UTC)
        state.depth += rop * (dt_seconds / 3600.0)


def _emit_row(state: LogState, *, allow_null: bool = True) -> tuple[str, list[str]]:
    """Produce (index_token, [channel tokens]) for one new row.

    The returned ``index_token`` is the ISO timestamp (time log) or the depth
    string (depth log); the channel list lines up with ``state.curves[1:]``.
    """
    _advance(state)
    t = state.rows_written * 0.05

    if state.is_time:
        index_token = iso_utc(state.last_time)
    else:
        index_token = fmt_num(state.depth)

    cells: list[str] = []
    for curve in state.curves[1:]:
        if allow_null and random.random() < NULL_INJECT_PROB:
            cells.append(NULL_VALUE)
            continue
        cells.append(fmt_num(_channel_value(curve, state, t)))

    state.rows_written += 1
    return index_token, cells


def _row_csv(index_token: str, cells: list[str]) -> str:
    return ",".join([index_token, *cells])


# ── XML builders (lxml, data namespace) ──────────────────────────────────
def _root(plural: str) -> etree._Element:
    return etree.Element(q_data(plural), nsmap={None: NS_DATA}, version=WITSML_VERSION)


def _sub(
    parent: etree._Element, tag: str, text: str | None = None, **attrib: str
) -> etree._Element:
    el = etree.SubElement(parent, q_data(tag), **attrib)
    if text is not None:
        el.text = text
    return el


def _serialize(root: etree._Element) -> str:
    return etree.tostring(root, encoding="unicode")


def well_xml(uid: str, name: str) -> str:
    root = _root("wells")
    well = _sub(root, "well", uid=uid)
    _sub(well, "name", name)
    _sub(well, "field", "Simulated Field")
    _sub(well, "country", "US")
    _sub(well, "operator", "Simulator")
    _sub(well, "statusWell", "drilling")
    _sub(well, "timeZone", "+00:00")
    return _serialize(root)


def wellbore_xml(uid_well: str, name_well: str, uid: str, name: str) -> str:
    root = _root("wellbores")
    wb = _sub(root, "wellbore", uidWell=uid_well, uid=uid)
    _sub(wb, "nameWell", name_well)
    _sub(wb, "name", name)
    _sub(wb, "statusWellbore", "drilling")
    return _serialize(root)


def _log_curve_info(log: etree._Element, state: LogState) -> None:
    """Append <logCurveInfo> for every curve, index curve first."""
    for i, curve in enumerate(state.curves):
        lci = _sub(log, "logCurveInfo", uid=f"lci-{curve.mnemonic}")
        _sub(lci, "mnemonic", curve.mnemonic)
        _sub(lci, "unit", curve.unit)
        _sub(lci, "curveDescription", curve.description)
        _sub(
            lci, "typeLogData", "date time" if (i == 0 and state.is_time) else "double"
        )
        _sub(lci, "nullValue", NULL_VALUE)


def log_create_xml(
    wb: WellboreState, state: LogState, first_row: tuple[str, list[str]]
) -> str:
    """Full <log> for AddToStore, carrying the header + the seed data row."""
    root = _root("logs")
    log = _sub(
        root, "log", uidWell=wb.uid_well, uidWellbore=wb.uid_wellbore, uid=state.wml_uid
    )
    _sub(log, "nameWell", wb.name_well)
    _sub(log, "nameWellbore", wb.name_wellbore)
    _sub(log, "name", state.name)
    _sub(log, "indexType", state.index_type.value)
    _sub(log, "indexCurve", state.curves[0].mnemonic)
    _sub(log, "direction", state.direction.value)
    _sub(log, "nullValue", NULL_VALUE)

    index_token, cells = first_row
    if state.is_time:
        _sub(log, "startDateTimeIndex", index_token)
        _sub(log, "endDateTimeIndex", index_token)
    else:
        _sub(log, "startIndex", index_token, uom=state.curves[0].unit)
        _sub(log, "endIndex", index_token, uom=state.curves[0].unit)

    _log_curve_info(log, state)

    log_data = _sub(log, "logData")
    _sub(log_data, "mnemonicList", ",".join(state.mnemonics))
    _sub(log_data, "unitList", ",".join(state.units))
    _sub(log_data, "data", _row_csv(index_token, cells))
    return _serialize(root)


def log_update_xml(
    wb: WellboreState, state: LogState, rows: list[tuple[str, list[str]]]
) -> str:
    """Minimal <log> for UpdateInStore appending one-or-more data rows.

    Carries identity + the SAME mnemonicList/unitList as the header so the
    server can align the appended <data> rows.
    """
    root = _root("logs")
    log = _sub(
        root, "log", uidWell=wb.uid_well, uidWellbore=wb.uid_wellbore, uid=state.wml_uid
    )
    log_data = _sub(log, "logData")
    _sub(log_data, "mnemonicList", ",".join(state.mnemonics))
    _sub(log_data, "unitList", ",".join(state.units))
    for index_token, cells in rows:
        _sub(log_data, "data", _row_csv(index_token, cells))
    return _serialize(root)


# ── mudLog ────────────────────────────────────────────────────────────────
_LITHO_DECK = [
    ("sandstone", "SND", "Sandstone, fine-medium grained"),
    ("shale", "SHL", "Shale, grey, firm"),
    ("salt", "SLT", "Salt, halite, clear"),
]


def mudlog_create_xml(wb: WellboreState) -> str:
    """mudLog with a couple of geologyInterval/lithology rows (lithPc)."""
    root = _root("mudLogs")
    ml = _sub(
        root,
        "mudLog",
        uidWell=wb.uid_well,
        uidWellbore=wb.uid_wellbore,
        uid=wb.mudlog_uid,
    )
    _sub(ml, "nameWell", wb.name_well)
    _sub(ml, "nameWellbore", wb.name_wellbore)
    _sub(ml, "name", wb.mudlog_name)
    _sub(ml, "mudLogCompany", "Simulator")

    top = wb.mudlog_md
    # Interval 1: sandstone-dominated with subordinate shale.
    _geology_interval(
        ml,
        uid="gi-1",
        md_top=top,
        md_bottom=top + 25.0,
        primary=("sandstone", "SND", 70.0, "Sandstone, fine-medium, good porosity"),
        secondary=("shale", "SHL", 30.0, "Shale, grey interbeds"),
    )
    # Interval 2: shale with a salt stringer.
    _geology_interval(
        ml,
        uid="gi-2",
        md_top=top + 25.0,
        md_bottom=top + 60.0,
        primary=("shale", "SHL", 80.0, "Shale, dark grey, calcareous"),
        secondary=("salt", "SLT", 20.0, "Salt stringer, halite"),
    )
    return _serialize(root)


def _geology_interval(
    ml: etree._Element,
    *,
    uid: str,
    md_top: float,
    md_bottom: float,
    primary: tuple[str, str, float, str],
    secondary: tuple[str, str, float, str],
) -> None:
    gi = _sub(ml, "geologyInterval", uid=uid)
    _sub(gi, "typeLithology", "cuttings")
    _sub(gi, "mdTop", fmt_num(md_top), uom="m")
    _sub(gi, "mdBottom", fmt_num(md_bottom), uom="m")
    _sub(gi, "description", f"{primary[0]} / {secondary[0]}")
    for i, (ltype, code, pc, desc) in enumerate((primary, secondary)):
        lith = _sub(gi, "lithology", uid=f"{uid}-l{i + 1}")
        _sub(lith, "type", ltype)
        _sub(lith, "codeLith", code)
        _sub(lith, "lithPc", fmt_num(pc), uom="%")
        _sub(lith, "description", desc)


# ── Fleet construction ────────────────────────────────────────────────────
def build_fleet(count: int) -> list[WellboreState]:
    fleet: list[WellboreState] = []
    for i in range(1, count + 1):
        uid_well = f"sim-well-{i:03d}"
        name_well = f"Simulated Well {i:03d}"
        uid_wellbore = f"{uid_well}-wb-1"
        name_wellbore = "Wellbore 1"

        # One well gets a decreasing depth log (pulling-out variant).
        depth_direction = Direction.DECREASING if i == 1 else Direction.INCREASING

        start_depth = 1500.0 + random.uniform(-200, 200)
        time_log = LogState(
            wml_uid=f"{uid_wellbore}-log-time",
            name="Time Log",
            index_type=IndexType.DATE_TIME,
            direction=Direction.INCREASING,
            curves=TIME_CURVES,
            depth=start_depth,
        )
        depth_log = LogState(
            wml_uid=f"{uid_wellbore}-log-depth",
            name="Depth Log",
            index_type=IndexType.MEASURED_DEPTH,
            direction=depth_direction,
            curves=DEPTH_CURVES,
            depth=start_depth,
        )
        fleet.append(
            WellboreState(
                uid_well=uid_well,
                name_well=name_well,
                uid_wellbore=uid_wellbore,
                name_wellbore=name_wellbore,
                time_log=time_log,
                depth_log=depth_log,
                mudlog_uid=f"{uid_wellbore}-mudlog-1",
                mudlog_name="Geology MudLog",
                mudlog_md=start_depth,
            )
        )
    return fleet


# ── Store interaction (idempotent-ish, robust) ────────────────────────────
def _already_exists(supp_msg: str | None) -> bool:
    if not supp_msg:
        return False
    msg = supp_msg.lower()
    return (
        "already exist" in msg
        or "already in the store" in msg
        or "uid_already_exists" in msg
    )


def _not_found(rc: int | None, supp_msg: str | None) -> bool:
    """A growing object vanished — the in-memory store was reset/restarted."""
    if rc == -411:  # WITSML: query did not match an object in the store
        return True
    return bool(supp_msg and "not found" in supp_msg.lower())


async def _add(client: WitsmlClient, wml_type: str, xml: str, what: str) -> bool:
    """AddToStore one object. Returns True on success or already-exists."""
    try:
        rc, supp = await client.add_to_store(wml_type, xml)
    except Exception:  # network/zeep faults — keep the rig alive
        logger.exception("AddToStore raised for %s", what)
        return False
    if is_success(rc):
        logger.info("created %s (rc=%s)", what, rc)
        return True
    if _already_exists(supp):
        logger.info("%s already exists — continuing", what)
        return True
    logger.error("AddToStore failed for %s rc=%s supp=%s", what, rc, supp)
    return False


async def seed_fleet(client: WitsmlClient, fleet: list[WellboreState]) -> None:
    """Create wells, wellbores, logs and mudLogs (idempotent-ish)."""
    for wb in fleet:
        await _add(
            client, "well", well_xml(wb.uid_well, wb.name_well), f"well {wb.uid_well}"
        )
        await _add(
            client,
            "wellbore",
            wellbore_xml(wb.uid_well, wb.name_well, wb.uid_wellbore, wb.name_wellbore),
            f"wellbore {wb.uid_wellbore}",
        )
        for state in wb.logs:
            first_row = _emit_row(state, allow_null=False)  # seed row is clean
            await _add(
                client,
                "log",
                log_create_xml(wb, state, first_row),
                f"log {state.wml_uid}",
            )
        await _add(client, "mudLog", mudlog_create_xml(wb), f"mudLog {wb.mudlog_uid}")


async def _update_log(
    client: WitsmlClient,
    wb: WellboreState,
    state: LogState,
    rows: list[tuple[str, list[str]]],
) -> bool:
    """Append rows to a growing log. Returns True if the log was MISSING
    (the in-memory store was reset) so the caller can re-seed the fleet.
    """
    try:
        rc, supp = await client.update_in_store("log", log_update_xml(wb, state, rows))
    except Exception:
        logger.exception("UpdateInStore raised for log %s", state.wml_uid)
        return False
    if is_success(rc):
        return False
    if _not_found(rc, supp):
        logger.warning(
            "log %s not found (store reset?) — flagging re-seed", state.wml_uid
        )
        return True
    logger.error(
        "UpdateInStore failed for log %s rc=%s supp=%s", state.wml_uid, rc, supp
    )
    return False


async def tick(client: WitsmlClient, fleet: list[WellboreState], tick_no: int) -> bool:
    """Append one new row to every log; periodically burst one well. Returns
    True if any log had vanished (store reset) and the fleet needs re-seeding.
    """
    burst_target = (
        fleet[tick_no % len(fleet)]
        if (tick_no and tick_no % BURST_EVERY_TICKS == 0)
        else None
    )

    needs_reseed = False
    for wb in fleet:
        for state in wb.logs:
            if wb is burst_target:
                rows = [_emit_row(state) for _ in range(BURST_ROWS)]
                logger.info("burst: %d rows into log %s", len(rows), state.wml_uid)
            else:
                rows = [_emit_row(state)]
            if await _update_log(client, wb, state, rows):
                needs_reseed = True
    return needs_reseed


# ── Entry point ────────────────────────────────────────────────────────────
async def main() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    count = settings.simulated_well_count
    interval = settings.poll_interval_seconds
    logger.info(
        "feed simulator starting: %d wells, %.1fs interval, target=%s",
        count,
        interval,
        settings.witsml_url,
    )

    client = WitsmlClient.from_settings()
    fleet = build_fleet(count)

    try:
        # Wait for the server to accept our first object, then seed.
        await _wait_for_server(client)
        await seed_fleet(client, fleet)

        tick_no = 0
        while True:
            tick_no += 1
            try:
                if await tick(client, fleet, tick_no):
                    # The store was reset (e.g. mockstore restarted) — its
                    # in-memory objects are gone. Re-create the whole fleet so
                    # discovery and ingestion recover automatically.
                    logger.warning("store appears reset — re-seeding the fleet")
                    await seed_fleet(client, fleet)
            except Exception:  # never let one bad tick kill the rig
                logger.exception("tick %d failed", tick_no)
            await asyncio.sleep(interval)
    finally:
        await client.aclose()


async def _wait_for_server(
    client: WitsmlClient, *, attempts: int = 60, delay: float = 5.0
) -> None:
    """Block until the WITSML server answers WMLS_GetVersion (boot ordering)."""
    for n in range(1, attempts + 1):
        try:
            version = await client.get_version()
            logger.info("WITSML server up (version=%s)", version)
            return
        except Exception as exc:  # noqa: BLE001 — log and retry
            logger.warning("server not ready (attempt %d/%d): %s", n, attempts, exc)
            await asyncio.sleep(delay)
    logger.error(
        "server never became ready after %d attempts; proceeding anyway", attempts
    )


if __name__ == "__main__":
    asyncio.run(main())
