import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import SaveIcon from '@mui/icons-material/Save';
import GridLayout, { type Layout } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';

import {
  useGetPage,
  useUpdatePage,
  type DashboardComponentConfig,
} from '../api/pages';
import { useIngestWells } from '../api/ingest';
import { useWellStream } from '../api/useWellStream';
import { DashboardComponent } from '../components/dashboard/DashboardComponent';
import { ComponentConfigDialog } from '../components/dashboard/ComponentConfigDialog';

export interface PageEditorProps {
  /** Page id to edit/view. */
  pageId: number;
  /** Optional: navigate back to the page list. */
  onBack?: () => void;
}

const COLS = 12;
const ROW_HEIGHT = 60;
const WIDTH = 1100;

/**
 * The dashboard builder, bound to one page.
 *
 * - Renders the page's components in a draggable/resizable react-grid-layout.
 * - "Add component" / per-component edit + remove via ComponentConfigDialog.
 * - A well selector binds `page.well_uid`.
 * - Opens ONE useWellStream(well_uid) and threads curves/rev into every
 *   DashboardComponent so the whole page updates live (5s cadence upstream).
 * - Save (PUT /api/pages/{id}) persists name/well + the full layout so a
 *   reload round-trips components and styles. Duplicate is offered from the
 *   list page (PagesPage).
 */
export function PageEditor({ pageId, onBack }: PageEditorProps) {
  const { data: page, isLoading, isError } = useGetPage(pageId);
  const { data: wells } = useIngestWells();
  const updatePage = useUpdatePage();

  // Working copy of the editable fields; seeded from the fetched page.
  const [name, setName] = useState('');
  const [wellUid, setWellUid] = useState<string | null>(null);
  const [components, setComponents] = useState<DashboardComponentConfig[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<DashboardComponentConfig | null>(null);

  useEffect(() => {
    if (!page) return;
    setName(page.name);
    setWellUid(page.well_uid ?? null);
    setComponents(page.layout?.components ?? []);
  }, [page]);

  // ONE shared subscription for the bound well; threaded into every component.
  const { status, curves, rev } = useWellStream(wellUid, 500);

  const gridLayout: Layout[] = useMemo(
    () =>
      components.map((c) => ({
        i: c.id,
        x: c.grid.x,
        y: c.grid.y,
        w: c.grid.w,
        h: c.grid.h,
        minW: 2,
        minH: 2,
      })),
    [components],
  );

  const handleLayoutChange = (next: Layout[]) => {
    setComponents((prev) =>
      prev.map((c) => {
        const l = next.find((n) => n.i === c.id);
        if (!l) return c;
        return { ...c, grid: { x: l.x, y: l.y, w: l.w, h: l.h } };
      }),
    );
  };

  const handleAdd = () => {
    setEditing(null);
    setDialogOpen(true);
  };

  const handleEdit = (c: DashboardComponentConfig) => {
    setEditing(c);
    setDialogOpen(true);
  };

  const handleRemove = (id: string) => {
    setComponents((prev) => prev.filter((c) => c.id !== id));
  };

  const handleDialogSave = (component: DashboardComponentConfig) => {
    setComponents((prev) => {
      const exists = prev.some((c) => c.id === component.id);
      if (exists) {
        return prev.map((c) => (c.id === component.id ? component : c));
      }
      // Place a new component below the current stack.
      const maxY = prev.reduce((m, c) => Math.max(m, c.grid.y + c.grid.h), 0);
      return [...prev, { ...component, grid: { ...component.grid, x: 0, y: maxY } }];
    });
  };

  const handleSave = () => {
    const selectedWell = wells?.find((w) => w.uid === wellUid);
    updatePage.mutate({
      id: pageId,
      body: {
        name: name.trim() || 'Untitled page',
        well_uid: wellUid,
        well_name: selectedWell?.name ?? null,
        layout: { components },
      },
    });
  };

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
        <CircularProgress />
      </Box>
    );
  }
  if (isError || !page) {
    return <Alert severity="error">Could not load page {pageId}.</Alert>;
  }

  return (
    <Box>
      <Stack
        direction={{ xs: 'column', md: 'row' }}
        spacing={2}
        alignItems={{ md: 'center' }}
        sx={{ mb: 2 }}
      >
        {onBack && (
          <Button onClick={onBack} variant="text">
            ← Pages
          </Button>
        )}
        <TextField
          label="Page name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          size="small"
          sx={{ minWidth: 220 }}
        />
        <TextField
          select
          label="Well"
          value={wellUid ?? ''}
          onChange={(e) => setWellUid(e.target.value || null)}
          size="small"
          sx={{ minWidth: 220 }}
        >
          <MenuItem value="">
            <em>None</em>
          </MenuItem>
          {(wells ?? []).map((w) => (
            <MenuItem key={w.uid} value={w.uid}>
              {w.name}
            </MenuItem>
          ))}
        </TextField>
        {wellUid && (
          <Chip
            size="small"
            color={status === 'open' ? 'success' : 'default'}
            label={status === 'open' ? 'Live' : 'Idle'}
          />
        )}
        <Box sx={{ flex: 1 }} />
        <Button startIcon={<AddIcon />} onClick={handleAdd} variant="outlined">
          Add component
        </Button>
        <Button
          startIcon={<SaveIcon />}
          onClick={handleSave}
          variant="contained"
          disabled={updatePage.isPending}
        >
          Save
        </Button>
      </Stack>

      {updatePage.isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Failed to save page.
        </Alert>
      )}
      {updatePage.isSuccess && (
        <Alert severity="success" sx={{ mb: 2 }}>
          Page saved.
        </Alert>
      )}

      {components.length === 0 ? (
        <Alert severity="info">
          No components yet. Use “Add component” to build this page.
        </Alert>
      ) : (
        <Box sx={{ overflowX: 'auto' }}>
          <GridLayout
            className="layout"
            layout={gridLayout}
            cols={COLS}
            rowHeight={ROW_HEIGHT}
            width={WIDTH}
            onLayoutChange={handleLayoutChange}
            draggableHandle=".drag-handle"
            compactType="vertical"
          >
            {components.map((c) => (
              <Box key={c.id} sx={{ height: '100%' }}>
                <Paper
                  variant="outlined"
                  sx={{
                    height: '100%',
                    display: 'flex',
                    flexDirection: 'column',
                    overflow: 'hidden',
                  }}
                >
                  <Box
                    className="drag-handle"
                    sx={{
                      display: 'flex',
                      alignItems: 'center',
                      px: 1,
                      py: 0.5,
                      cursor: 'move',
                      borderBottom: '1px solid',
                      borderColor: 'divider',
                      bgcolor: 'action.hover',
                    }}
                  >
                    <Typography variant="caption" noWrap sx={{ flex: 1 }}>
                      {c.title || c.mnemonics.join(', ') || c.type}
                    </Typography>
                    <Tooltip title="Edit">
                      <IconButton size="small" onClick={() => handleEdit(c)}>
                        <EditIcon fontSize="inherit" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Remove">
                      <IconButton
                        size="small"
                        onClick={() => handleRemove(c.id)}
                      >
                        <DeleteIcon fontSize="inherit" />
                      </IconButton>
                    </Tooltip>
                  </Box>
                  <Box sx={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
                    <DashboardComponent
                      config={c}
                      curves={curves}
                      rev={rev}
                      height={Math.max(80, c.grid.h * ROW_HEIGHT - 40)}
                    />
                  </Box>
                </Paper>
              </Box>
            ))}
          </GridLayout>
        </Box>
      )}

      <ComponentConfigDialog
        open={dialogOpen}
        initial={editing}
        onClose={() => setDialogOpen(false)}
        onSave={handleDialogSave}
      />
    </Box>
  );
}
