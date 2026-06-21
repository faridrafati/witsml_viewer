import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Autocomplete,
  Box,
  Chip,
  CircularProgress,
  FormControlLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import {
  MAX_COMPARE_WELLS,
  useComparison,
  useWellList,
  type ComparisonWell,
} from '../api/comparison';
import { CompareChart, WELL_COLORS } from '../components/comparison/CompareChart';
import { LithologyTrack } from '../components/comparison/LithologyTrack';
import { LithologyTable } from '../components/comparison/LithologyTable';

/** Default mnemonics to seed the picker if none are typed yet. */
const DEFAULT_MNEMONICS = ['GR', 'ROP', 'RPM', 'WOB'];

/** Shared depth domain across every selected well's curves + intervals. */
function depthDomain(
  wells: ComparisonWell[],
  mnemonics: string[],
): { min: number; max: number } {
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (const w of wells) {
    for (const m of mnemonics) {
      for (const p of w.curves[m] ?? []) {
        if (p.i < min) min = p.i;
        if (p.i > max) max = p.i;
      }
    }
    for (const iv of w.intervals) {
      if (iv.md_top != null && iv.md_top < min) min = iv.md_top;
      if (iv.md_bottom != null && iv.md_bottom > max) max = iv.md_bottom;
    }
  }
  if (!Number.isFinite(min) || !Number.isFinite(max) || min >= max) {
    return { min: 0, max: 1 };
  }
  return { min, max };
}

export function ComparisonPage() {
  const wellList = useWellList();

  const [selectedWells, setSelectedWells] = useState<string[]>([]);
  const [mnemonics, setMnemonics] = useState<string[]>(['GR']);
  const [chartMnemonic, setChartMnemonic] = useState<string>('GR');
  const [logScale, setLogScale] = useState(false);
  const [tableWell, setTableWell] = useState<string>('');

  const comparison = useComparison(selectedWells, mnemonics);
  const wells = useMemo(
    () => comparison.data?.wells ?? [],
    [comparison.data],
  );

  // Keep the chart mnemonic valid as the mnemonic set changes.
  useEffect(() => {
    if (mnemonics.length > 0 && !mnemonics.includes(chartMnemonic)) {
      setChartMnemonic(mnemonics[0]);
    }
  }, [mnemonics, chartMnemonic]);

  // Default the table well to the first selected well.
  useEffect(() => {
    if (wells.length > 0 && !wells.some((w) => w.wellUid === tableWell)) {
      setTableWell(wells[0].wellUid);
    }
  }, [wells, tableWell]);

  const domain = useMemo(
    () => depthDomain(wells, mnemonics),
    [wells, mnemonics],
  );

  const wellOptions = wellList.data ?? [];
  const wellNameByUid = useMemo(() => {
    const m = new Map<string, string>();
    for (const w of wellOptions) m.set(w.uid, w.name ?? w.uid);
    return m;
  }, [wellOptions]);

  const atMax = selectedWells.length >= MAX_COMPARE_WELLS;
  const tableTarget = wells.find((w) => w.wellUid === tableWell);

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        Multi-Well Comparison
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        Overlay up to {MAX_COMPARE_WELLS} wells on a shared depth axis and
        compare their curves and lithology side by side.
      </Typography>

      {/* ── Selection controls ─────────────────────────────────────── */}
      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Stack spacing={2}>
          <Autocomplete
            multiple
            options={wellOptions.map((w) => w.uid)}
            value={selectedWells}
            getOptionLabel={(uid) => wellNameByUid.get(uid) ?? uid}
            loading={wellList.isLoading}
            onChange={(_e, value) => {
              // ENFORCE the 4-well cap in the UI.
              setSelectedWells(value.slice(0, MAX_COMPARE_WELLS));
            }}
            getOptionDisabled={(uid) => atMax && !selectedWells.includes(uid)}
            renderTags={(value, getTagProps) =>
              value.map((uid, index) => {
                const { key, ...tagProps } = getTagProps({ index });
                return (
                  <Chip
                    key={key}
                    label={wellNameByUid.get(uid) ?? uid}
                    {...tagProps}
                    sx={{
                      bgcolor: WELL_COLORS[index % WELL_COLORS.length],
                      color: '#fff',
                    }}
                  />
                );
              })
            }
            renderInput={(params) => (
              <TextField
                {...params}
                label={`Wells (max ${MAX_COMPARE_WELLS})`}
                placeholder={atMax ? 'Maximum reached' : 'Add a well…'}
                helperText={`${selectedWells.length}/${MAX_COMPARE_WELLS} selected`}
              />
            )}
          />

          <Autocomplete
            multiple
            freeSolo
            options={DEFAULT_MNEMONICS}
            value={mnemonics}
            onChange={(_e, value) =>
              setMnemonics(
                Array.from(
                  new Set(value.map((v) => v.trim().toUpperCase()).filter(Boolean)),
                ),
              )
            }
            renderInput={(params) => (
              <TextField
                {...params}
                label="Mnemonics"
                placeholder="Add a mnemonic (e.g. GR)…"
                helperText="Type a mnemonic and press Enter."
              />
            )}
          />

          <Stack
            direction="row"
            spacing={2}
            alignItems="center"
            sx={{ flexWrap: 'wrap', gap: 1 }}
          >
            <Box sx={{ minWidth: 200 }}>
              <Typography variant="caption" color="text.secondary">
                Chart curve
              </Typography>
              <Select
                size="small"
                fullWidth
                value={mnemonics.includes(chartMnemonic) ? chartMnemonic : ''}
                onChange={(e) => setChartMnemonic(e.target.value)}
                displayEmpty
              >
                {mnemonics.length === 0 && (
                  <MenuItem value="" disabled>
                    Pick a mnemonic first
                  </MenuItem>
                )}
                {mnemonics.map((m) => (
                  <MenuItem key={m} value={m}>
                    {m}
                  </MenuItem>
                ))}
              </Select>
            </Box>

            <FormControlLabel
              control={
                <Switch
                  checked={logScale}
                  onChange={(e) => setLogScale(e.target.checked)}
                />
              }
              label={logScale ? 'Logarithmic scale' : 'Cartesian (linear) scale'}
            />
          </Stack>
        </Stack>
      </Paper>

      {/* ── State banners ──────────────────────────────────────────── */}
      {wellList.isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Failed to load well list:{' '}
          {(wellList.error as Error)?.message ?? 'unknown error'}
        </Alert>
      )}

      {selectedWells.length === 0 && (
        <Alert severity="info">Select up to {MAX_COMPARE_WELLS} wells to compare.</Alert>
      )}

      {selectedWells.length > 0 && comparison.isLoading && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, p: 2 }}>
          <CircularProgress size={20} />
          <Typography color="text.secondary">Loading comparison…</Typography>
        </Box>
      )}

      {selectedWells.length > 0 && comparison.isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Failed to load comparison data:{' '}
          {(comparison.error as Error)?.message ?? 'unknown error'}
        </Alert>
      )}

      {/* ── Comparison body ────────────────────────────────────────── */}
      {wells.length > 0 && (
        <Stack spacing={2}>
          {chartMnemonic && (
            <CompareChart
              wells={wells}
              mnemonic={chartMnemonic}
              depthMin={domain.min}
              depthMax={domain.max}
              logScale={logScale}
            />
          )}

          <Paper variant="outlined" sx={{ p: 2 }}>
            <Typography variant="subtitle2" gutterBottom>
              Lithology tracks (shared depth axis)
            </Typography>
            <Box
              sx={{
                display: 'flex',
                gap: 2,
                overflowX: 'auto',
                alignItems: 'flex-start',
                pb: 1,
              }}
            >
              {wells.map((w) => (
                <LithologyTrack
                  key={w.wellUid}
                  wellName={w.wellName || w.wellUid}
                  intervals={w.intervals}
                  depthMin={domain.min}
                  depthMax={domain.max}
                />
              ))}
            </Box>
          </Paper>

          <Box>
            <Box sx={{ mb: 1, maxWidth: 320 }}>
              <Typography variant="caption" color="text.secondary">
                Lithology table well
              </Typography>
              <Select
                size="small"
                fullWidth
                value={tableTarget ? tableWell : ''}
                onChange={(e) => setTableWell(e.target.value)}
                displayEmpty
              >
                {wells.map((w) => (
                  <MenuItem key={w.wellUid} value={w.wellUid}>
                    {w.wellName || w.wellUid}
                  </MenuItem>
                ))}
              </Select>
            </Box>
            {tableTarget && (
              <LithologyTable
                wellName={tableTarget.wellName || tableTarget.wellUid}
                intervals={tableTarget.intervals}
              />
            )}
          </Box>
        </Stack>
      )}
    </Box>
  );
}
