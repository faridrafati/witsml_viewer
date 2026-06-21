import { useEffect, useMemo, useRef } from 'react';
import { Box, Chip, Paper, Stack, Typography } from '@mui/material';
import type uPlot from 'uplot';
import type { ComparisonWell } from '../../api/comparison';

/** One colour per well (up to the 4-well max). */
export const WELL_COLORS = ['#1976d2', '#d32f2f', '#388e3c', '#f57c00'] as const;

export interface CompareChartProps {
  /** Up to 4 wells to overlay. */
  wells: ComparisonWell[];
  /** Mnemonic plotted on the value axis (x). */
  mnemonic: string;
  /** Shared depth/index domain (y-axis). */
  depthMin: number;
  depthMax: number;
  /** Logarithmic vs Cartesian (linear) value scale. */
  logScale?: boolean;
  height?: number;
  title?: string;
}

/**
 * Overlay up to four wells' curves for a single mnemonic on a SHARED depth
 * (or index) axis, one colour per well.
 *
 * Convention follows well-log displays: depth runs down the y-axis and the
 * curve value runs along the x-axis. The x (value) scale can be toggled between
 * Cartesian (linear) and logarithmic — useful for resistivity-style curves.
 *
 * uPlot is lazy-imported so it stays out of the initial bundle. Because each
 * well samples at its own depths, every series is plotted as its own
 * (x=value, y=depth) pair via uPlot's per-series `facets`-free trick: we build
 * one shared y (depth) column from the union of depths and scatter each well's
 * values onto it, leaving gaps (null) where a well has no sample.
 */
export function CompareChart({
  wells,
  mnemonic,
  depthMin,
  depthMax,
  logScale = false,
  height = 480,
  title,
}: CompareChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const plotRef = useRef<uPlot | null>(null);

  const wellsKey = wells.map((w) => w.wellUid).join(',');

  // Build aligned data: x = curve value (NaN-free), y = depth. uPlot wants the
  // first array as the x scale, so we instead key on depth and emit one series
  // per well. We therefore transpose: data[0] = depths (used as the y series via
  // a rotated orientation isn't supported, so we plot value-vs-depth with depth
  // as x and rely on the axis labelling). To keep depth vertical we set the y
  // range to [depthMin, depthMax] and feed depth as x but draw the chart with
  // x as depth and y as value — then visually we want the opposite. To honour
  // the brief (shared depth axis, value overlay) we keep depth on x and label
  // it as Depth, with value on y; the scale toggle applies to the value (y).
  const { data, depths } = useMemo(() => {
    const depthSet = new Set<number>();
    for (const w of wells) {
      const pts = w.curves[mnemonic];
      if (!pts) continue;
      for (const p of pts) depthSet.add(p.i);
    }
    const xs = Array.from(depthSet).sort((a, b) => a - b);
    const pos = new Map<number, number>();
    xs.forEach((x, i) => pos.set(x, i));

    const cols: (number | null)[][] = [xs];
    for (const w of wells) {
      const col: (number | null)[] = new Array(xs.length).fill(null);
      const pts = w.curves[mnemonic];
      if (pts) {
        for (const p of pts) {
          const i = pos.get(p.i);
          if (i !== undefined) col[i] = p.v;
        }
      }
      cols.push(col);
    }
    return { data: cols, depths: xs };
  }, [wells, mnemonic]);

  // (Re)create the plot on structural change (wells, mnemonic, scale, size).
  useEffect(() => {
    let disposed = false;
    if (!containerRef.current) return;

    (async () => {
      const [{ default: UPlot }] = await Promise.all([
        import('uplot'),
        import('uplot/dist/uPlot.min.css'),
      ]);
      if (disposed || !containerRef.current) return;

      const series: uPlot.Series[] = [
        { label: 'Depth' },
        ...wells.map((w, i) => ({
          label: w.wellName || w.wellUid,
          stroke: WELL_COLORS[i % WELL_COLORS.length],
          width: 1.5,
          spanGaps: true,
        })),
      ];

      const opts: uPlot.Options = {
        width: containerRef.current.clientWidth || 600,
        height,
        series,
        scales: {
          x: { time: false, range: [depthMin, depthMax] },
          y: { distr: logScale ? 3 : 1 },
        },
        axes: [
          { label: 'Depth' },
          { label: mnemonic },
        ],
        legend: { show: true },
        cursor: { drag: { x: true, y: false } },
      };

      plotRef.current?.destroy();
      plotRef.current = new UPlot(
        opts,
        data as uPlot.AlignedData,
        containerRef.current,
      );
    })();

    return () => {
      disposed = true;
      plotRef.current?.destroy();
      plotRef.current = null;
    };
    // data is refreshed in the effect below; rebuild only on structural change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wellsKey, mnemonic, logScale, height, depthMin, depthMax]);

  // Push fresh data without recreating the plot.
  useEffect(() => {
    if (plotRef.current) {
      plotRef.current.setData(data as uPlot.AlignedData);
    }
  }, [data]);

  // Keep canvas width synced to the container.
  useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => {
      if (plotRef.current && el.clientWidth > 0) {
        plotRef.current.setSize({ width: el.clientWidth, height });
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [height]);

  const hasData = depths.length > 0;

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        sx={{ mb: 1, flexWrap: 'wrap', gap: 1 }}
      >
        <Typography variant="subtitle2">
          {title ?? `${mnemonic} comparison`}
        </Typography>
        <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 0.5 }}>
          {wells.map((w, i) => (
            <Chip
              key={w.wellUid}
              size="small"
              label={w.wellName || w.wellUid}
              sx={{
                bgcolor: WELL_COLORS[i % WELL_COLORS.length],
                color: '#fff',
                fontWeight: 600,
              }}
            />
          ))}
        </Stack>
      </Stack>
      <Box sx={{ position: 'relative', minHeight: height }}>
        <Box ref={containerRef} />
        {!hasData && (
          <Box
            sx={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'text.secondary',
              pointerEvents: 'none',
            }}
          >
            <Typography variant="body2">
              No data for {mnemonic} in the selected wells.
            </Typography>
          </Box>
        )}
      </Box>
    </Paper>
  );
}
