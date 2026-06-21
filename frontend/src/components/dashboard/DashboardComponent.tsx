import { useEffect, useRef } from 'react';
import { Paper, Typography, Box } from '@mui/material';
import type uPlot from 'uplot';
import type { IngestCurves } from '../../api/types';
import type { DashboardComponentConfig } from '../../api/pages';
import { NumericReadout } from '../tracks/NumericReadout';
import { StripTrack } from '../tracks/StripTrack';

export interface DashboardComponentProps {
  config: DashboardComponentConfig;
  /** Shared live curve buffer (from useWellStream). */
  curves: IngestCurves;
  /** Revision counter; bumps on new data. */
  rev: number;
  /** Inner height available for the component body. */
  height?: number;
}

/**
 * uPlot-backed chart that honors the per-component `ui` config
 * (line color, stroke width, y-min/y-max, unit label) and the
 * `time_config` axis (time vs depth). Kept local to this module because the
 * shared LiveChart does not expose these knobs.
 */
function ConfigurableChart({
  config,
  curves,
  rev,
  height,
}: {
  config: DashboardComponentConfig;
  curves: IngestCurves;
  rev: number;
  height: number;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const plotRef = useRef<uPlot | null>(null);
  const { mnemonics, ui, time_config } = config;
  const mnemonicsKey = mnemonics.join(',');
  const timeAxis = time_config.axis === 'time';

  function buildData(): (number | null)[][] {
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
        ...mnemonics.map((m) => ({
          label: ui.unit ? `${m} (${ui.unit})` : m,
          stroke: ui.lineColor || '#42a5f5',
          width: ui.lineStroke || 1.5,
          spanGaps: true,
        })),
      ];

      // Honor explicit y-range when both bounds are supplied.
      const yRange: uPlot.Scale.Range | undefined =
        ui.min != null && ui.max != null
          ? [ui.min, ui.max]
          : undefined;

      const opts: uPlot.Options = {
        width: containerRef.current.clientWidth || 600,
        height,
        series,
        scales: {
          x: { time: timeAxis },
          y: yRange ? { range: yRange } : {},
        },
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    mnemonicsKey,
    timeAxis,
    height,
    ui.lineColor,
    ui.lineStroke,
    ui.unit,
    ui.min,
    ui.max,
  ]);

  useEffect(() => {
    if (plotRef.current) {
      plotRef.current.setData(buildData() as uPlot.AlignedData);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rev, mnemonicsKey]);

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
  );
}

/**
 * Renders ONE dashboard component from its config plus the shared live buffer.
 *
 *   numeric -> NumericReadout (latest value of the first mnemonic)
 *   chart   -> ConfigurableChart (ui color/stroke/min/max/unit + time/depth axis)
 *   strip   -> StripTrack (discrete/lithology colored intervals)
 *
 * The component never opens its own subscription; `curves`/`rev` are threaded
 * down from the page-level useWellStream so the whole page shares one socket.
 */
export function DashboardComponent({
  config,
  curves,
  rev,
  height = 220,
}: DashboardComponentProps) {
  const bg = config.back_config?.backgroundColor || undefined;
  const comment = config.comment_config;
  const firstMnemonic = config.mnemonics[0] ?? '';

  let body: JSX.Element;
  switch (config.type) {
    case 'numeric':
      body = (
        <NumericReadout
          mnemonic={firstMnemonic}
          label={config.title || firstMnemonic}
          curves={curves}
          height={height}
        />
      );
      break;
    case 'strip':
      body = (
        <StripTrack
          mnemonic={firstMnemonic}
          curves={curves}
          rev={rev}
          title={config.title || firstMnemonic}
          axis={config.time_config.axis}
          height={height}
          backgroundColor={bg}
        />
      );
      break;
    case 'chart':
    default:
      body = (
        <Paper
          variant="outlined"
          sx={{
            p: 2,
            height,
            display: 'flex',
            flexDirection: 'column',
            backgroundColor: bg,
            overflow: 'hidden',
          }}
        >
          <Typography variant="subtitle2" gutterBottom noWrap>
            {config.title || config.mnemonics.join(', ')}
          </Typography>
          <Box sx={{ flex: 1, minHeight: 0 }}>
            <ConfigurableChart
              config={config}
              curves={curves}
              rev={rev}
              height={Math.max(80, height - 56)}
            />
          </Box>
        </Paper>
      );
      break;
  }

  return (
    <Box sx={{ height: '100%', position: 'relative' }}>
      {body}
      {comment?.isVisible && comment.text && (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{
            position: 'absolute',
            bottom: 4,
            right: 8,
            px: 0.5,
            borderRadius: 0.5,
            backgroundColor: 'rgba(255,255,255,0.6)',
            pointerEvents: 'none',
          }}
        >
          {comment.text}
        </Typography>
      )}
    </Box>
  );
}
