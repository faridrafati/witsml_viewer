import { useEffect, useState } from 'react';
import {
  Alert,
  Autocomplete,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import {
  downloadPdf,
  downloadXlsx,
  type ExportFormat,
  type ExportIndexType,
} from '../../api/export';

export interface ExportDialogProps {
  open: boolean;
  /** Well the export is for. The dialog is inert without one. */
  wellUid: string | null;
  onClose: () => void;
  /** Optional mnemonic suggestions for the free-solo picker. */
  mnemonicOptions?: string[];
  /** Optional initial mnemonic selection. */
  initialMnemonics?: string[];
}

const INDEX_TYPES: { value: ExportIndexType; label: string }[] = [
  { value: 'time', label: 'Time' },
  { value: 'depth', label: 'Depth' },
];

const FORMATS: { value: ExportFormat; label: string }[] = [
  { value: 'xlsx', label: 'Excel (.xlsx)' },
  { value: 'pdf', label: 'PDF' },
];

/**
 * Reusable export dialog (brief §7.9). Pick a free-solo list of mnemonics, the
 * index type (time/depth) and the output format (Excel/PDF) for a given well,
 * then stream and download the file via downloadXlsx / downloadPdf.
 *
 * Drop it anywhere a well is in context (dashboard, comparison, well detail)
 * and drive it with `open` / `onClose`.
 */
export function ExportDialog({
  open,
  wellUid,
  onClose,
  mnemonicOptions = [],
  initialMnemonics = [],
}: ExportDialogProps) {
  const [mnemonics, setMnemonics] = useState<string[]>(initialMnemonics);
  const [indexType, setIndexType] = useState<ExportIndexType>('time');
  const [format, setFormat] = useState<ExportFormat>('xlsx');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset the working copy each time the dialog opens.
  useEffect(() => {
    if (open) {
      setMnemonics(initialMnemonics);
      setIndexType('time');
      setFormat('xlsx');
      setError(null);
      setBusy(false);
    }
    // initialMnemonics is intentionally read only on open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const canExport = !!wellUid && mnemonics.length > 0 && !busy;

  const handleExport = async () => {
    if (!wellUid) return;
    setBusy(true);
    setError(null);
    const body = { wellUid, mnemonics, indexType };
    try {
      if (format === 'xlsx') {
        await downloadXlsx(body);
      } else {
        await downloadPdf(body);
      }
      onClose();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Export failed. Please try again.',
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Export well data</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {!wellUid && (
            <Alert severity="info">
              Select a well before exporting.
            </Alert>
          )}

          <Typography variant="caption" color="text.secondary">
            Well: {wellUid ?? '—'}
          </Typography>

          <Autocomplete
            multiple
            freeSolo
            options={mnemonicOptions}
            value={mnemonics}
            onChange={(_e, value) =>
              setMnemonics(
                Array.from(
                  new Set(
                    value.map((v) => v.trim().toUpperCase()).filter(Boolean),
                  ),
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

          <Stack direction="row" spacing={2}>
            <TextField
              select
              label="Index type"
              value={indexType}
              onChange={(e) => setIndexType(e.target.value as ExportIndexType)}
              sx={{ width: 180 }}
            >
              {INDEX_TYPES.map((t) => (
                <MenuItem key={t.value} value={t.value}>
                  {t.label}
                </MenuItem>
              ))}
            </TextField>

            <TextField
              select
              label="Format"
              value={format}
              onChange={(e) => setFormat(e.target.value as ExportFormat)}
              sx={{ width: 180 }}
            >
              {FORMATS.map((f) => (
                <MenuItem key={f.value} value={f.value}>
                  {f.label}
                </MenuItem>
              ))}
            </TextField>
          </Stack>

          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button
          onClick={handleExport}
          variant="contained"
          disabled={!canExport}
        >
          {busy ? 'Exporting…' : 'Export'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
