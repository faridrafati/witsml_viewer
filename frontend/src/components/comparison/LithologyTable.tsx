import { useMemo, useState } from 'react';
import {
  Box,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import type {
  ComparisonGeologyInterval,
  ComparisonLithology,
} from '../../api/comparison';
import { lithStyle, normalizeLithType } from './LithologyTrack';

export interface LithologyTableProps {
  wellName: string;
  intervals: ComparisonGeologyInterval[];
}

interface Row {
  key: string;
  type: string;
  normType: string;
  mdTop: number | null;
  mdBottom: number | null;
  lithPc: number | null;
  description: string | null;
  color: string;
}

/** Explode intervals into one row per lithology component, sorted by depth. */
function buildRows(intervals: ComparisonGeologyInterval[]): Row[] {
  const rows: Row[] = [];
  intervals.forEach((iv, i) => {
    const liths: ComparisonLithology[] =
      iv.lithologies.length > 0
        ? iv.lithologies
        : [{ type: iv.type_lithology, description: iv.description, lith_pc: 100 }];
    liths.forEach((l, j) => {
      const style = lithStyle(l);
      rows.push({
        key: `${iv.uid ?? i}-${j}`,
        type: (l.type ?? iv.type_lithology ?? 'Unknown').trim() || 'Unknown',
        normType: normalizeLithType(l.type ?? iv.type_lithology),
        mdTop: iv.md_top ?? null,
        mdBottom: iv.md_bottom ?? null,
        lithPc: l.lith_pc ?? null,
        description: l.description ?? iv.description ?? null,
        color: style.color,
      });
    });
  });
  return rows.sort((a, b) => (a.mdTop ?? 0) - (b.mdTop ?? 0));
}

const fmt = (n: number | null): string => (n == null ? '—' : n.toFixed(1));

/**
 * Tabular lithology breakdown (%-by-depth) for one selected well.
 *
 * Columns: type, depth span (mdTop–mdBottom), lith % and description. A
 * lithology selector at the top filters the table to a chosen type and
 * highlights its rows; choosing "All" shows everything.
 */
export function LithologyTable({ wellName, intervals }: LithologyTableProps) {
  const rows = useMemo(() => buildRows(intervals), [intervals]);

  const types = useMemo(() => {
    const map = new Map<string, string>();
    for (const r of rows) if (!map.has(r.normType)) map.set(r.normType, r.type);
    return Array.from(map.entries())
      .map(([norm, label]) => ({ norm, label }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [rows]);

  const [selected, setSelected] = useState<string>('');

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 2,
          mb: 1.5,
          flexWrap: 'wrap',
        }}
      >
        <Typography variant="subtitle1" noWrap title={wellName}>
          Lithology — {wellName}
        </Typography>
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel id="lith-select-label">Lithology</InputLabel>
          <Select
            labelId="lith-select-label"
            label="Lithology"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            <MenuItem value="">
              <em>All lithologies</em>
            </MenuItem>
            {types.map((t) => (
              <MenuItem key={t.norm} value={t.norm}>
                {t.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Box>

      <TableContainer sx={{ maxHeight: 420 }}>
        <Table size="small" stickyHeader aria-label={`Lithology table for ${wellName}`}>
          <TableHead>
            <TableRow>
              <TableCell>Type</TableCell>
              <TableCell align="right">MD Top</TableCell>
              <TableCell align="right">MD Bottom</TableCell>
              <TableCell align="right">Lith %</TableCell>
              <TableCell>Description</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={5}>
                  <Typography color="text.secondary" variant="body2">
                    No lithology data for this well.
                  </Typography>
                </TableCell>
              </TableRow>
            )}
            {rows.map((r) => {
              const isMatch = selected !== '' && r.normType === selected;
              const dimmed = selected !== '' && !isMatch;
              return (
                <TableRow
                  key={r.key}
                  hover
                  sx={{
                    opacity: dimmed ? 0.35 : 1,
                    backgroundColor: isMatch
                      ? 'rgba(25,118,210,0.10)'
                      : undefined,
                  }}
                >
                  <TableCell>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Box
                        component="span"
                        sx={{
                          width: 12,
                          height: 12,
                          borderRadius: '2px',
                          backgroundColor: r.color,
                          border: '1px solid rgba(0,0,0,0.2)',
                          flexShrink: 0,
                        }}
                      />
                      {r.type}
                    </Box>
                  </TableCell>
                  <TableCell align="right">{fmt(r.mdTop)}</TableCell>
                  <TableCell align="right">{fmt(r.mdBottom)}</TableCell>
                  <TableCell align="right">
                    {r.lithPc == null ? '—' : `${r.lithPc.toFixed(0)}%`}
                  </TableCell>
                  <TableCell>{r.description ?? '—'}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
}
