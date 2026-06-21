import { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  FormGroup,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Switch,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import EditIcon from '@mui/icons-material/Edit';
import LockIcon from '@mui/icons-material/Lock';

import { useAuthStore, type AccessLevel } from '../store/auth';
import {
  useUsers,
  useCreateUser,
  useUpdateUser,
  useDeleteUser,
  useSetUserPages,
  useServers,
  useCreateServer,
  useUpdateServer,
  useDeleteServer,
  useTestServer,
  useUnits,
  useCreateUnit,
  usePageSummaries,
  type AdminUser,
  type ServerConnection,
} from '../api/admin';

/**
 * Admin console (brief §7). Three tabs: Users, Server Connections, Units.
 *
 * Gated client-side on the auth store's access level; the backend enforces the
 * real authorization. Self-contained so a human can wire it into the router/nav
 * without touching App.tsx or Layout.tsx.
 */
export function AdminPage() {
  const isAdmin = useAuthStore((s) => s.isAdmin());
  const [tab, setTab] = useState(0);

  if (!isAdmin) {
    return (
      <Box sx={{ p: 4, display: 'flex', justifyContent: 'center' }}>
        <Alert severity="warning" icon={<LockIcon />}>
          You are not authorized to view the admin console. An administrator
          account is required.
        </Alert>
      </Box>
    );
  }

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>
        Administration
      </Typography>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Users" />
        <Tab label="Server Connections" />
        <Tab label="Units" />
      </Tabs>
      {tab === 0 && <UsersTab />}
      {tab === 1 && <ServersTab />}
      {tab === 2 && <UnitsTab />}
    </Box>
  );
}

/* ================================================================== */
/* Users tab                                                          */
/* ================================================================== */

const ACCESS_LEVELS: AccessLevel[] = ['normal', 'admin', 'super_admin'];

interface UserFormState {
  username: string;
  password: string;
  first_name: string;
  last_name: string;
  phone: string;
  position: string;
  access_level: AccessLevel;
  is_active: boolean;
}

function emptyUserForm(): UserFormState {
  return {
    username: '',
    password: '',
    first_name: '',
    last_name: '',
    phone: '',
    position: '',
    access_level: 'normal',
    is_active: true,
  };
}

function UsersTab() {
  const { data: users, isLoading, isError } = useUsers();
  const { data: pages } = usePageSummaries();
  const createUser = useCreateUser();
  const updateUser = useUpdateUser();
  const deleteUser = useDeleteUser();
  const setUserPages = useSetUserPages();

  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<UserFormState>(emptyUserForm());
  const [grantUser, setGrantUser] = useState<AdminUser | null>(null);
  const [grantIds, setGrantIds] = useState<number[]>([]);
  const [formError, setFormError] = useState<string | null>(null);

  const openCreate = () => {
    setEditing(null);
    setForm(emptyUserForm());
    setFormError(null);
    setDialogOpen(true);
  };

  const openEdit = (u: AdminUser) => {
    setEditing(u);
    setForm({
      username: u.username,
      password: '',
      first_name: u.first_name ?? '',
      last_name: u.last_name ?? '',
      phone: u.phone ?? '',
      position: u.position ?? '',
      access_level: u.access_level,
      is_active: u.is_active,
    });
    setFormError(null);
    setDialogOpen(true);
  };

  const handleSave = () => {
    setFormError(null);
    const onError = () => setFormError('Could not save user. Check the fields and try again.');
    if (editing) {
      updateUser.mutate(
        {
          id: editing.id,
          body: {
            first_name: form.first_name || null,
            last_name: form.last_name || null,
            phone: form.phone || null,
            position: form.position || null,
            access_level: form.access_level,
            is_active: form.is_active,
            ...(form.password ? { password: form.password } : {}),
          },
        },
        { onSuccess: () => setDialogOpen(false), onError },
      );
    } else {
      createUser.mutate(
        {
          username: form.username.trim(),
          password: form.password,
          first_name: form.first_name || null,
          last_name: form.last_name || null,
          phone: form.phone || null,
          position: form.position || null,
          access_level: form.access_level,
          is_active: form.is_active,
        },
        { onSuccess: () => setDialogOpen(false), onError },
      );
    }
  };

  const openGrants = (u: AdminUser) => {
    setGrantUser(u);
    setGrantIds(u.page_grants ?? []);
  };

  const toggleGrant = (pageId: number) => {
    setGrantIds((prev) =>
      prev.includes(pageId) ? prev.filter((id) => id !== pageId) : [...prev, pageId],
    );
  };

  const saveGrants = () => {
    if (!grantUser) return;
    setUserPages.mutate(
      { id: grantUser.id, pageIds: grantIds },
      { onSuccess: () => setGrantUser(null) },
    );
  };

  if (isLoading) return <Loading />;
  if (isError) return <Alert severity="error">Could not load users.</Alert>;

  return (
    <Box>
      <Box sx={{ display: 'flex', mb: 2 }}>
        <Box sx={{ flex: 1 }} />
        <Button startIcon={<AddIcon />} variant="contained" onClick={openCreate}>
          New user
        </Button>
      </Box>

      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Username</TableCell>
            <TableCell>Name</TableCell>
            <TableCell>Access</TableCell>
            <TableCell>Active</TableCell>
            <TableCell align="right">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {(users ?? []).map((u) => (
            <TableRow key={u.id}>
              <TableCell>{u.username}</TableCell>
              <TableCell>
                {[u.first_name, u.last_name].filter(Boolean).join(' ') || '—'}
              </TableCell>
              <TableCell>
                <Chip
                  size="small"
                  label={u.access_level}
                  color={u.access_level === 'normal' ? 'default' : 'primary'}
                />
              </TableCell>
              <TableCell>{u.is_active ? 'Yes' : 'No'}</TableCell>
              <TableCell align="right">
                <Tooltip title="Page grants">
                  <Button size="small" onClick={() => openGrants(u)}>
                    Pages
                  </Button>
                </Tooltip>
                <Tooltip title="Edit">
                  <IconButton size="small" onClick={() => openEdit(u)}>
                    <EditIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
                <Tooltip title="Delete">
                  <IconButton
                    size="small"
                    color="error"
                    onClick={() => {
                      if (window.confirm(`Delete user "${u.username}"?`)) {
                        deleteUser.mutate(u.id);
                      }
                    }}
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </TableCell>
            </TableRow>
          ))}
          {users && users.length === 0 && (
            <TableRow>
              <TableCell colSpan={5}>
                <Typography color="text.secondary">No users yet.</Typography>
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      {/* Create / edit dialog */}
      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{editing ? `Edit ${editing.username}` : 'New user'}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {formError && <Alert severity="error">{formError}</Alert>}
            <TextField
              label="Username"
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              disabled={!!editing}
              fullWidth
            />
            <TextField
              label={editing ? 'New password (leave blank to keep)' : 'Password'}
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              fullWidth
            />
            <Stack direction="row" spacing={2}>
              <TextField
                label="First name"
                value={form.first_name}
                onChange={(e) => setForm({ ...form, first_name: e.target.value })}
                fullWidth
              />
              <TextField
                label="Last name"
                value={form.last_name}
                onChange={(e) => setForm({ ...form, last_name: e.target.value })}
                fullWidth
              />
            </Stack>
            <Stack direction="row" spacing={2}>
              <TextField
                label="Phone"
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
                fullWidth
              />
              <TextField
                label="Position"
                value={form.position}
                onChange={(e) => setForm({ ...form, position: e.target.value })}
                fullWidth
              />
            </Stack>
            <FormControl fullWidth>
              <InputLabel id="access-level-label">Access level</InputLabel>
              <Select
                labelId="access-level-label"
                label="Access level"
                value={form.access_level}
                onChange={(e) =>
                  setForm({ ...form, access_level: e.target.value as AccessLevel })
                }
              >
                {ACCESS_LEVELS.map((lvl) => (
                  <MenuItem key={lvl} value={lvl}>
                    {lvl}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControlLabel
              control={
                <Switch
                  checked={form.is_active}
                  onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                />
              }
              label="Active"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleSave}
            disabled={
              createUser.isPending ||
              updateUser.isPending ||
              (!editing && (!form.username.trim() || !form.password))
            }
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>

      {/* Page grants dialog */}
      <Dialog open={!!grantUser} onClose={() => setGrantUser(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Page grants — {grantUser?.username}</DialogTitle>
        <DialogContent>
          {!pages || pages.length === 0 ? (
            <Typography color="text.secondary">No pages available.</Typography>
          ) : (
            <FormGroup>
              {pages.map((p) => (
                <FormControlLabel
                  key={p.id}
                  control={
                    <Checkbox
                      checked={grantIds.includes(p.id)}
                      onChange={() => toggleGrant(p.id)}
                    />
                  }
                  label={p.name}
                />
              ))}
            </FormGroup>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setGrantUser(null)}>Cancel</Button>
          <Button variant="contained" onClick={saveGrants} disabled={setUserPages.isPending}>
            Save grants
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

/* ================================================================== */
/* Servers tab                                                        */
/* ================================================================== */

interface ServerFormState {
  name: string;
  url: string;
  username: string;
  password: string;
  verify_ssl: boolean;
}

function emptyServerForm(): ServerFormState {
  return { name: '', url: '', username: '', password: '', verify_ssl: true };
}

function ServersTab() {
  const { data: servers, isLoading, isError } = useServers();
  const createServer = useCreateServer();
  const updateServer = useUpdateServer();
  const deleteServer = useDeleteServer();
  const testServer = useTestServer();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ServerConnection | null>(null);
  const [form, setForm] = useState<ServerFormState>(emptyServerForm());
  const [testResult, setTestResult] = useState<{ id: number; ok: boolean; text: string } | null>(
    null,
  );

  const openCreate = () => {
    setEditing(null);
    setForm(emptyServerForm());
    setDialogOpen(true);
  };

  const openEdit = (s: ServerConnection) => {
    setEditing(s);
    setForm({
      name: s.name,
      url: s.url,
      username: s.username,
      password: '',
      verify_ssl: s.verify_ssl,
    });
    setDialogOpen(true);
  };

  const handleSave = () => {
    if (editing) {
      updateServer.mutate(
        {
          id: editing.id,
          body: {
            name: form.name,
            url: form.url,
            username: form.username,
            verify_ssl: form.verify_ssl,
            ...(form.password ? { password: form.password } : {}),
          },
        },
        { onSuccess: () => setDialogOpen(false) },
      );
    } else {
      createServer.mutate(
        {
          name: form.name.trim(),
          url: form.url.trim(),
          username: form.username.trim(),
          password: form.password,
          verify_ssl: form.verify_ssl,
        },
        { onSuccess: () => setDialogOpen(false) },
      );
    }
  };

  const runTest = (id: number) => {
    setTestResult(null);
    testServer.mutate(id, {
      onSuccess: (res) => {
        setTestResult({
          id,
          ok: res.ok,
          text: res.ok
            ? `Connected${res.version ? ` (v${res.version})` : ''}`
            : res.detail ?? 'Connection failed',
        });
      },
      onError: () => setTestResult({ id, ok: false, text: 'Connection failed' }),
    });
  };

  if (isLoading) return <Loading />;
  if (isError) return <Alert severity="error">Could not load server connections.</Alert>;

  return (
    <Box>
      <Box sx={{ display: 'flex', mb: 2 }}>
        <Box sx={{ flex: 1 }} />
        <Button startIcon={<AddIcon />} variant="contained" onClick={openCreate}>
          New connection
        </Button>
      </Box>

      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Name</TableCell>
            <TableCell>URL</TableCell>
            <TableCell>Username</TableCell>
            <TableCell>SSL</TableCell>
            <TableCell align="right">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {(servers ?? []).map((s) => (
            <TableRow key={s.id}>
              <TableCell>{s.name}</TableCell>
              <TableCell sx={{ maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {s.url}
              </TableCell>
              <TableCell>{s.username}</TableCell>
              <TableCell>{s.verify_ssl ? 'Verify' : 'Skip'}</TableCell>
              <TableCell align="right">
                <Button
                  size="small"
                  onClick={() => runTest(s.id)}
                  disabled={testServer.isPending}
                >
                  Test
                </Button>
                <Tooltip title="Edit">
                  <IconButton size="small" onClick={() => openEdit(s)}>
                    <EditIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
                <Tooltip title="Delete">
                  <IconButton
                    size="small"
                    color="error"
                    onClick={() => {
                      if (window.confirm(`Delete connection "${s.name}"?`)) {
                        deleteServer.mutate(s.id);
                      }
                    }}
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </TableCell>
            </TableRow>
          ))}
          {servers && servers.length === 0 && (
            <TableRow>
              <TableCell colSpan={5}>
                <Typography color="text.secondary">No connections yet.</Typography>
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      {testResult && (
        <Alert severity={testResult.ok ? 'success' : 'error'} sx={{ mt: 2 }}>
          Connection #{testResult.id}: {testResult.text}
        </Alert>
      )}

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{editing ? `Edit ${editing.name}` : 'New connection'}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="Name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              fullWidth
            />
            <TextField
              label="WITSML URL"
              value={form.url}
              onChange={(e) => setForm({ ...form, url: e.target.value })}
              fullWidth
            />
            <TextField
              label="Username"
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              fullWidth
            />
            <TextField
              label={editing ? 'Password (leave blank to keep)' : 'Password'}
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              fullWidth
            />
            <FormControlLabel
              control={
                <Switch
                  checked={form.verify_ssl}
                  onChange={(e) => setForm({ ...form, verify_ssl: e.target.checked })}
                />
              }
              label="Verify SSL certificate"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleSave}
            disabled={
              createServer.isPending ||
              updateServer.isPending ||
              !form.name.trim() ||
              !form.url.trim()
            }
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

/* ================================================================== */
/* Units tab                                                          */
/* ================================================================== */

interface UnitFormState {
  name: string;
  from_unit: string;
  to_unit: string;
  expression: string;
}

function UnitsTab() {
  const { data: units, isLoading, isError } = useUnits();
  const createUnit = useCreateUnit();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<UnitFormState>({
    name: '',
    from_unit: '',
    to_unit: '',
    expression: '',
  });
  const [error, setError] = useState<string | null>(null);

  const handleCreate = () => {
    setError(null);
    createUnit.mutate(
      {
        name: form.name.trim(),
        from_unit: form.from_unit.trim(),
        to_unit: form.to_unit.trim(),
        expression: form.expression.trim(),
      },
      {
        onSuccess: () => {
          setDialogOpen(false);
          setForm({ name: '', from_unit: '', to_unit: '', expression: '' });
        },
        onError: () =>
          setError('Could not create unit. The expression may be invalid or a duplicate.'),
      },
    );
  };

  if (isLoading) return <Loading />;
  if (isError) return <Alert severity="error">Could not load units.</Alert>;

  return (
    <Box>
      <Box sx={{ display: 'flex', mb: 2 }}>
        <Box sx={{ flex: 1 }} />
        <Button
          startIcon={<AddIcon />}
          variant="contained"
          onClick={() => {
            setError(null);
            setDialogOpen(true);
          }}
        >
          New unit
        </Button>
      </Box>

      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Name</TableCell>
            <TableCell>From</TableCell>
            <TableCell>To</TableCell>
            <TableCell>Expression</TableCell>
            <TableCell>Built-in</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {(units ?? []).map((u) => (
            <TableRow key={u.id}>
              <TableCell>{u.name}</TableCell>
              <TableCell>{u.from_unit}</TableCell>
              <TableCell>{u.to_unit}</TableCell>
              <TableCell>
                <code>{u.expression}</code>
              </TableCell>
              <TableCell>{u.is_builtin ? 'Yes' : 'No'}</TableCell>
            </TableRow>
          ))}
          {units && units.length === 0 && (
            <TableRow>
              <TableCell colSpan={5}>
                <Typography color="text.secondary">No units defined yet.</Typography>
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New unit definition</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField
              label="Name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              fullWidth
            />
            <Stack direction="row" spacing={2}>
              <TextField
                label="From unit"
                value={form.from_unit}
                onChange={(e) => setForm({ ...form, from_unit: e.target.value })}
                fullWidth
              />
              <TextField
                label="To unit"
                value={form.to_unit}
                onChange={(e) => setForm({ ...form, to_unit: e.target.value })}
                fullWidth
              />
            </Stack>
            <TextField
              label="Expression"
              helperText="Use __value__ for the input, e.g. __value__ * 3.28084"
              value={form.expression}
              onChange={(e) => setForm({ ...form, expression: e.target.value })}
              fullWidth
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleCreate}
            disabled={
              createUnit.isPending ||
              !form.name.trim() ||
              !form.from_unit.trim() ||
              !form.to_unit.trim() ||
              !form.expression.trim()
            }
          >
            Create
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

/* ================================================================== */
/* Shared bits                                                        */
/* ================================================================== */

function Loading() {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
      <CircularProgress />
    </Box>
  );
}

/**
 * Convenience hook left intentionally exported for callers that mount the
 * admin page lazily and want to ensure the session is hydrated. No-op when a
 * user is already present.
 */
export function useEnsureSession(refresh: () => void) {
  const hasUser = useAuthStore((s) => !!s.user);
  useEffect(() => {
    if (!hasUser) refresh();
  }, [hasUser, refresh]);
}
