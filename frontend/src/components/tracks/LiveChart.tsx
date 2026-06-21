import { useEffect, useRef } from 'react';
import { Paper, Typography, Box } from '@mui/material';
import type uPlot from 'uplot';
import type { IngestCurves } from '../../api/types';

export interface LiveChartProps {
  /** Mnemonics to draw as series; the first defines the x-axis domain. */
  mnemonics: string[];
  /** Shared live curve buffer (from useWellStream). */
  curves: IngestCurves;
  /** Revision counter; bump signals new data. */
  rev: number;
  /** True if the index is epoch-millis time (vs. depth). */
  timeAxis?: boolean;
  title?: string;
  height?: number;
}

const SERIES_COLORS = [
  '#42a5f5',
  '#ef5350',
  '#66bb6a',
  '#ffa726',
  '#ab47bc',
  '#26c6da',
];

/**
 * uPlot-backed live line chart for one well across a set of mnemonics.
 *
 * - uPlot is lazy-imported (`await import('uplot')`) so it stays out of the
 *   initial bundle; its CSS is loaded the same way.
 * - Data comes from a shared live buffer that is already windowed (fixed
 *   scrolling window) upstream in `useWellStream`.
 * - The chart instance is created once per mount/size and destroyed on
 *   unmount; data is pushed via `setData` on every `rev` bump.
 *
 * All mnemonics are plotted against a common x-axis built from the union of
 * their index values, so series sampled at slightly different indices still
 * align on the same scale.
 */
export function LiveChart({
  mnemonics,
  curves,
  rev,
  timeAxis = true,
  title = 'Live',
  height = 280,
}: LiveChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const plotRef = useRef<uPlot | null>(null);
  const mnemonicsKey = mnemonics.join(',');

  // Build aligned uPlot data: [xs, series0, series1, ...].
  function buildData(): (number | null)[][] {
    // Union of all index values across the requested mnemonics.
    const indexSet = new Set<number>();
    for (const m of mnemonics) {
      const pts = curves[m];
      if (!pts) continue;
      for (const p of pts) indexSet.add(p.i);
    }
    const xs = Array.from(indexSet).sort((a, b) => a - b);
    const xPos = new Map<number, number>();
    xs.forEach((x, idx) => xPos.set(x, idx));

    const data: (number | null)[][] = [xs];
    for (const m of mnemonics) {
      const col: (number | null)[] = new Array(xs.length).fill(null);
      const pts = curves[m];
      if (pts) {
        for (const p of pts) {
          const idx = xPos.get(p.i);
          if (idx !== undefined) col[idx] = p.v;
        }
      }
      data.push(col);
    }
    return data;
  }

  // Create / recreate the plot when mnemonics, axis mode, or size change.
  useEffect(() => {
    let disposed = false;
    const el = containerRef.current;
    if (!el) return;

    (async () => {
      const [{ default: UPlot }] = await Promise.all([
        import('uplot'),
        import('uplot/dist/uPlot.min.css'),
      ]);
      if (disposed || !containerRef.current) return;

      const series: uPlot.Series[] = [
        timeAxis ? { label: 'time' } : { label: 'depth' },
        ...mnemonics.map((m, i) => ({
          label: m,
          stroke: SERIES_COLORS[i % SERIES_COLORS.length],
          width: 1.5,
          spanGaps: true,
        })),
      ];

      const opts: uPlot.Options = {
        width: containerRef.current.clientWidth || 600,
        height,
        series,
        scales: { x: { time: timeAxis } },
        legend: { show: true },
        cursor: { drag: { x: true, y: false } },
      };

      plotRef.current?.destroy();
      plotRef.current = new UPlot(
        opts,
        buildData() as uPlot.AlignedData,
        containerRef.current,
      );
    })();

    return () => {
      disposed = true;
      plotRef.current?.destroy();
      plotRef.current = null;
    };
    // buildData closes over `curves`, but we intentionally rebuild the plot
    // only on structural changes; data refresh is handled by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mnemonicsKey, timeAxis, height]);

  // Push fresh data on every revision bump without recreating the plot.
  useEffect(() => {
    if (plotRef.current) {
      plotRef.current.setData(buildData() as uPlot.AlignedData);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rev, mnemonicsKey]);

  // Keep the canvas width in sync with the container.
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

  const hasData = mnemonics.some((m) => (curves[m]?.length ?? 0) > 0);

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Typography variant="subtitle2" gutterBottom>
        {title}
      </Typography>
      <Box ref={containerRef} sx={{ position: 'relative', minHeight: height }}>
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
            <Typography variant="body2">Waiting for live data…</Typography>
          </Box>
        )}
      </Box>
    </Paper>
  );
}
