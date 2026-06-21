import { useQuery } from '@tanstack/react-query';
import { http } from './http';
import type { WellStatus } from './types';

/**
 * API layer for the multi-well comparison view (brief §7.8 / §7.10).
 *
 * Two public hooks:
 *   useWellList()                       -> GET /api/ingest/wells  (the warm wells)
 *   useComparison(wellUids, mnemonics)  -> GET /api/comparison    (aligned curves
 *                                          + lithology for up to 4 wells)
 *
 * As with the rest of the app nothing is fetched at module-evaluation time;
 * all network access is lazy inside the hooks.
 */

/** Hard cap enforced by the UI and the comparison query. */
export const MAX_COMPARE_WELLS = 4;

/* ------------------------------------------------------------------ */
/* Wire shapes for GET /api/comparison                                */
/*                                                                     */
/* The backend serializes pydantic domain models with snake_case      */
/* field names, so the lithology shapes mirror app/domain/models.py   */
/* (MudLog -> GeologyInterval -> Lithology) verbatim.                  */
/* ------------------------------------------------------------------ */

/** One curve sample on a shared axis. `i` = depth (or index), `v` = value. */
export interface ComparisonPoint {
  i: number;
  v: number;
  u?: string | null;
}

/** A single lithology component of a geology interval. */
export interface ComparisonLithology {
  uid?: string | null;
  type?: string | null;
  code_lith?: string | null;
  /** Percentage of the interval occupied by this lithology (0..100). */
  lith_pc?: number | null;
  description?: string | null;
  color?: string | null;
}

/** A depth interval with one or more lithologies (from a mudLog). */
export interface ComparisonGeologyInterval {
  uid?: string | null;
  type_lithology?: string | null;
  md_top?: number | null;
  md_bottom?: number | null;
  md_uom?: string | null;
  lithologies: ComparisonLithology[];
  description?: string | null;
}

/** Everything the comparison view needs for one well. */
export interface ComparisonWell {
  wellUid: string;
  wellName?: string | null;
  /** Mnemonic -> samples aligned to the shared depth/index axis. */
  curves: Record<string, ComparisonPoint[]>;
  /** Flattened geology intervals across the well's mudLogs. */
  intervals: ComparisonGeologyInterval[];
}

/** Response of GET /api/comparison. */
export interface ComparisonResponse {
  /** Echo of the requested mnemonics (preserves order). */
  mnemonics: string[];
  wells: ComparisonWell[];
}

/* ------------------------------------------------------------------ */
/* Hooks                                                               */
/* ------------------------------------------------------------------ */

/**
 * List all warm wells available for comparison (GET /api/ingest/wells).
 * Polls so the picker stays current as wells warm up / go cold.
 */
export function useWellList() {
  return useQuery<WellStatus[]>({
    queryKey: ['comparison', 'wells'],
    queryFn: async () => {
      const { data } = await http.get<WellStatus[]>('/ingest/wells');
      return data;
    },
    refetchInterval: 10_000,
  });
}

/**
 * Fetch aligned curves + lithology for up to {@link MAX_COMPARE_WELLS} wells
 * over a shared axis (GET /api/comparison?wells=&mnemonics=).
 *
 * The query is disabled until at least one well and one mnemonic are chosen,
 * and the well list is truncated to the max so an over-long selection can
 * never reach the backend.
 */
export function useComparison(wellUids: string[], mnemonics: string[]) {
  const wells = wellUids.slice(0, MAX_COMPARE_WELLS);
  const wellsKey = wells.join(',');
  const mnemonicsKey = mnemonics.join(',');

  return useQuery<ComparisonResponse>({
    queryKey: ['comparison', 'data', wellsKey, mnemonicsKey],
    enabled: wells.length > 0 && mnemonics.length > 0,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set('wells', wellsKey);
      params.set('mnemonics', mnemonicsKey);
      const { data } = await http.get<ComparisonResponse>(
        `/comparison?${params.toString()}`,
      );
      return data;
    },
  });
}
