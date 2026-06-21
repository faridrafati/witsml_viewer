import { useState } from 'react';
import {
  Box,
  Chip,
  Collapse,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Typography,
} from '@mui/material';
import ExpandLess from '@mui/icons-material/ExpandLess';
import ExpandMore from '@mui/icons-material/ExpandMore';
import OilBarrelIcon from '@mui/icons-material/OilBarrel';
import RouteIcon from '@mui/icons-material/Route';
import type { WellTreeNode } from '../../api/types';

interface WellTreeProps {
  nodes: WellTreeNode[];
  selectedWellUid: string | null;
  onSelectWell: (wellUid: string) => void;
}

function statusColor(status?: string | null): 'success' | 'warning' | 'default' {
  if (!status) return 'default';
  const s = status.toLowerCase();
  if (s.includes('drill') || s.includes('active')) return 'success';
  if (s.includes('plan') || s.includes('suspend')) return 'warning';
  return 'default';
}

/**
 * MUI list-based tree of wells with their nested wellbores. Region and status
 * are surfaced as chips. Selecting a well row notifies the parent.
 */
export function WellTree({ nodes, selectedWellUid, onSelectWell }: WellTreeProps) {
  const [open, setOpen] = useState<Record<string, boolean>>({});

  const toggle = (uid: string) =>
    setOpen((prev) => ({ ...prev, [uid]: !prev[uid] }));

  if (nodes.length === 0) {
    return (
      <Typography color="text.secondary" sx={{ p: 2 }}>
        No wells connected yet.
      </Typography>
    );
  }

  return (
    <List dense disablePadding>
      {nodes.map((well) => {
        const isOpen = open[well.uid] ?? false;
        const isSelected = well.uid === selectedWellUid;
        return (
          <Box key={well.uid}>
            <ListItemButton
              selected={isSelected}
              onClick={() => {
                onSelectWell(well.uid);
                toggle(well.uid);
              }}
            >
              <ListItemIcon sx={{ minWidth: 36 }}>
                <OilBarrelIcon fontSize="small" />
              </ListItemIcon>
              <ListItemText
                primary={well.name}
                secondary={well.region ?? well.country ?? undefined}
              />
              {well.status && (
                <Chip
                  size="small"
                  label={well.status}
                  color={statusColor(well.status)}
                  sx={{ mr: 1 }}
                />
              )}
              {well.wellbores.length > 0 && (isOpen ? <ExpandLess /> : <ExpandMore />)}
            </ListItemButton>
            <Collapse in={isOpen} timeout="auto" unmountOnExit>
              <List dense disablePadding>
                {well.wellbores.map((wb) => (
                  <ListItemButton key={wb.uid} sx={{ pl: 6 }}>
                    <ListItemIcon sx={{ minWidth: 36 }}>
                      <RouteIcon fontSize="small" />
                    </ListItemIcon>
                    <ListItemText
                      primary={wb.name}
                      secondary={wb.purposeRange ?? undefined}
                    />
                    {wb.status && (
                      <Chip size="small" variant="outlined" label={wb.status} />
                    )}
                  </ListItemButton>
                ))}
              </List>
            </Collapse>
          </Box>
        );
      })}
    </List>
  );
}
