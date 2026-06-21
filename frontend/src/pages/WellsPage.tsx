import { Alert, Box, CircularProgress, Paper, Typography } from '@mui/material';
import { useTree } from '../api/queries';
import { useSessionStore } from '../store/session';
import { WellTree } from '../components/wells/WellTree';

export function WellsPage() {
  const { data, isLoading, isError, error } = useTree();
  const selectedWellUid = useSessionStore((s) => s.selectedWellUid);
  const setSelectedWell = useSessionStore((s) => s.setSelectedWell);

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        Connected Wells
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        Browse the well and wellbore hierarchy from the connected WITSML store.
        Selecting a well makes it the active context for the dashboard.
      </Typography>

      {isLoading && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, p: 2 }}>
          <CircularProgress size={20} />
          <Typography color="text.secondary">Loading well tree…</Typography>
        </Box>
      )}

      {isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Failed to load wells: {(error as Error)?.message ?? 'unknown error'}
        </Alert>
      )}

      {!isLoading && !isError && (
        <Paper variant="outlined" sx={{ maxWidth: 640 }}>
          <WellTree
            nodes={data ?? []}
            selectedWellUid={selectedWellUid}
            onSelectWell={setSelectedWell}
          />
        </Paper>
      )}
    </Box>
  );
}
