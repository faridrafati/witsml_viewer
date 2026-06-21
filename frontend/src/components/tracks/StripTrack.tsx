import { useMemo } from 'react';
import { Paper, Typography, Box } from '@mui/material';
import type { IngestCurves, IngestPoint } from '../../api/types';

export interface StripTrackProps {
  /**
   * Mnemonic to render as a discrete strip. The latest values from the shared
   * live buffer are collapsed into contiguous, colored intervals (a stepped
   * state bar). A "LITH"-like mnemonic renders as a lithology strip.
   */
  mnemonic: string;
  /** Shared live curve buffer (from useWellStream). */
  curves: IngestCurves;
  /** Revision counter; bump signals new data (used to recompute). */
  rev: number;
  title?: string;
  /** Plot against time (epoch-ms index) or depth. Affects axis labels only. */
  axis?: 'time' | 'depth';
  height?: number;
  /** Background of the track surface. */
  backgroundColor?: string;
}

/** Stable, readable palette for discrete states / lithology codes. */
const STATE_COLORS = [
  '#8d6e63', // brown
  '#fdd835', // sandstone yellow
  '#90a4ae', // shale grey
  '#4db6ac', // limestone teal
  '#7e57c2', // purple
  '#ef5350', // red
  '#66bb6a', // green
  '#42a5f5', // blue
  '#ff8a65', // orange
  '#bdbdbd', // light grey
];

interface Segment {
  /** Discrete state key for this run (rounded value or category). */
  key: string;
  start: number;
  end: number;
  color: string;
}

/**
 * Collapse a series of samples into contiguous runs of equal state.
 *
 * Continuous numeric values are bucketed (rounded) so a noisy channel still
 * produces readable bands; the index axis (time/depth) drives segment widths.
 */
function buildSegments(points: IngestPoint[]): { segments: Segment[]; min: number; max: number } {
  if (points.length === 0) return { segments: [], min: 0, max: 1 };

  const colorByKey = new Map<string, string>();
  const colorFor = (key: string): string => {
    let c = colorByKey.get(key);
    if (!c) {
      c = STATE_COLORS[colorByKey.size % STATE_COLORS.length];
      colorByKey.set(key, c);
    }
    return c;
  };

  const keyFor = (v: number): string => {
    // Integer-ish channels (lithology codes, flags) key exactly; otherwise
    // bucket to one decimal so continuous channels still band cleanly.
    return Number.isInteger(v) ? String(v) : v.toFixed(1);
  };

  const sorted = [...points].sort((a, b) => a.i - b.i);
  const min = sorted[0].i;
  const max = sorted[sorted.length - 1].i;

  const segments: Segment[] = [];
  for (let idx = 0; idx < sorted.length; idx += 1) {
    const p = sorted[idx];
    const key = keyFor(p.v);
    const next = sorted[idx + 1];
    const end = next ? next.i : p.i + (max - min) / Math.max(sorted.length, 1) || p.i + 1;
    const last = segments[segments.length - 1];
    if (last && last.key === key) {
      last.end = end;
    } else {
      segments.push({ key, start: p.i, end, color: colorFor(key) });
    }
  }

  return { segments, min, max };
}

/**
 * A track-style component rendering a discrete/lithology strip over depth or
 * time as colored bars. Self-contained SVG + MUI; no heavy chart dependency.
 *
 * Reads the latest windowed samples for one mnemonic from the shared live
 * buffer and draws contiguous colored intervals, with a small legend of the
 * states currently in view.
 */
export function StripTrack({
  mnemonic,
  curves,
  rev,
  title,
  axis = 'depth',
  height = 120,
  backgroundColor,
}: StripTrackProps) {
  const points = curves[mnemonic] ?? [];

  // Recompute whenever the buffer mutates (rev) or the mnemonic changes.
  const { segments, min, max } = useMemo(
    () => buildSegments(points),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mnemonic, rev],
  );

  const span = max - min || 1;
  const barHeight = Math.max(24, height - 56);

  const legend = useMemo(() => {
    const seen = new Map<string, string>();
    for (const s of segments) if (!seen.has(s.key)) seen.set(s.key, s.color);
    return Array.from(seen.entries());
  }, [segments]);

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 2,
        height,
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: backgroundColor || undefined,
        overflow: 'hidden',
      }}
    >
      <Typography variant="subtitle2" gutterBottom noWrap>
        {title ?? mnemonic}
      </Typography>

      {segments.length === 0 ? (
        <Box
          sx={{
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'text.secondary',
          }}
        >
          <Typography variant="body2">Waiting for {mnemonic} data…</Typography>
        </Box>
      ) : (
        <>
          <Box sx={{ width: '100%' }}>
            <svg
              width="100%"
              height={barHeight}
              viewBox={`0 0 1000 ${barHeight}`}
              preserveAspectRatio="none"
              role="img"
              aria-label={`${mnemonic} strip`}
            >
              {segments.map((s, i) => {
                const x = ((s.start - min) / span) * 1000;
                const w = Math.max(((s.end - s.start) / span) * 1000, 0.5);
                return (
                  <rect
                    key={`${s.key}-${i}`}
                    x={x}
                    y={0}
                    width={w}
                    height={barHeight}
                    fill={s.color}
                    stroke="rgba(0,0,0,0.15)"
                    strokeWidth={0.5}
                  >
                    <title>{`${s.key}`}</title>
                  </rect>
                );
              })}
            </svg>
          </Box>

          <Box
            sx={{
              display: 'flex',
              justifyContent: 'space-between',
              mt: 0.5,
              color: 'text.secondary',
            }}
          >
            <Typography variant="caption">
              {axis === 'time'
                ? new Date(min).toLocaleTimeString()
                : min.toFixed(1)}
            </Typography>
            <Typography variant="caption">
              {axis === 'time'
                ? new Date(max).toLocaleTimeString()
                : max.toFixed(1)}
            </Typography>
          </Box>

          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mt: 0.5 }}>
            {legend.slice(0, 8).map(([key, color]) => (
              <Box
                key={key}
                sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}
              >
                <Box
                  sx={{
                    width: 10,
                    height: 10,
                    borderRadius: 0.5,
                    backgroundColor: color,
                  }}
                />
                <Typography variant="caption" color="text.secondary">
                  {key}
                </Typography>
              </Box>
            ))}
          </Box>
        </>
      )}
    </Paper>
  );
}
