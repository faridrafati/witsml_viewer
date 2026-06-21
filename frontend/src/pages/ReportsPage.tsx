import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  List,
  ListItemButton,
  ListItemText,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import PlaceIcon from '@mui/icons-material/Place';
import ReplayIcon from '@mui/icons-material/Replay';
import SaveIcon from '@mui/icons-material/Save';
import FileDownloadIcon from '@mui/icons-material/FileDownload';
import {
  saveRemarksXlsx,
  useCreateDepth,
  useCreateSavedSearch,
  useDeleteSavedSearch,
  useMudProperties,
  useRemarks,
  useReports,
  useRunSavedSearch,
  useSavedSearches,
  type RemarkRow,
  type ReportFilters,
  type ReportRow,
} from '../api/reports';
import { useWellList } from '../api/comparison';

/* ------------------------------------------------------------------ */
/* Sub-navigation                                                      */
/* ------------------------------------------------------------------ */

type SectionId =
  | 'remarks'
  | 'mud-properties'
  | 'mud-stock'
  | 'well-path'
  | 'time-analysis'
  | 'tools';

interface SectionDef {
  id: SectionId;
  label: string;
  /** SCAFFOLD sections show a "coming soon" placeholder. */
  scaffold: boolean;
}

const SECTIONS: SectionDef[] = [
  { id: 'remarks', label: 'Remarks & Summary', scaffold: false },
  { id: 'mud-properties', label: 'Mud Properties', scaffold: false },
  { id: 'mud-stock', label: 'Mud Stock', scaffold: true },
  { id: 'well-path', label: 'Well Path', scaffold: true },
  { id: 'time-analysis', label: 'Time Analysis', scaffold: true },
  { id: 'tools', label: 'Tools', scaffold: true },
];

/* ------------------------------------------------------------------ */
/* Small helpers                                                       */
/* ------------------------------------------------------------------ */

const fmtNum = (n: number | null | undefined): string =>
  n == null ? '—' : Number(n).toLocaleString();

const dash = (s: string | null | undefined): string =>
  s == null || s === '' ? '—' : s;

/** Build a stable filename for the remarks export. */
function exportFilename(keyword: string): string {
  const stamp = new Date().toISOString().slice(0, 10);
  const kw = keyword.trim().replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '');
  return kw ? `remarks-${kw}-${stamp}.xlsx` : `remarks-${stamp}.xlsx`;
}

/* ================================================================== */
/* Filter bar (shared by Remarks and Mud Properties)                   */
/* ================================================================== */

interface FilterBarProps {
  filters: ReportFilters;
  onChange: (next: ReportFilters) => void;
  wellOptions: { uid: string; name: string }[];
  /** Optional keyword box (only the Remarks section uses it). */
  keyword?: string;
  onKeywordChange?: (kw: string) => void;
}

function FilterBar({
  filters,
  onChange,
  wellOptions,
  keyword,
  onKeywordChange,
}: FilterBarProps) {
  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
      <Stack
        direction="row"
        spacing={2}
        sx={{ flexWrap: 'wrap', gap: 2, alignItems: 'flex-start' }}
      >
        {onKeywordChange && (
          <TextField
            size="small"
            label="Keyword"
            placeholder="Search remarks…"
            value={keyword ?? ''}
            onChange={(e) => onKeywordChange(e.target.value)}
            sx={{ minWidth: 220 }}
          />
        )}
        <TextField
          size="small"
          label="Field / section"
          placeholder="e.g. GEOLOGY"
          value={filters.field ?? ''}
          onChange={(e) =>
            onChange({ ...filters, field: e.target.value || null })
          }
          sx={{ minWidth: 180 }}
        />
        <TextField
          select
          size="small"
          label="Well"
          value={filters.wellUid ?? ''}
          onChange={(e) =>
            onChange({ ...filters, wellUid: e.target.value || null })
          }
          SelectProps={{ native: true }}
          sx={{ minWidth: 200 }}
          InputLabelProps={{ shrink: true }}
        >
          <option value="">All wells</option>
          {wellOptions.map((w) => (
            <option key={w.uid} value={w.uid}>
              {w.name}
            </option>
          ))}
        </TextField>
        <TextField
          size="small"
          type="date"
          label="From"
          value={filters.dateFrom ?? ''}
          onChange={(e) =>
            onChange({ ...filters, dateFrom: e.target.value || null })
          }
          InputLabelProps={{ shrink: true }}
        />
        <TextField
          size="small"
          type="date"
          label="To"
          value={filters.dateTo ?? ''}
          onChange={(e) =>
            onChange({ ...filters, dateTo: e.target.value || null })
          }
          InputLabelProps={{ shrink: true }}
        />
      </Stack>
    </Paper>
  );
}

/* ================================================================== */
/* Remarks & Summary section                                           */
/* ================================================================== */

interface RemarksSectionProps {
  wellOptions: { uid: string; name: string }[];
  wellNameByUid: Map<string, string>;
}

function RemarksSection({ wellOptions, wellNameByUid }: RemarksSectionProps) {
  const [keyword, setKeyword] = useState('');
  const [filters, setFilters] = useState<ReportFilters>({});

  // Saved-search dialog state.
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState('');

  // Depth-of-interest dialog state (per row).
  const [depthRow, setDepthRow] = useState<RemarkRow | null>(null);
  const [depthMd, setDepthMd] = useState('');
  const [depthNote, setDepthNote] = useState('');

  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const remarks = useRemarks(keyword, filters);
  const reports = useReports(filters);
  const savedSearches = useSavedSearches();

  const createSavedSearch = useCreateSavedSearch();
  const deleteSavedSearch = useDeleteSavedSearch();
  const runSavedSearch = useRunSavedSearch();
  const createDepth = useCreateDepth();

  // Report context lookup so each remark can show its report title/date.
  const reportById = useMemo(() => {
    const m = new Map<number, ReportRow>();
    for (const r of reports.data ?? []) m.set(r.id, r);
    return m;
  }, [reports.data]);

  // Results: either the live keyword search, or the result of re-running a
  // saved search (which replaces the table until the keyword changes).
  const rows: RemarkRow[] = runSavedSearch.data ?? remarks.data ?? [];

  const handleSaveSearch = () => {
    if (!saveName.trim()) return;
    createSavedSearch.mutate(
      { name: saveName.trim(), keyword, filters },
      {
        onSuccess: () => {
          setSaveOpen(false);
          setSaveName('');
        },
      },
    );
  };

  const openDepthDialog = (row: RemarkRow) => {
    setDepthRow(row);
    setDepthMd(row.md != null ? String(row.md) : '');
    setDepthNote('');
  };

  const handleSaveDepth = () => {
    if (!depthRow) return;
    const md = Number(depthMd);
    if (!Number.isFinite(md)) return;
    createDepth.mutate(
      {
        wellUid: depthRow.wellUid,
        wellName: depthRow.wellName ?? wellNameByUid.get(depthRow.wellUid),
        md,
        mdUom: depthRow.mdUom ?? null,
        note: depthNote.trim() || null,
        remarkId: depthRow.id,
      },
      { onSuccess: () => setDepthRow(null) },
    );
  };

  const handleExport = async () => {
    setExporting(true);
    setExportError(null);
    try {
      await saveRemarksXlsx({ keyword, ...filters }, exportFilename(keyword));
    } catch (e) {
      setExportError((e as Error)?.message ?? 'Export failed');
    } finally {
      setExporting(false);
    }
  };

  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        Remarks &amp; Summary
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        Search report remarks by keyword, save useful searches to re-run, flag
        depths of interest, and export the results to Excel.
      </Typography>

      <FilterBar
        filters={filters}
        onChange={(next) => {
          setFilters(next);
          runSavedSearch.reset();
        }}
        wellOptions={wellOptions}
        keyword={keyword}
        onKeywordChange={(kw) => {
          setKeyword(kw);
          runSavedSearch.reset();
        }}
      />

      <Stack direction="row" spacing={1} sx={{ mb: 2, flexWrap: 'wrap', gap: 1 }}>
        <Button
          variant="outlined"
          startIcon={<SaveIcon />}
          onClick={() => setSaveOpen(true)}
        >
          Save this search
        </Button>
        <Button
          variant="outlined"
          startIcon={
            exporting ? <CircularProgress size={16} /> : <FileDownloadIcon />
          }
          disabled={exporting || rows.length === 0}
          onClick={() => void handleExport()}
        >
          Export to Excel
        </Button>
      </Stack>

      {exportError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setExportError(null)}>
          {exportError}
        </Alert>
      )}

      {/* Saved searches list with re-run. */}
      {(savedSearches.data?.length ?? 0) > 0 && (
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Typography variant="subtitle2" gutterBottom>
            Saved searches
          </Typography>
          <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}>
            {savedSearches.data?.map((s) => (
              <Chip
                key={s.id}
                label={s.name}
                onClick={() => runSavedSearch.mutate(s.id)}
                onDelete={() => deleteSavedSearch.mutate(s.id)}
                icon={<ReplayIcon />}
                variant="outlined"
              />
            ))}
          </Stack>
          {runSavedSearch.isPending && (
            <Typography variant="caption" color="text.secondary">
              Running saved search…
            </Typography>
          )}
        </Paper>
      )}

      {/* Result banners. */}
      {remarks.isError && !runSavedSearch.data && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Failed to load remarks:{' '}
          {(remarks.error as Error)?.message ?? 'unknown error'}
        </Alert>
      )}

      {remarks.isLoading && !runSavedSearch.data && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, p: 2 }}>
          <CircularProgress size={20} />
          <Typography color="text.secondary">Loading remarks…</Typography>
        </Box>
      )}

      {/* Results table with report context. */}
      <TableContainer component={Paper} variant="outlined">
        <Table size="small" stickyHeader aria-label="Remarks results">
          <TableHead>
            <TableRow>
              <TableCell>Date</TableCell>
              <TableCell>Well</TableCell>
              <TableCell>Field</TableCell>
              <TableCell>Report</TableCell>
              <TableCell align="right">MD</TableCell>
              <TableCell>Remark</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.length === 0 && !remarks.isLoading && (
              <TableRow>
                <TableCell colSpan={7}>
                  <Typography color="text.secondary" variant="body2">
                    No remarks match the current search.
                  </Typography>
                </TableCell>
              </TableRow>
            )}
            {rows.map((r) => {
              const report = reportById.get(r.reportId);
              const wellName =
                r.wellName ?? wellNameByUid.get(r.wellUid) ?? r.wellUid;
              return (
                <TableRow key={r.id} hover>
                  <TableCell>{dash(r.reportDate)}</TableCell>
                  <TableCell>{wellName}</TableCell>
                  <TableCell>{dash(r.field)}</TableCell>
                  <TableCell>
                    {report ? (
                      <Tooltip
                        title={`Report #${report.id} — ${dash(report.reportDate)}`}
                      >
                        <span>{dash(report.title) || `#${report.id}`}</span>
                      </Tooltip>
                    ) : (
                      `#${r.reportId}`
                    )}
                  </TableCell>
                  <TableCell align="right">
                    {r.md == null ? '—' : `${fmtNum(r.md)} ${r.mdUom ?? ''}`}
                  </TableCell>
                  <TableCell>{r.text}</TableCell>
                  <TableCell align="right">
                    <Tooltip title="Save depth of interest">
                      <span>
                        <IconButton
                          size="small"
                          onClick={() => openDepthDialog(r)}
                        >
                          <PlaceIcon fontSize="small" />
                        </IconButton>
                      </span>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Save-this-search dialog. */}
      <Dialog open={saveOpen} onClose={() => setSaveOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>Save this search</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            margin="dense"
            label="Name"
            value={saveName}
            onChange={(e) => setSaveName(e.target.value)}
            helperText="Captures the current keyword and filters."
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSaveOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!saveName.trim() || createSavedSearch.isPending}
            onClick={handleSaveSearch}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>

      {/* Save-depth-of-interest dialog. */}
      <Dialog
        open={depthRow != null}
        onClose={() => setDepthRow(null)}
        fullWidth
        maxWidth="xs"
      >
        <DialogTitle>Save depth of interest</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            {depthRow
              ? depthRow.wellName ??
                wellNameByUid.get(depthRow.wellUid) ??
                depthRow.wellUid
              : ''}
          </Typography>
          <TextField
            fullWidth
            margin="dense"
            type="number"
            label={`Measured depth${depthRow?.mdUom ? ` (${depthRow.mdUom})` : ''}`}
            value={depthMd}
            onChange={(e) => setDepthMd(e.target.value)}
          />
          <TextField
            fullWidth
            margin="dense"
            label="Note"
            multiline
            minRows={2}
            value={depthNote}
            onChange={(e) => setDepthNote(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDepthRow(null)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!Number.isFinite(Number(depthMd)) || createDepth.isPending}
            onClick={handleSaveDepth}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

/* ================================================================== */
/* Mud Properties section                                              */
/* ================================================================== */

interface MudPropertiesSectionProps {
  wellOptions: { uid: string; name: string }[];
  wellNameByUid: Map<string, string>;
}

function MudPropertiesSection({
  wellOptions,
  wellNameByUid,
}: MudPropertiesSectionProps) {
  const [filters, setFilters] = useState<ReportFilters>({});
  const mud = useMudProperties(filters);
  const rows = mud.data ?? [];

  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        Mud Properties
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        Drilling-fluid spec by report and well.
      </Typography>

      <FilterBar filters={filters} onChange={setFilters} wellOptions={wellOptions} />

      {mud.isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Failed to load mud properties:{' '}
          {(mud.error as Error)?.message ?? 'unknown error'}
        </Alert>
      )}

      {mud.isLoading && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, p: 2 }}>
          <CircularProgress size={20} />
          <Typography color="text.secondary">Loading mud properties…</Typography>
        </Box>
      )}

      <TableContainer component={Paper} variant="outlined">
        <Table size="small" stickyHeader aria-label="Mud properties">
          <TableHead>
            <TableRow>
              <TableCell>Date</TableCell>
              <TableCell>Well</TableCell>
              <TableCell align="right">MD</TableCell>
              <TableCell>Fluid</TableCell>
              <TableCell align="right">Density</TableCell>
              <TableCell align="right">Visc.</TableCell>
              <TableCell align="right">PV</TableCell>
              <TableCell align="right">YP</TableCell>
              <TableCell align="right">pH</TableCell>
              <TableCell align="right">Cl⁻</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.length === 0 && !mud.isLoading && (
              <TableRow>
                <TableCell colSpan={10}>
                  <Typography color="text.secondary" variant="body2">
                    No mud property records match the current filters.
                  </Typography>
                </TableCell>
              </TableRow>
            )}
            {rows.map((r) => (
              <TableRow key={r.id} hover>
                <TableCell>{dash(r.reportDate)}</TableCell>
                <TableCell>
                  {r.wellName ?? wellNameByUid.get(r.wellUid) ?? r.wellUid}
                </TableCell>
                <TableCell align="right">
                  {r.md == null ? '—' : `${fmtNum(r.md)} ${r.mdUom ?? ''}`}
                </TableCell>
                <TableCell>{dash(r.fluidType)}</TableCell>
                <TableCell align="right">
                  {r.density == null
                    ? '—'
                    : `${fmtNum(r.density)} ${r.densityUom ?? ''}`}
                </TableCell>
                <TableCell align="right">
                  {r.viscosity == null
                    ? '—'
                    : `${fmtNum(r.viscosity)} ${r.viscosityUom ?? ''}`}
                </TableCell>
                <TableCell align="right">{fmtNum(r.pv)}</TableCell>
                <TableCell align="right">{fmtNum(r.yp)}</TableCell>
                <TableCell align="right">{fmtNum(r.ph)}</TableCell>
                <TableCell align="right">{fmtNum(r.chlorides)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
}

/* ================================================================== */
/* Scaffold placeholder                                                */
/* ================================================================== */

function ScaffoldSection({ label }: { label: string }) {
  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        {label}
      </Typography>
      <Paper
        variant="outlined"
        sx={{
          p: 6,
          textAlign: 'center',
          color: 'text.secondary',
        }}
      >
        <Typography variant="subtitle1">Coming soon</Typography>
        <Typography variant="body2">
          The {label} report is not available yet.
        </Typography>
      </Paper>
    </Box>
  );
}

/* ================================================================== */
/* Module shell                                                        */
/* ================================================================== */

/**
 * Reporting module (brief §7.11).
 *
 * A self-contained shell with a left sub-nav. Two sections are fully
 * implemented — "Remarks & Summary" (keyword search + filters, results with
 * report context, save-search, save-depth, Excel export) and "Mud Properties"
 * (drilling-fluid spec table) — and the rest are routed scaffolds.
 */
export function ReportsPage() {
  const [section, setSection] = useState<SectionId>('remarks');
  const wellList = useWellList();

  const wellOptions = useMemo(
    () =>
      (wellList.data ?? []).map((w) => ({
        uid: w.uid,
        name: w.name ?? w.uid,
      })),
    [wellList.data],
  );
  const wellNameByUid = useMemo(() => {
    const m = new Map<string, string>();
    for (const w of wellOptions) m.set(w.uid, w.name);
    return m;
  }, [wellOptions]);

  const active = SECTIONS.find((s) => s.id === section) ?? SECTIONS[0];

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        Reporting
      </Typography>

      <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start' }}>
        {/* Left sub-nav. */}
        <Paper variant="outlined" sx={{ width: 220, flexShrink: 0 }}>
          <List dense disablePadding>
            {SECTIONS.map((s, i) => (
              <Box key={s.id}>
                {i > 0 && <Divider component="li" />}
                <ListItemButton
                  selected={s.id === section}
                  onClick={() => setSection(s.id)}
                >
                  <ListItemText
                    primary={s.label}
                    secondary={s.scaffold ? 'Coming soon' : undefined}
                  />
                </ListItemButton>
              </Box>
            ))}
          </List>
        </Paper>

        {/* Active section body. */}
        <Box sx={{ flex: 1, minWidth: 0 }}>
          {active.scaffold ? (
            <ScaffoldSection label={active.label} />
          ) : section === 'remarks' ? (
            <RemarksSection
              wellOptions={wellOptions}
              wellNameByUid={wellNameByUid}
            />
          ) : (
            <MudPropertiesSection
              wellOptions={wellOptions}
              wellNameByUid={wellNameByUid}
            />
          )}
        </Box>
      </Box>
    </Box>
  );
}
