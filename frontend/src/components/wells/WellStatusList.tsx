import {
  Box,
  Chip,
  CircularProgress,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Typography,
} from '@mui/material';
import OilBarrelIcon from '@mui/icons-material/OilBarrel';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import { useIngestWells } from '../../api/ingest';
import { useSessionStore } from '../../store/session';
import type { WellStatus } from '../../api/types';

function relativeTime(ts?: number | null): string {
  if (!ts) return 'no data';
  const deltaSec = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (deltaSec < 5) return 'just now';
  if (deltaSec < 60) return `${deltaSec}s ago`;
  if (deltaSec < 3600) return `${Math.round(deltaSec / 60)}m ago`;
  return `${Math.round(deltaSec / 3600)}h ago`;
}

/**
 * Sidebar listing every warm well from the ingest layer. Each row shows a
 * growing indicator and the last-update time; clicking a row sets the
 * selected well in the Zustand session store, which (re)binds the dashboard's
 * single WebSocket subscription.
 */
export function WellStatusList() {
  const { data: wells, isLoading, isError } = useIngestWells();
  const selectedWellUid = useSessionStore((s) => s.selectedWellUid);
  const setSelectedWell = useSessionStore((s) => s.setSelectedWell);

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, p: 2 }}>
        <CircularProgress size={16} />
        <Typography variant="body2" color="text.secondary">
          Loading wells…
        </Typography>
      </Box>
    );
  }

  if (isError) {
    return (
      <Typography color="error" variant="body2" sx={{ p: 2 }}>
        Failed to load ingest wells.
      </Typography>
    );
  }

  if (!wells || wells.length === 0) {
    return (
      <Typography color="text.secondary" variant="body2" sx={{ p: 2 }}>
        No warm wells yet.
      </Typography>
    );
  }

  return (
    <List dense disablePadding>
      {wells.map((well: WellStatus) => {
        const isSelected = well.uid === selectedWellUid;
        return (
          <ListItemButton
            key={well.uid}
            selected={isSelected}
            onClick={() => setSelectedWell(well.uid)}
          >
            <ListItemIcon sx={{ minWidth: 36 }}>
              <OilBarrelIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText
              primary={well.name}
              secondary={relativeTime(well.lastUpdate)}
              primaryTypographyProps={{ noWrap: true }}
            />
            {well.growing ? (
              <Chip
                size="small"
                color="success"
                variant="outlined"
                icon={<FiberManualRecordIcon sx={{ fontSize: 10 }} />}
                label="live"
                sx={{ ml: 1 }}
              />
            ) : (
              <Chip size="small" variant="outlined" label="idle" sx={{ ml: 1 }} />
            )}
          </ListItemButton>
        );
      })}
    </List>
  );
}
