import { Paper, Typography, Box } from '@mui/material';
import type { IngestCurves } from '../../api/types';

export interface NumericReadoutProps {
  /** Mnemonic to display, e.g. "DEPTH". */
  mnemonic: string;
  /** Optional human label; defaults to the mnemonic. */
  label?: string;
  /** Shared live curve buffer (from useWellStream). */
  curves: IngestCurves;
  /** Number of fractional digits to render. */
  precision?: number;
  height?: number;
}

/**
 * A large single-value readout for the latest sample of one mnemonic, with its
 * unit of measure. Reads from the shared live curve buffer; renders an em-dash
 * placeholder until the first sample arrives.
 */
export function NumericReadout({
  mnemonic,
  label,
  curves,
  precision = 1,
  height = 120,
}: NumericReadoutProps) {
  const points = curves[mnemonic];
  const latest = points && points.length > 0 ? points[points.length - 1] : null;

  const valueText =
    latest && Number.isFinite(latest.v) ? latest.v.toFixed(precision) : '—';
  const unit = latest?.u ?? '';

  return (
    <Paper
      variant="outlined"
      sx={{
        height,
        p: 2,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
      }}
    >
      <Typography variant="overline" color="text.secondary" noWrap>
        {label ?? mnemonic}
      </Typography>
      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1 }}>
        <Typography
          variant="h3"
          component="span"
          sx={{ fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}
        >
          {valueText}
        </Typography>
        {unit && (
          <Typography variant="h6" component="span" color="text.secondary">
            {unit}
          </Typography>
        )}
      </Box>
    </Paper>
  );
}
