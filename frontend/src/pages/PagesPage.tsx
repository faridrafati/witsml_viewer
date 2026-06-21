import { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardActionArea,
  CardActions,
  CardContent,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  IconButton,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import DeleteIcon from '@mui/icons-material/Delete';

import {
  usePages,
  useCreatePage,
  useDeletePage,
  useDuplicatePage,
  type DashboardPageDto,
} from '../api/pages';
import { PageEditor } from './PageEditor';

/**
 * "Dynamic pages" hub (brief §7.5).
 *
 * Lists saved dashboard pages with create / duplicate / delete. Selecting a
 * page opens the in-place editor/viewer (PageEditor), which owns the live
 * stream and grid. This component is self-contained so a human can wire it
 * into the router/nav without touching App.tsx or Layout.tsx.
 */
export function PagesPage() {
  const { data: pages, isLoading, isError } = usePages();
  const createPage = useCreatePage();
  const deletePage = useDeletePage();
  const duplicatePage = useDuplicatePage();

  const [openId, setOpenId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState('');

  if (openId != null) {
    return <PageEditor pageId={openId} onBack={() => setOpenId(null)} />;
  }

  const handleCreate = () => {
    createPage.mutate(
      { name: newName.trim() || 'Untitled page', layout: { components: [] } },
      {
        onSuccess: (page) => {
          setCreateOpen(false);
          setNewName('');
          setOpenId(page.id);
        },
      },
    );
  };

  return (
    <Box>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 2,
          mb: 2,
        }}
      >
        <Typography variant="h5">Dashboard Pages</Typography>
        <Box sx={{ flex: 1 }} />
        <Button
          startIcon={<AddIcon />}
          variant="contained"
          onClick={() => setCreateOpen(true)}
        >
          New page
        </Button>
      </Box>

      {isLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
          <CircularProgress />
        </Box>
      )}
      {isError && <Alert severity="error">Could not load pages.</Alert>}

      {pages && pages.length === 0 && (
        <Alert severity="info">
          No pages yet. Create one to start building a live dashboard.
        </Alert>
      )}

      <Grid container spacing={2}>
        {(pages ?? []).map((p: DashboardPageDto) => {
          const count = p.layout?.components?.length ?? 0;
          return (
            <Grid item xs={12} sm={6} md={4} key={p.id}>
              <Card variant="outlined">
                <CardActionArea onClick={() => setOpenId(p.id)}>
                  <CardContent>
                    <Typography variant="h6" noWrap>
                      {p.name}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" noWrap>
                      {p.well_name ?? p.well_uid ?? 'No well bound'}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {count} component{count === 1 ? '' : 's'}
                    </Typography>
                  </CardContent>
                </CardActionArea>
                <CardActions>
                  <Tooltip title="Duplicate">
                    <IconButton
                      size="small"
                      onClick={() => duplicatePage.mutate({ id: p.id })}
                      disabled={duplicatePage.isPending}
                    >
                      <ContentCopyIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title="Delete">
                    <IconButton
                      size="small"
                      color="error"
                      onClick={() => {
                        if (
                          window.confirm(`Delete page "${p.name}"?`)
                        ) {
                          deletePage.mutate(p.id);
                        }
                      }}
                      disabled={deletePage.isPending}
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </CardActions>
              </Card>
            </Grid>
          );
        })}
      </Grid>

      <Dialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>New page</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            label="Page name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            fullWidth
            sx={{ mt: 1 }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleCreate();
            }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleCreate}
            disabled={createPage.isPending}
          >
            Create
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
