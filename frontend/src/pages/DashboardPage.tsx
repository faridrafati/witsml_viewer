import { Alert, Box, Chip, Grid, Paper, Typography } from '@mui/material';
import { useSessionStore } from '../store/session';
import { useWellStream } from '../api/useWellStream';
import { WellStatusList } from '../components/wells/WellStatusList';
import { NumericReadout } from '../components/tracks/NumericReadout';
import { LiveChart } from '../components/tracks/LiveChart';

/** Mnemonics charted over time for the selected well. */
const CHART_MNEMONICS = ['ROP', 'WOB', 'TOTGAS'];
/** Mnemonics surfaced as big single-value readouts. */
const READOUT_MNEMONICS: { mnemonic: string; label: string }[] = [
  { mnemonic: 'DEPTH', label: 'Depth' },
  { mnemonic: 'ROP', label: 'Rate of Penetration' },
  { mnemonic: 'TOTGAS', label: 'Total Gas' },
];

function statusLabel(status: string): string {
  switch (status) {
    case 'open':
      return 'Live';
    case 'connecting':
      return 'Connecting…';
    case 'closed':
      return 'Reconnecting…';
    default:
      return 'Idle';
  }
}

export function DashboardPage() {
  const selectedWellUid = useSessionStore((s) => s.selectedWellUid);

  // ONE shared WebSocket subscription for the viewed well. Both the readouts
  // and the chart read from this single buffer; it (re)subscribes on change
  // and tears down on unmount.
  const { status, curves, rev } = useWellStream(selectedWellUid, 500);

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
        <Typography variant="h5">Live Dashboard</Typography>
        {selectedWellUid && (
          <Chip
            size="small"
            color={status === 'open' ? 'success' : 'default'}
            label={statusLabel(status)}
          />
        )}
      </Box>

      <Grid container spacing={2}>
        {/* Sidebar: all warm wells. */}
        <Grid item xs={12} md={3}>
          <Paper variant="outlined" sx={{ overflow: 'hidden' }}>
            <Typography variant="subtitle2" sx={{ p: 2, pb: 1 }}>
              Wells
            </Typography>
            <WellStatusList />
          </Paper>
        </Grid>

        {/* Main: readouts + live chart for the selected well. */}
        <Grid item xs={12} md={9}>
          {!selectedWellUid ? (
            <Alert severity="info">
              No well selected. Pick a well from the list to start streaming.
            </Alert>
          ) : (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <Grid container spacing={2}>
                {READOUT_MNEMONICS.map((r) => (
                  <Grid item xs={12} sm={4} key={r.mnemonic}>
                    <NumericReadout
                      mnemonic={r.mnemonic}
                      label={r.label}
                      curves={curves}
                      // `rev` is unused by the readout directly, but threading
                      // it via the parent re-render keeps the latest value
                      // fresh as the shared buffer mutates.
                    />
                  </Grid>
                ))}
              </Grid>

              <LiveChart
                title="ROP / WOB / Total Gas over time"
                mnemonics={CHART_MNEMONICS}
                curves={curves}
                rev={rev}
                timeAxis
                height={300}
              />
            </Box>
          )}
        </Grid>
      </Grid>
    </Box>
  );
}
