import { ReactNode } from 'react';
import { Link as RouterLink, useLocation } from 'react-router-dom';
import {
  AppBar,
  Box,
  Chip,
  CircularProgress,
  Drawer,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Toolbar,
  Typography,
} from '@mui/material';
import OilBarrelIcon from '@mui/icons-material/OilBarrel';
import DashboardIcon from '@mui/icons-material/Dashboard';
import CompareArrowsIcon from '@mui/icons-material/CompareArrows';
import FunctionsIcon from '@mui/icons-material/Functions';
import DescriptionIcon from '@mui/icons-material/Description';
import SettingsIcon from '@mui/icons-material/Settings';
import { useHealth } from '../api/queries';

const DRAWER_WIDTH = 240;

interface NavItem {
  label: string;
  to: string;
  icon: ReactNode;
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Wells', to: '/', icon: <OilBarrelIcon /> },
  { label: 'Dashboard', to: '/dashboard', icon: <DashboardIcon /> },
  { label: 'Comparison', to: '/comparison', icon: <CompareArrowsIcon /> },
  { label: 'Formulas', to: '/formulas', icon: <FunctionsIcon /> },
  { label: 'Reports', to: '/reports', icon: <DescriptionIcon /> },
  { label: 'Admin', to: '/admin', icon: <SettingsIcon /> },
];

function HealthChip() {
  const { data, isLoading, isError } = useHealth();

  if (isLoading) {
    return <Chip size="small" icon={<CircularProgress size={14} />} label="API…" />;
  }
  if (isError || data?.status !== 'ok') {
    const label = isError ? 'API offline' : `API: ${data?.status ?? 'unknown'}`;
    return <Chip size="small" color="error" label={label} />;
  }
  return <Chip size="small" color="success" label="API online" />;
}

export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <AppBar
        position="fixed"
        sx={{ zIndex: (t) => t.zIndex.drawer + 1 }}
      >
        <Toolbar>
          <OilBarrelIcon sx={{ mr: 1.5 }} />
          <Typography variant="h6" noWrap sx={{ flexGrow: 1 }}>
            WITSML Mudlogging Viewer
          </Typography>
          <HealthChip />
        </Toolbar>
      </AppBar>

      <Drawer
        variant="permanent"
        sx={{
          width: DRAWER_WIDTH,
          flexShrink: 0,
          '& .MuiDrawer-paper': { width: DRAWER_WIDTH, boxSizing: 'border-box' },
        }}
      >
        <Toolbar />
        <Box sx={{ overflow: 'auto' }}>
          <List>
            {NAV_ITEMS.map((item) => {
              const selected =
                item.to === '/'
                  ? location.pathname === '/'
                  : location.pathname.startsWith(item.to);
              return (
                <ListItemButton
                  key={item.to}
                  component={RouterLink}
                  to={item.to}
                  selected={selected}
                >
                  <ListItemIcon>{item.icon}</ListItemIcon>
                  <ListItemText primary={item.label} />
                </ListItemButton>
              );
            })}
          </List>
        </Box>
      </Drawer>

      <Box component="main" sx={{ flexGrow: 1, p: 3, width: `calc(100% - ${DRAWER_WIDTH}px)` }}>
        <Toolbar />
        {children}
      </Box>
    </Box>
  );
}
