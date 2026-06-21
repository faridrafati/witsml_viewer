"""PDF export of a simple multi-track 'Draw' view via reportlab.

`build_tracks_pdf` renders, for each requested mnemonic, one small line plot of
its values over the shared index — stacked vertically as separate tracks under a
title/header. It is deliberately dependency-light: a single reportlab ``canvas``
draws the header, axes, and polylines directly (no charting extras).

Input shape (kept loose so callers can feed warm-store or history samples):
    wells_curves: list of well bundles, each ::
        {"wellUid": str, "name": str | None,
         "curves": {mnemonic: [{"i": float, "v": float|None, ...}, ...]}}
    meta: free-form dict surfaced in the header (e.g. indexType, generatedAt).

Multiple wells overlay on the same track (one polyline per well) so wells can be
compared per mnemonic. Tracks with no numeric data render an empty framed box.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

# A small palette so overlaid wells are distinguishable per track.
_WELL_COLORS: list[Color] = [
    HexColor("#1f77b4"),
    HexColor("#d62728"),
    HexColor("#2ca02c"),
    HexColor("#9467bd"),
]
_AXIS = HexColor("#888888")
_TEXT = HexColor("#222222")


def _collect_mnemonics(wells_curves: list[dict]) -> list[str]:
    """Ordered union of every mnemonic appearing across the wells."""
    seen: set[str] = set()
    order: list[str] = []
    for well in wells_curves:
        for mnem in well.get("curves") or {}:
            if mnem not in seen:
                seen.add(mnem)
                order.append(mnem)
    return order


def _points(samples: list[dict]) -> list[tuple[float, float]]:
    """Extract (index, value) pairs with numeric values, sorted by index."""
    pts: list[tuple[float, float]] = []
    for s in samples or ():
        i = s.get("i")
        v = s.get("v")
        if i is None or v is None:
            continue
        try:
            pts.append((float(i), float(v)))
        except (TypeError, ValueError):
            continue
    pts.sort(key=lambda p: p[0])
    return pts


def _draw_header(c: canvas.Canvas, title: str, meta: dict, width: float, top: float) -> float:
    """Draw the title + meta line, returning the y of the first track top."""
    c.setFillColor(_TEXT)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(18 * mm, top, title or "Curve Tracks")

    c.setFont("Helvetica", 9)
    c.setFillColor(_AXIS)
    generated = meta.get("generatedAt") or datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    bits = [f"generated {generated}"]
    if meta.get("indexType"):
        bits.append(f"index: {meta['indexType']}")
    if meta.get("wellCount") is not None:
        bits.append(f"wells: {meta['wellCount']}")
    c.drawString(18 * mm, top - 6 * mm, "   ".join(bits))
    return top - 14 * mm


def _draw_track(
    c: canvas.Canvas,
    mnemonic: str,
    series: list[tuple[Color, list[tuple[float, float]]]],
    *,
    x: float,
    y: float,
    w: float,
    h: float,
) -> None:
    """Draw one mnemonic track: a framed plot with one polyline per well."""
    # Frame.
    c.setStrokeColor(_AXIS)
    c.setLineWidth(0.5)
    c.rect(x, y, w, h, stroke=1, fill=0)

    # Label.
    c.setFillColor(_TEXT)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x + 2 * mm, y + h - 4 * mm, mnemonic)

    all_pts = [p for _, pts in series for p in pts]
    if not all_pts:
        c.setFillColor(_AXIS)
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(x + 2 * mm, y + h / 2, "no data")
        return

    xs = [p[0] for p in all_pts]
    vs = [p[1] for p in all_pts]
    x_min, x_max = min(xs), max(xs)
    v_min, v_max = min(vs), max(vs)
    x_span = (x_max - x_min) or 1.0
    v_span = (v_max - v_min) or 1.0

    pad = 2 * mm
    plot_x = x + 14 * mm  # leave room for the value axis labels
    plot_w = w - 14 * mm - pad
    plot_y = y + pad
    plot_h = h - 6 * mm  # leave room for the label band

    def sx(ix: float) -> float:
        return plot_x + (ix - x_min) / x_span * plot_w

    def sy(val: float) -> float:
        return plot_y + (val - v_min) / v_span * plot_h

    # Value axis min/max.
    c.setFillColor(_AXIS)
    c.setFont("Helvetica", 6)
    c.drawString(x + 1.5 * mm, plot_y + plot_h - 2 * mm, f"{v_max:.4g}")
    c.drawString(x + 1.5 * mm, plot_y, f"{v_min:.4g}")

    for color, pts in series:
        if len(pts) < 1:
            continue
        c.setStrokeColor(color)
        c.setLineWidth(0.8)
        if len(pts) == 1:
            px, py = sx(pts[0][0]), sy(pts[0][1])
            c.circle(px, py, 0.6, stroke=1, fill=1)
            continue
        path = c.beginPath()
        path.moveTo(sx(pts[0][0]), sy(pts[0][1]))
        for ix, val in pts[1:]:
            path.lineTo(sx(ix), sy(val))
        c.drawPath(path, stroke=1, fill=0)


def build_tracks_pdf(title: str, wells_curves: list[dict], meta: dict | None = None) -> bytes:
    """Render a stacked multi-track PDF, returning the document bytes."""
    meta = dict(meta or {})
    meta.setdefault("wellCount", len(wells_curves))

    width, height = A4
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    mnemonics = _collect_mnemonics(wells_curves)

    # Pre-compute per-well colours (stable across pages).
    well_color: dict[str, Color] = {}
    for i, well in enumerate(wells_curves):
        uid = well.get("wellUid") or well.get("name") or f"well{i}"
        well_color[uid] = _WELL_COLORS[i % len(_WELL_COLORS)]

    margin = 15 * mm
    track_h = 40 * mm
    gap = 6 * mm

    track_top = _draw_header(c, title, meta, width, height - margin)

    # Legend (well -> colour), only when overlaying more than one well.
    if len(wells_curves) > 1:
        lx = 18 * mm
        c.setFont("Helvetica", 8)
        for i, well in enumerate(wells_curves):
            uid = well.get("wellUid") or well.get("name") or f"well{i}"
            label = well.get("name") or uid
            color = well_color[uid]
            c.setFillColor(color)
            c.rect(lx, track_top - 2 * mm, 4 * mm, 3 * mm, stroke=0, fill=1)
            c.setFillColor(_TEXT)
            c.drawString(lx + 5 * mm, track_top - 2 * mm, str(label)[:28])
            lx += 5 * mm + 40 * mm
        track_top -= 8 * mm

    track_w = width - 2 * margin
    y = track_top - track_h

    if not mnemonics:
        c.setFillColor(_AXIS)
        c.setFont("Helvetica-Oblique", 11)
        c.drawString(margin, y, "No curve data to plot.")

    for mnem in mnemonics:
        if y < margin:
            c.showPage()
            y = height - margin - track_h
        series: list[tuple[Color, list[tuple[float, float]]]] = []
        for i, well in enumerate(wells_curves):
            uid = well.get("wellUid") or well.get("name") or f"well{i}"
            samples = (well.get("curves") or {}).get(mnem) or []
            pts = _points(samples)
            if pts:
                series.append((well_color[uid], pts))
        _draw_track(c, mnem, series, x=margin, y=y, w=track_w, h=track_h)
        y -= track_h + gap

    c.showPage()
    c.save()
    return buf.getvalue()
