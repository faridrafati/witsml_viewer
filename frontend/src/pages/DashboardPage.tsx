import { Alert, Box, Grid, Typography } from '@mui/material';
import { useSessionStore } from '../store/session';
import { ChartPlaceholder } from '../components/tracks/ChartPlaceholder';

export function DashboardPage() {
  const selectedWellUid = useSessionStore((s) => s.selectedWellUid);

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        Live Dashboard
      </Typography>

      {selectedWellUid ? (
        <Typography color="text.secondary" sx={{ mb: 2 }}>
          Active well: <code>{selectedWellUid}</code>
        </Typography>
      ) : (
        <Alert severity="info" sx={{ mb: 2 }}>
          No well selected. Pick a well on the Wells page to bind the dashboard.
        </Alert>
      )}

      <Alert severity="info" sx={{ mb: 3 }}>
        The live, streaming dashboard (real-time curve tracks over WebSocket)
        arrives in Phase 3. The track lanes below are placeholders; each will be
        backed by uPlot or videx-wellog, loaded lazily.
      </Alert>

      <Grid container spacing={2}>
        <Grid item xs={12} md={4}>
          <ChartPlaceholder title="ROP / Depth" backend="uplot" />
        </Grid>
        <Grid item xs={12} md={4}>
          <ChartPlaceholder title="Gas Total" backend="uplot" />
        </Grid>
        <Grid item xs={12} md={4}>
          <ChartPlaceholder title="Lithology" backend="videx-wellog" />
        </Grid>
      </Grid>
    </Box>
  );
}
