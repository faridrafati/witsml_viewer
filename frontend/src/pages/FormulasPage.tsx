import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  FormControlLabel,
  List,
  ListItemButton,
  ListItemText,
  Paper,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import {
  useComputeFormula,
  useFormulas,
  type FormulaDef,
  type FormulaVariable,
} from '../api/formulas';
import { useSessionStore } from '../store/session';
import { useWellStream } from '../api/useWellStream';
import type { IngestCurves } from '../api/types';

/** Recompute bound variables against the live stream this often (ms). */
const POLL_INTERVAL = 4_000;

/** Per-variable form state: a constant value or a binding to a live mnemonic. */
interface VarState {
  /** When true, the value is read from the live stream by `mnemonic`. */
  bound: boolean;
  /** Constant value used when `bound` is false. */
  constValue: string;
  /** Live mnemonic to read when `bound` is true. */
  mnemonic: string;
}

/** Build the initial form state for a formula's variables. */
function initialVarState(formula: FormulaDef): Record<string, VarState> {
  const out: Record<string, VarState> = {};
  for (const v of formula.variables) {
    const bound = !!v.suggest_mnemonic;
    out[v.name] = {
      bound,
      constValue: v.default != null ? String(v.default) : '',
      mnemonic: v.suggest_mnemonic ?? '',
    };
  }
  return out;
}

/** Latest finite value for a mnemonic in the live buffer, or null. */
function latestValue(curves: IngestCurves, mnemonic: string): number | null {
  const pts = curves[mnemonic];
  if (!pts || pts.length === 0) return null;
  const v = pts[pts.length - 1].v;
  return Number.isFinite(v) ? v : null;
}

/**
 * Resolve every variable to a numeric value given the current form state and
 * the live curve buffer. Returns null if any variable is unresolved (so the
 * caller can avoid an invalid compute).
 */
function resolveValues(
  formula: FormulaDef,
  state: Record<string, VarState>,
  curves: IngestCurves,
): { values: Record<string, number>; missing: string[] } {
  const values: Record<string, number> = {};
  const missing: string[] = [];
  for (const v of formula.variables) {
    const s = state[v.name];
    if (!s) {
      missing.push(v.name);
      continue;
    }
    if (s.bound) {
      const live = s.mnemonic ? latestValue(curves, s.mnemonic) : null;
      if (live == null) {
        missing.push(v.name);
      } else {
        values[v.name] = live;
      }
    } else {
      const n = Number(s.constValue);
      if (s.constValue.trim() === '' || !Number.isFinite(n)) {
        missing.push(v.name);
      } else {
        values[v.name] = n;
      }
    }
  }
  return { values, missing };
}

/** Editor row for a single formula variable (constant or live-bound). */
function VariableRow({
  variable,
  state,
  liveValue,
  mnemonicOptions,
  onChange,
}: {
  variable: FormulaVariable;
  state: VarState;
  liveValue: number | null;
  mnemonicOptions: string[];
  onChange: (patch: Partial<VarState>) => void;
}) {
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={2}
        alignItems={{ xs: 'stretch', sm: 'center' }}
      >
        <Box sx={{ minWidth: 160 }}>
          <Typography variant="subtitle2">
            {variable.label}{' '}
            <Typography component="span" color="text.secondary">
              ({variable.name})
            </Typography>
          </Typography>
          {variable.unit && (
            <Typography variant="caption" color="text.secondary">
              {variable.unit}
            </Typography>
          )}
        </Box>

        <FormControlLabel
          control={
            <Switch
              checked={state.bound}
              onChange={(e) => onChange({ bound: e.target.checked })}
            />
          }
          label={state.bound ? 'Live' : 'Constant'}
          sx={{ minWidth: 110 }}
        />

        {state.bound ? (
          <Stack
            direction="row"
            spacing={2}
            alignItems="center"
            sx={{ flexGrow: 1 }}
          >
            <Autocomplete
              freeSolo
              fullWidth
              options={mnemonicOptions}
              value={state.mnemonic}
              onInputChange={(_e, value) =>
                onChange({ mnemonic: value.trim().toUpperCase() })
              }
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Live mnemonic"
                  placeholder="e.g. MW"
                  size="small"
                />
              )}
            />
            <Chip
              size="small"
              color={liveValue == null ? 'default' : 'success'}
              label={
                liveValue == null
                  ? 'no data'
                  : `${liveValue.toFixed(2)}${variable.unit ? ` ${variable.unit}` : ''}`
              }
            />
          </Stack>
        ) : (
          <TextField
            label="Value"
            type="number"
            size="small"
            value={state.constValue}
            onChange={(e) => onChange({ constValue: e.target.value })}
            sx={{ flexGrow: 1 }}
          />
        )}
      </Stack>
    </Paper>
  );
}

export function FormulasPage() {
  const { data: formulas, isLoading, isError, error } = useFormulas();
  const selectedWellUid = useSessionStore((s) => s.selectedWellUid);

  // Live data for the session's selected well drives every bound variable.
  const stream = useWellStream(selectedWellUid);
  const curves = stream.curves;

  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [varState, setVarState] = useState<Record<string, VarState>>({});

  const selected = useMemo(
    () => formulas?.find((f) => f.key === selectedKey) ?? null,
    [formulas, selectedKey],
  );

  // Default to the Impact Force showcase once the library loads.
  useEffect(() => {
    if (!formulas || formulas.length === 0 || selectedKey) return;
    const showcase =
      formulas.find((f) => f.key === 'impact_force') ?? formulas[0];
    setSelectedKey(showcase.key);
  }, [formulas, selectedKey]);

  // Seed form state whenever the selected formula changes.
  useEffect(() => {
    if (selected) setVarState(initialVarState(selected));
  }, [selected]);

  const compute = useComputeFormula();
  const computeRef = useRef(compute.mutate);
  computeRef.current = compute.mutate;

  // Suggest mnemonics from whatever the live stream currently carries, merged
  // with the formula's own suggestions.
  const mnemonicOptions = useMemo(() => {
    const set = new Set<string>(Object.keys(curves));
    for (const v of selected?.variables ?? []) {
      if (v.suggest_mnemonic) set.add(v.suggest_mnemonic);
    }
    return Array.from(set).sort();
  }, [curves, selected]);

  const { values, missing } = useMemo(
    () =>
      selected
        ? resolveValues(selected, varState, curves)
        : { values: {}, missing: [] as string[] },
    [selected, varState, curves],
  );

  // Recompute whenever resolved values change (and the form is complete).
  // We key on a stable serialization so identical live values don't refire.
  const valuesKey = useMemo(() => JSON.stringify(values), [values]);
  useEffect(() => {
    if (!selected || missing.length > 0) return;
    computeRef.current({ key: selected.key, values });
    // values is captured via valuesKey to avoid an unstable-object dep.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.key, valuesKey, missing.length]);

  // Poll: re-fire compute on an interval so bound variables track the well's
  // live value even when the form itself is untouched.
  useEffect(() => {
    if (!selected) return;
    const id = window.setInterval(() => {
      const resolved = resolveValues(selected, varState, stream.curves);
      if (resolved.missing.length === 0) {
        computeRef.current({ key: selected.key, values: resolved.values });
      }
    }, POLL_INTERVAL);
    return () => window.clearInterval(id);
  }, [selected, varState, stream.curves]);

  const updateVar = (name: string, patch: Partial<VarState>) =>
    setVarState((prev) => ({ ...prev, [name]: { ...prev[name], ...patch } }));

  const handleRefresh = () => {
    if (selected && missing.length === 0) {
      compute.mutate({ key: selected.key, values });
    }
  };

  const result = compute.data;

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        Hydraulics Formulas
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        Pick a formula, then supply each variable as a constant or bind it to a
        live curve from the selected well. The result recomputes as inputs (and
        live values) change.
      </Typography>

      {isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Failed to load formulas: {(error as Error)?.message ?? 'unknown error'}
        </Alert>
      )}

      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems="flex-start">
        {/* ── Formula list ─────────────────────────────────────────── */}
        <Paper variant="outlined" sx={{ width: { xs: '100%', md: 300 }, flexShrink: 0 }}>
          {isLoading ? (
            <Box sx={{ p: 2, display: 'flex', gap: 1, alignItems: 'center' }}>
              <CircularProgress size={18} />
              <Typography color="text.secondary">Loading…</Typography>
            </Box>
          ) : (
            <List disablePadding>
              {(formulas ?? []).map((f) => (
                <ListItemButton
                  key={f.key}
                  selected={f.key === selectedKey}
                  onClick={() => setSelectedKey(f.key)}
                >
                  <ListItemText
                    primary={f.name}
                    secondary={f.result_unit}
                  />
                </ListItemButton>
              ))}
            </List>
          )}
        </Paper>

        {/* ── Selected formula form ────────────────────────────────── */}
        <Box sx={{ flexGrow: 1, width: '100%' }}>
          {!selected ? (
            <Alert severity="info">Select a formula to begin.</Alert>
          ) : (
            <Stack spacing={2}>
              <Paper variant="outlined" sx={{ p: 2 }}>
                <Typography variant="h6">{selected.name}</Typography>
                {selected.description && (
                  <Typography color="text.secondary" sx={{ mb: 1 }}>
                    {selected.description}
                  </Typography>
                )}
                <Typography
                  variant="body2"
                  sx={{ fontFamily: 'monospace', color: 'text.secondary' }}
                >
                  {selected.expression}
                </Typography>
                {!selectedWellUid && (
                  <Alert severity="info" sx={{ mt: 1 }}>
                    No well selected — live-bound variables will have no data
                    until a well is chosen.
                  </Alert>
                )}
              </Paper>

              {selected.variables.map((v) => {
                const s =
                  varState[v.name] ?? {
                    bound: false,
                    constValue: v.default != null ? String(v.default) : '',
                    mnemonic: v.suggest_mnemonic ?? '',
                  };
                const liveValue =
                  s.bound && s.mnemonic ? latestValue(curves, s.mnemonic) : null;
                return (
                  <VariableRow
                    key={v.name}
                    variable={v}
                    state={s}
                    liveValue={liveValue}
                    mnemonicOptions={mnemonicOptions}
                    onChange={(patch) => updateVar(v.name, patch)}
                  />
                );
              })}

              {/* ── Result ─────────────────────────────────────────── */}
              <Paper variant="outlined" sx={{ p: 2 }}>
                <Stack
                  direction="row"
                  justifyContent="space-between"
                  alignItems="center"
                  sx={{ mb: 1 }}
                >
                  <Typography variant="overline" color="text.secondary">
                    Result
                  </Typography>
                  <Button
                    size="small"
                    onClick={handleRefresh}
                    disabled={missing.length > 0 || compute.isPending}
                  >
                    Refresh
                  </Button>
                </Stack>
                <Divider sx={{ mb: 2 }} />

                {missing.length > 0 ? (
                  <Alert severity="warning">
                    Waiting on {missing.join(', ')} — supply a constant or bind
                    a live mnemonic with data.
                  </Alert>
                ) : compute.isError ? (
                  <Alert severity="error">
                    {(compute.error as Error)?.message ?? 'Compute failed.'}
                  </Alert>
                ) : (
                  <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1 }}>
                    <Typography
                      variant="h3"
                      sx={{ fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}
                    >
                      {result ? result.result.toFixed(2) : '—'}
                    </Typography>
                    <Typography variant="h6" color="text.secondary">
                      {result?.result_unit ?? selected.result_unit}
                    </Typography>
                    {compute.isPending && <CircularProgress size={18} />}
                  </Box>
                )}
              </Paper>
            </Stack>
          )}
        </Box>
      </Stack>
    </Box>
  );
}
