import { useEffect, useMemo, useState } from 'react';
import {
  Autocomplete,
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import {
  useParameters,
  type ComponentType,
  type DashboardComponentConfig,
  type TimeAxis,
} from '../../api/pages';

export interface ComponentConfigDialogProps {
  open: boolean;
  /** When editing, the existing config; null/undefined when adding. */
  initial?: DashboardComponentConfig | null;
  onClose: () => void;
  /** Called with the resulting component (PAGE LAYOUT JSON shape). */
  onSave: (component: DashboardComponentConfig) => void;
}

const COMPONENT_TYPES: { value: ComponentType; label: string }[] = [
  { value: 'numeric', label: 'Numeric readout' },
  { value: 'chart', label: 'Line chart' },
  { value: 'strip', label: 'Strip / lithology track' },
];

function newId(): string {
  return `cmp_${Math.random().toString(36).slice(2, 10)}`;
}

/** A fresh component with sensible defaults, used when adding. */
function defaultComponent(): DashboardComponentConfig {
  return {
    id: newId(),
    type: 'numeric',
    mnemonics: [],
    title: '',
    grid: { x: 0, y: 0, w: 4, h: 3 },
    ui: {
      lineColor: '#42a5f5',
      lineStroke: 2,
      min: null,
      max: null,
      unit: null,
    },
    back_config: { backgroundColor: '#ffffff' },
    comment_config: { text: '', isVisible: false },
    time_config: { axis: 'time' },
  };
}

/**
 * MUI dialog to add or edit a single dashboard component. Picks the type, one
 * or more mnemonics from the parameter catalog, a title, UI style (line color,
 * stroke, y-min/max, unit) and the time/depth axis. Returns a component object
 * in the PAGE LAYOUT JSON shape via `onSave`.
 */
export function ComponentConfigDialog({
  open,
  initial,
  onClose,
  onSave,
}: ComponentConfigDialogProps) {
  const { data: parameters } = useParameters();
  const [draft, setDraft] = useState<DashboardComponentConfig>(
    initial ?? defaultComponent(),
  );

  // Reset the working copy each time the dialog opens.
  useEffect(() => {
    if (open) setDraft(initial ?? defaultComponent());
  }, [open, initial]);

  const mnemonicOptions = useMemo(
    () => (parameters ?? []).map((p) => p.mnemonic),
    [parameters],
  );

  const update = (patch: Partial<DashboardComponentConfig>) =>
    setDraft((d) => ({ ...d, ...patch }));
  const updateUi = (patch: Partial<DashboardComponentConfig['ui']>) =>
    setDraft((d) => ({ ...d, ui: { ...d.ui, ...patch } }));

  const isNumeric = draft.type === 'numeric';
  const canSave = draft.mnemonics.length > 0;

  const handleSave = () => {
    // Numeric/strip use the first mnemonic; charts may use several.
    const cleaned: DashboardComponentConfig = {
      ...draft,
      title: draft.title.trim() || draft.mnemonics[0] || draft.type,
    };
    onSave(cleaned);
    onClose();
  };

  // Helper to parse an optional numeric text field into number | null.
  const parseNum = (s: string): number | null => {
    if (s.trim() === '') return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{initial ? 'Edit component' : 'Add component'}</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            select
            label="Type"
            value={draft.type}
            onChange={(e) =>
              update({ type: e.target.value as ComponentType })
            }
            fullWidth
          >
            {COMPONENT_TYPES.map((t) => (
              <MenuItem key={t.value} value={t.value}>
                {t.label}
              </MenuItem>
            ))}
          </TextField>

          <Autocomplete
            multiple={!isNumeric}
            freeSolo
            options={mnemonicOptions}
            value={
              isNumeric
                ? (draft.mnemonics[0] ?? null)
                : draft.mnemonics
            }
            onChange={(_e, value) => {
              if (isNumeric) {
                update({ mnemonics: value ? [value as string] : [] });
              } else {
                update({ mnemonics: (value as string[]) ?? [] });
              }
            }}
            renderInput={(params) => (
              <TextField
                {...params}
                label={isNumeric ? 'Mnemonic' : 'Mnemonics'}
                placeholder="Pick from catalog"
                helperText={
                  isNumeric
                    ? 'Numeric readout shows the first mnemonic'
                    : 'Add one or more curves'
                }
              />
            )}
          />

          <TextField
            label="Title"
            value={draft.title}
            onChange={(e) => update({ title: e.target.value })}
            fullWidth
          />

          {draft.type === 'chart' && (
            <>
              <Typography variant="overline" color="text.secondary">
                Style
              </Typography>
              <Stack direction="row" spacing={2}>
                <TextField
                  label="Line color"
                  type="color"
                  value={draft.ui.lineColor}
                  onChange={(e) => updateUi({ lineColor: e.target.value })}
                  sx={{ width: 120 }}
                />
                <TextField
                  label="Stroke"
                  type="number"
                  value={draft.ui.lineStroke}
                  onChange={(e) =>
                    updateUi({
                      lineStroke: Math.max(1, Number(e.target.value) || 1),
                    })
                  }
                  inputProps={{ min: 1, max: 8, step: 0.5 }}
                  sx={{ width: 100 }}
                />
              </Stack>
              <Stack direction="row" spacing={2}>
                <TextField
                  label="Y min"
                  value={draft.ui.min ?? ''}
                  onChange={(e) => updateUi({ min: parseNum(e.target.value) })}
                  sx={{ width: 120 }}
                />
                <TextField
                  label="Y max"
                  value={draft.ui.max ?? ''}
                  onChange={(e) => updateUi({ max: parseNum(e.target.value) })}
                  sx={{ width: 120 }}
                />
                <TextField
                  label="Unit"
                  value={draft.ui.unit ?? ''}
                  onChange={(e) =>
                    updateUi({ unit: e.target.value.trim() || null })
                  }
                  sx={{ width: 120 }}
                />
              </Stack>
            </>
          )}

          {draft.type !== 'numeric' && (
            <TextField
              select
              label="Axis"
              value={draft.time_config.axis}
              onChange={(e) =>
                update({
                  time_config: { axis: e.target.value as TimeAxis },
                })
              }
              sx={{ width: 160 }}
            >
              <MenuItem value="time">Time</MenuItem>
              <MenuItem value="depth">Depth</MenuItem>
            </TextField>
          )}

          <Typography variant="overline" color="text.secondary">
            Appearance
          </Typography>
          <Stack direction="row" spacing={2} alignItems="center">
            <TextField
              label="Background"
              type="color"
              value={draft.back_config.backgroundColor}
              onChange={(e) =>
                update({ back_config: { backgroundColor: e.target.value } })
              }
              sx={{ width: 120 }}
            />
          </Stack>

          <Box>
            <FormControlLabel
              control={
                <Checkbox
                  checked={draft.comment_config.isVisible}
                  onChange={(e) =>
                    update({
                      comment_config: {
                        ...draft.comment_config,
                        isVisible: e.target.checked,
                      },
                    })
                  }
                />
              }
              label="Show comment"
            />
            <TextField
              label="Comment"
              value={draft.comment_config.text}
              onChange={(e) =>
                update({
                  comment_config: {
                    ...draft.comment_config,
                    text: e.target.value,
                  },
                })
              }
              fullWidth
              size="small"
            />
          </Box>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button onClick={handleSave} variant="contained" disabled={!canSave}>
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}
