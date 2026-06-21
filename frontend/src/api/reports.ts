import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query';
import { http } from './http';

/**
 * React Query hooks + helpers for the P7 reporting module (brief §7.11),
 * talking to the `/api/reports/*` family of endpoints.
 *
 * Public surface:
 *   useReports(filters)                 -> GET /api/reports
 *   useRemarks(keyword, filters)        -> GET /api/reports/remarks
 *   downloadRemarksXlsx(params)         -> GET /api/reports/remarks/export (blob)
 *   useSavedSearches()                  -> GET    /api/reports/saved-searches
 *   useCreateSavedSearch()              -> POST   /api/reports/saved-searches
 *   useDeleteSavedSearch()              -> DELETE /api/reports/saved-searches/{id}
 *   useRunSavedSearch()                 -> POST   /api/reports/saved-searches/{id}/run
 *   useDepths()                         -> GET    /api/reports/depths
 *   useCreateDepth()                    -> POST   /api/reports/depths
 *   useDeleteDepth()                    -> DELETE /api/reports/depths/{id}
 *   useMudProperties(filters)           -> GET    /api/reports/mud-properties
 *
 * Nothing is fetched at module-evaluation time; all network access is lazy
 * inside the hooks. Query keys are scoped under ['reports', …] so a single
 * invalidation can refresh the whole module if needed.
 */

/* ------------------------------------------------------------------ */
/* Wire shapes (mirror the backend reports DTOs)                       */
/* ------------------------------------------------------------------ */

/** Common filter set shared by reports, remarks and mud-properties queries. */
export interface ReportFilters {
  /** Restrict to a single report field/section (e.g. "GEOLOGY", "DRILLING"). */
  field?: string | null;
  /** Restrict to a single well by uid. */
  wellUid?: string | null;
  /** Inclusive lower bound on report date (ISO yyyy-mm-dd). */
  dateFrom?: string | null;
  /** Inclusive upper bound on report date (ISO yyyy-mm-dd). */
  dateTo?: string | null;
}

/** A daily/operational report header row. */
export interface ReportRow {
  id: number;
  /** Owning well. */
  wellUid: string;
  wellName?: string | null;
  /** Report date (ISO yyyy-mm-dd). */
  reportDate: string;
  /** Report section / field this row belongs to. */
  field?: string | null;
  /** Free-form report title. */
  title?: string | null;
  /** Measured-depth context for the report, if any. */
  mdTop?: number | null;
  mdBottom?: number | null;
  mdUom?: string | null;
}

/** A single remark/summary line, with the report it belongs to for context. */
export interface RemarkRow {
  id: number;
  wellUid: string;
  wellName?: string | null;
  reportId: number;
  reportDate: string;
  field?: string | null;
  /** The remark text itself. */
  text: string;
  /** Measured depth the remark refers to, if recorded. */
  md?: number | null;
  mdUom?: string | null;
  /** Author / reporter, if recorded. */
  author?: string | null;
}

/** Drilling-fluid (mud) property spec for one report/well. */
export interface MudPropertyRow {
  id: number;
  wellUid: string;
  wellName?: string | null;
  reportId?: number | null;
  reportDate?: string | null;
  /** Sample measured depth. */
  md?: number | null;
  mdUom?: string | null;
  /** Fluid type, e.g. "WBM", "OBM". */
  fluidType?: string | null;
  /** Density / mud weight. */
  density?: number | null;
  densityUom?: string | null;
  /** Funnel viscosity. */
  viscosity?: number | null;
  viscosityUom?: string | null;
  /** Plastic viscosity. */
  pv?: number | null;
  /** Yield point. */
  yp?: number | null;
  ph?: number | null;
  /** Chloride content. */
  chlorides?: number | null;
}

/** A persisted "save this search" entry (criteria the user wants to re-run). */
export interface SavedSearch {
  id: number;
  name: string;
  /** Keyword the remarks search was run with. */
  keyword?: string | null;
  /** Filters captured at save time. */
  filters: ReportFilters;
  createdAt?: string | null;
}

export interface CreateSavedSearchBody {
  name: string;
  keyword?: string | null;
  filters: ReportFilters;
}

/** A "depth of interest" bookmark a user saved from a remark/result row. */
export interface DepthOfInterest {
  id: number;
  wellUid: string;
  wellName?: string | null;
  /** The depth the user flagged. */
  md: number;
  mdUom?: string | null;
  /** Optional note / why it matters. */
  note?: string | null;
  /** The remark this was saved from, if any. */
  remarkId?: number | null;
  createdAt?: string | null;
}

export interface CreateDepthBody {
  wellUid: string;
  wellName?: string | null;
  md: number;
  mdUom?: string | null;
  note?: string | null;
  remarkId?: number | null;
}

/* ------------------------------------------------------------------ */
/* Query-param helpers                                                 */
/* ------------------------------------------------------------------ */

/** Serialize a {@link ReportFilters} into URL search params (skipping empties). */
function filtersToParams(filters: ReportFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.field) params.set('field', filters.field);
  if (filters.wellUid) params.set('well_uid', filters.wellUid);
  if (filters.dateFrom) params.set('date_from', filters.dateFrom);
  if (filters.dateTo) params.set('date_to', filters.dateTo);
  return params;
}

/** Stable string key for a filter set, for use in query keys. */
function filtersKey(filters: ReportFilters): string {
  return [
    filters.field ?? '',
    filters.wellUid ?? '',
    filters.dateFrom ?? '',
    filters.dateTo ?? '',
  ].join('|');
}

const REPORTS_KEY = ['reports'] as const;

/* ------------------------------------------------------------------ */
/* Reports + remarks                                                   */
/* ------------------------------------------------------------------ */

/** List report headers matching the given filters (GET /api/reports). */
export function useReports(
  filters: ReportFilters = {},
): UseQueryResult<ReportRow[]> {
  return useQuery<ReportRow[]>({
    queryKey: [...REPORTS_KEY, 'list', filtersKey(filters)],
    queryFn: async () => {
      const params = filtersToParams(filters);
      const { data } = await http.get<ReportRow[]>(
        `/reports?${params.toString()}`,
      );
      return data;
    },
  });
}

/**
 * Search remark/summary lines by keyword + filters
 * (GET /api/reports/remarks?keyword=&field=&well_uid=&date_from=&date_to=).
 *
 * Always enabled — an empty keyword returns all remarks within the filters.
 */
export function useRemarks(
  keyword: string,
  filters: ReportFilters = {},
): UseQueryResult<RemarkRow[]> {
  const trimmed = keyword.trim();
  return useQuery<RemarkRow[]>({
    queryKey: [...REPORTS_KEY, 'remarks', trimmed, filtersKey(filters)],
    queryFn: async () => {
      const params = filtersToParams(filters);
      if (trimmed) params.set('keyword', trimmed);
      const { data } = await http.get<RemarkRow[]>(
        `/reports/remarks?${params.toString()}`,
      );
      return data;
    },
  });
}

/** Parameters accepted by {@link downloadRemarksXlsx}. */
export interface RemarksExportParams extends ReportFilters {
  keyword?: string | null;
}

/**
 * Download the current remarks search as an Excel workbook
 * (GET /api/reports/remarks/export). Returns the binary blob; the caller is
 * responsible for triggering the browser save (see ReportsPage).
 */
export async function downloadRemarksXlsx(
  params: RemarksExportParams,
): Promise<Blob> {
  const search = filtersToParams(params);
  if (params.keyword && params.keyword.trim()) {
    search.set('keyword', params.keyword.trim());
  }
  const { data } = await http.get<Blob>(
    `/reports/remarks/export?${search.toString()}`,
    { responseType: 'blob' },
  );
  return data;
}

/**
 * Convenience helper: download the remarks export and trigger a browser save
 * with a sensible filename. Safe to call from a click handler.
 */
export async function saveRemarksXlsx(
  params: RemarksExportParams,
  filename = 'remarks.xlsx',
): Promise<void> {
  const blob = await downloadRemarksXlsx(params);
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}

/* ------------------------------------------------------------------ */
/* Saved searches (CRUD + run)                                         */
/* ------------------------------------------------------------------ */

const SAVED_SEARCHES_KEY = [...REPORTS_KEY, 'saved-searches'] as const;

/** List the user's saved searches (GET /api/reports/saved-searches). */
export function useSavedSearches(): UseQueryResult<SavedSearch[]> {
  return useQuery<SavedSearch[]>({
    queryKey: SAVED_SEARCHES_KEY,
    queryFn: async () => {
      const { data } = await http.get<SavedSearch[]>(
        '/reports/searches',
      );
      return data;
    },
  });
}

export function useCreateSavedSearch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CreateSavedSearchBody) => {
      const { data } = await http.post<SavedSearch>(
        '/reports/searches',
        body,
      );
      return data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: SAVED_SEARCHES_KEY });
    },
  });
}

export function useDeleteSavedSearch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await http.delete(`/reports/searches/${id}`);
      return id;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: SAVED_SEARCHES_KEY });
    },
  });
}

/**
 * Re-run a saved search server-side and return the matching remarks
 * (POST /api/reports/saved-searches/{id}/run). The backend resolves the saved
 * keyword + filters and returns the same shape as {@link useRemarks}.
 */
export function useRunSavedSearch() {
  return useMutation({
    mutationFn: async (id: number) => {
      const { data } = await http.post<RemarkRow[]>(
        `/reports/saved-searches/${id}/run`,
      );
      return data;
    },
  });
}

/* ------------------------------------------------------------------ */
/* Depths of interest (CRUD)                                           */
/* ------------------------------------------------------------------ */

const DEPTHS_KEY = [...REPORTS_KEY, 'depths'] as const;

/** List saved depths of interest (GET /api/reports/depths). */
export function useDepths(
  wellUid?: string | null,
): UseQueryResult<DepthOfInterest[]> {
  return useQuery<DepthOfInterest[]>({
    queryKey: [...DEPTHS_KEY, wellUid ?? ''],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (wellUid) params.set('well_uid', wellUid);
      const qs = params.toString();
      const { data } = await http.get<DepthOfInterest[]>(
        `/reports/depths${qs ? `?${qs}` : ''}`,
      );
      return data;
    },
  });
}

export function useCreateDepth() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CreateDepthBody) => {
      const { data } = await http.post<DepthOfInterest>(
        '/reports/depths',
        body,
      );
      return data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: DEPTHS_KEY });
    },
  });
}

export function useDeleteDepth() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await http.delete(`/reports/depths/${id}`);
      return id;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: DEPTHS_KEY });
    },
  });
}

/* ------------------------------------------------------------------ */
/* Mud properties                                                      */
/* ------------------------------------------------------------------ */

/** List drilling-fluid spec rows (GET /api/reports/mud-properties). */
export function useMudProperties(
  filters: ReportFilters = {},
): UseQueryResult<MudPropertyRow[]> {
  return useQuery<MudPropertyRow[]>({
    queryKey: [...REPORTS_KEY, 'mud-properties', filtersKey(filters)],
    queryFn: async () => {
      const params = filtersToParams(filters);
      const { data } = await http.get<MudPropertyRow[]>(
        `/reports/mud-properties?${params.toString()}`,
      );
      return data;
    },
  });
}
