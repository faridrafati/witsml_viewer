import { useMemo } from 'react';
import { Box, Paper, Tooltip, Typography } from '@mui/material';
import type {
  ComparisonGeologyInterval,
  ComparisonLithology,
} from '../../api/comparison';

/* ------------------------------------------------------------------ */
/* Lithology -> colour / pattern mapping                              */
/* ------------------------------------------------------------------ */

export interface LithStyle {
  color: string;
  /** SVG pattern hint used to give common lithologies a distinct fill. */
  pattern: 'solid' | 'dots' | 'bricks' | 'dashes' | 'cross';
  label: string;
}

/**
 * Canonical lithology styles keyed by a normalized type string. Colours follow
 * common mud-log conventions (yellow sand, grey shale, blue limestone, …) so
 * tracks read the same way a geologist expects.
 */
const LITH_STYLES: Record<string, LithStyle> = {
  sandstone: { color: '#f4d03f', pattern: 'dots', label: 'Sandstone' },
  sand: { color: '#f4d03f', pattern: 'dots', label: 'Sand' },
  shale: { color: '#7f8c8d', pattern: 'dashes', label: 'Shale' },
  claystone: { color: '#95a5a6', pattern: 'dashes', label: 'Claystone' },
  clay: { color: '#95a5a6', pattern: 'dashes', label: 'Clay' },
  siltstone: { color: '#bdc3c7', pattern: 'dashes', label: 'Siltstone' },
  limestone: { color: '#5dade2', pattern: 'bricks', label: 'Limestone' },
  dolomite: { color: '#48c9b0', pattern: 'bricks', label: 'Dolomite' },
  salt: { color: '#ecf0f1', pattern: 'cross', label: 'Salt' },
  halite: { color: '#ecf0f1', pattern: 'cross', label: 'Halite' },
  anhydrite: { color: '#e8daef', pattern: 'cross', label: 'Anhydrite' },
  gypsum: { color: '#d2b4de', pattern: 'cross', label: 'Gypsum' },
  coal: { color: '#2c3e50', pattern: 'solid', label: 'Coal' },
  marl: { color: '#82e0aa', pattern: 'dots', label: 'Marl' },
  chalk: { color: '#aed6f1', pattern: 'bricks', label: 'Chalk' },
  conglomerate: { color: '#e59866', pattern: 'dots', label: 'Conglomerate' },
  granite: { color: '#cd6155', pattern: 'cross', label: 'Granite' },
  basalt: { color: '#34495e', pattern: 'solid', label: 'Basalt' },
  tuff: { color: '#d7bde2', pattern: 'dots', label: 'Tuff' },
};

const UNKNOWN_STYLE: LithStyle = {
  color: '#9e9e9e',
  pattern: 'solid',
  label: 'Unknown',
};

/** Normalize a free-text lithology type to a styling key. */
export function normalizeLithType(type?: string | null): string {
  return (type ?? '').trim().toLowerCase();
}

/**
 * Resolve a display style for a lithology. An explicit `color` from the source
 * data wins; otherwise we map the (normalized) type, falling back to a neutral
 * grey for unrecognized lithologies.
 */
export function lithStyle(lith: {
  type?: string | null;
  color?: string | null;
}): LithStyle {
  const key = normalizeLithType(lith.type);
  const base = LITH_STYLES[key] ?? {
    ...UNKNOWN_STYLE,
    label: lith.type?.trim() || 'Unknown',
  };
  return lith.color ? { ...base, color: lith.color } : base;
}

/** Distinct (type -> style) pairs across a set of intervals, for legends. */
export function lithLegend(
  intervals: ComparisonGeologyInterval[],
): Array<{ key: string; style: LithStyle }> {
  const seen = new Map<string, LithStyle>();
  for (const iv of intervals) {
    for (const l of iv.lithologies) {
      const key = normalizeLithType(l.type) || 'unknown';
      if (!seen.has(key)) seen.set(key, lithStyle(l));
    }
    if (iv.lithologies.length === 0 && iv.type_lithology) {
      const key = normalizeLithType(iv.type_lithology);
      if (!seen.has(key)) seen.set(key, lithStyle({ type: iv.type_lithology }));
    }
  }
  return Array.from(seen.entries()).map(([key, style]) => ({ key, style }));
}

/* ------------------------------------------------------------------ */
/* SVG pattern definitions                                            */
/* ------------------------------------------------------------------ */

function PatternDefs() {
  const stroke = 'rgba(0,0,0,0.45)';
  return (
    <defs>
      <pattern id="lith-dots" width="6" height="6" patternUnits="userSpaceOnUse">
        <circle cx="2" cy="2" r="1" fill={stroke} />
      </pattern>
      <pattern
        id="lith-dashes"
        width="8"
        height="6"
        patternUnits="userSpaceOnUse"
      >
        <line x1="0" y1="3" x2="5" y2="3" stroke={stroke} strokeWidth="1" />
      </pattern>
      <pattern
        id="lith-bricks"
        width="12"
        height="8"
        patternUnits="userSpaceOnUse"
      >
        <path
          d="M0 0H12M0 4H12M0 0V4M6 4V8M12 0V4"
          stroke={stroke}
          strokeWidth="0.8"
          fill="none"
        />
      </pattern>
      <pattern
        id="lith-cross"
        width="8"
        height="8"
        patternUnits="userSpaceOnUse"
      >
        <path
          d="M0 0L8 8M8 0L0 8"
          stroke={stroke}
          strokeWidth="0.8"
          fill="none"
        />
      </pattern>
    </defs>
  );
}

function patternFill(pattern: LithStyle['pattern']): string | undefined {
  switch (pattern) {
    case 'dots':
      return 'url(#lith-dots)';
    case 'dashes':
      return 'url(#lith-dashes)';
    case 'bricks':
      return 'url(#lith-bricks)';
    case 'cross':
      return 'url(#lith-cross)';
    default:
      return undefined;
  }
}

/* ------------------------------------------------------------------ */
/* Component                                                          */
/* ------------------------------------------------------------------ */

export interface LithologyTrackProps {
  wellName: string;
  intervals: ComparisonGeologyInterval[];
  /** Shared depth domain so all tracks line up on the same axis. */
  depthMin: number;
  depthMax: number;
  height?: number;
  width?: number;
  /** Normalized lith key to emphasize (others dimmed). */
  highlightType?: string | null;
}

interface Segment {
  yTop: number;
  yBottom: number;
  xStart: number;
  width: number;
  style: LithStyle;
  lith: ComparisonLithology;
  mdTop: number;
  mdBottom: number;
  description?: string | null;
}

/**
 * A single well's lithology column drawn over a SHARED depth axis.
 *
 * Each geology interval maps to a vertical band; within a band the component
 * lithologies are laid out left-to-right with width proportional to their
 * `lith_pc` (percentage), so a 70/30 sand/shale interval reads at a glance.
 * Hovering a segment reveals type, depth span, percentage and description.
 */
export function LithologyTrack({
  wellName,
  intervals,
  depthMin,
  depthMax,
  height = 480,
  width = 64,
  highlightType,
}: LithologyTrackProps) {
  const span = Math.max(depthMax - depthMin, 1e-9);

  const segments = useMemo<Segment[]>(() => {
    const out: Segment[] = [];
    for (const iv of intervals) {
      const top = iv.md_top;
      const bottom = iv.md_bottom;
      if (top == null || bottom == null || bottom <= top) continue;

      const yTop = ((top - depthMin) / span) * height;
      const yBottom = ((bottom - depthMin) / span) * height;

      // Effective lithology list: fall back to the interval's type_lithology
      // when no per-component lithologies are present.
      const liths: ComparisonLithology[] =
        iv.lithologies.length > 0
          ? iv.lithologies
          : [{ type: iv.type_lithology, lith_pc: 100 }];

      const totalPc =
        liths.reduce((acc, l) => acc + (l.lith_pc ?? 0), 0) || liths.length;

      let xCursor = 0;
      for (const l of liths) {
        const pc = l.lith_pc ?? 100 / liths.length;
        const w = (pc / totalPc) * width;
        out.push({
          yTop,
          yBottom,
          xStart: xCursor,
          width: w,
          style: lithStyle(l),
          lith: l,
          mdTop: top,
          mdBottom: bottom,
          description: l.description ?? iv.description,
        });
        xCursor += w;
      }
    }
    return out;
  }, [intervals, depthMin, span, height, width]);

  return (
    <Paper
      variant="outlined"
      sx={{ p: 1, display: 'inline-flex', flexDirection: 'column' }}
    >
      <Typography
        variant="caption"
        noWrap
        title={wellName}
        sx={{ maxWidth: width + 8, textAlign: 'center', fontWeight: 600 }}
      >
        {wellName}
      </Typography>
      <Box sx={{ position: 'relative' }}>
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`Lithology track for ${wellName}`}
          style={{ display: 'block', border: '1px solid rgba(0,0,0,0.12)' }}
        >
          <PatternDefs />
          <rect x={0} y={0} width={width} height={height} fill="#fafafa" />
          {segments.length === 0 && (
            <text
              x={width / 2}
              y={height / 2}
              textAnchor="middle"
              fontSize={10}
              fill="#9e9e9e"
            >
              no data
            </text>
          )}
          {segments.map((seg, idx) => {
            const dimmed =
              highlightType != null &&
              highlightType !== '' &&
              normalizeLithType(seg.lith.type) !== highlightType;
            const fillPattern = patternFill(seg.style.pattern);
            const h = Math.max(seg.yBottom - seg.yTop, 1);
            return (
              <Tooltip
                key={idx}
                arrow
                placement="right"
                title={
                  <Box sx={{ fontSize: 12 }}>
                    <strong>{seg.style.label}</strong>
                    <br />
                    {seg.mdTop.toFixed(1)} – {seg.mdBottom.toFixed(1)}
                    {seg.lith.lith_pc != null && (
                      <>
                        <br />
                        {seg.lith.lith_pc.toFixed(0)}%
                      </>
                    )}
                    {seg.description && (
                      <>
                        <br />
                        {seg.description}
                      </>
                    )}
                  </Box>
                }
              >
                <g opacity={dimmed ? 0.25 : 1} style={{ cursor: 'pointer' }}>
                  <rect
                    x={seg.xStart}
                    y={seg.yTop}
                    width={seg.width}
                    height={h}
                    fill={seg.style.color}
                    stroke="rgba(0,0,0,0.18)"
                    strokeWidth={0.4}
                  />
                  {fillPattern && (
                    <rect
                      x={seg.xStart}
                      y={seg.yTop}
                      width={seg.width}
                      height={h}
                      fill={fillPattern}
                    />
                  )}
                </g>
              </Tooltip>
            );
          })}
        </svg>
      </Box>
    </Paper>
  );
}
