import { createTheme } from '@mui/material/styles';

/**
 * Centralized MUI dark theme for the WITSML viewer.
 * Tweak palette / typography here only.
 */
export const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: '#4fc3f7',
    },
    secondary: {
      main: '#ffb74d',
    },
    background: {
      default: '#0e1116',
      paper: '#161b22',
    },
    success: { main: '#66bb6a' },
    error: { main: '#ef5350' },
    warning: { main: '#ffa726' },
  },
  shape: {
    borderRadius: 8,
  },
  typography: {
    fontFamily:
      '"Inter", "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    h6: { fontWeight: 600 },
  },
  components: {
    MuiAppBar: {
      defaultProps: { elevation: 0 },
      styleOverrides: {
        root: {
          borderBottom: '1px solid rgba(255,255,255,0.08)',
          backgroundColor: '#161b22',
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: '#10151c',
          borderRight: '1px solid rgba(255,255,255,0.08)',
        },
      },
    },
  },
});
