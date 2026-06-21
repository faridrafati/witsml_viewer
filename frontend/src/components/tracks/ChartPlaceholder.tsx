import { Box, Paper, Typography } from '@mui/material';
import ShowChartIcon from '@mui/icons-material/ShowChart';

/**
 * Track abstraction note.
 *
 * A "track" is a single vertical lane in the log view. Each track can be
 * backed by one of two renderers, chosen per-track at wire-up time:
 *
 *   - uPlot ........... fast canvas line/scatter plots (time or depth index)
 *   - videx-wellog .... specialized petrophysical well-log tracks
 *
 * To keep the bundle lean and the app buildable before charts are wired,
 * those heavy libraries MUST be imported lazily and ONLY inside the concrete
 * track component (e.g. `const uPlot = (await import('uplot')).default`).
 * This placeholder imports neither, so it is always safe to render.
 */
export interface ChartPlaceholderProps {
  title?: string;
  backend?: 'uplot' | 'videx-wellog';
  height?: number;
}

export function ChartPlaceholder({
  title = 'Track',
  backend = 'uplot',
  height = 240,
}: ChartPlaceholderProps) {
  return (
    <Paper
      variant="outlined"
      sx={{
        height,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 1,
        borderStyle: 'dashed',
        color: 'text.secondary',
      }}
    >
      <ShowChartIcon fontSize="large" />
      <Box textAlign="center">
        <Typography variant="subtitle2">{title}</Typography>
        <Typography variant="caption">
          Renderer: {backend} (lazy-loaded when wired)
        </Typography>
      </Box>
    </Paper>
  );
}
