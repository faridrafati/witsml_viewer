import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query';
import { http } from './http';

/**
 * React Query hooks for the dashboard "dynamic pages" feature (brief §7.5) and
 * the parameter catalog used by the component builder.
 *
 * The page `layout` is opaque JSON owned by the frontend (see
 * `PageLayout` below); the backend simply persists, lists, duplicates and
 * scopes it. All fetching happens lazily inside the hooks.
 */

/* ------------------------------------------------------------------ */
/* Page layout JSON shape (frontend-owned; must round-trip on save)   */
/* ------------------------------------------------------------------ */

export type ComponentType = 'numeric' | 'chart' | 'strip';
export type TimeAxis = 'time' | 'depth';

export interface ComponentGrid {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ComponentUi {
  lineColor: string;
  lineStroke: number;
  min: number | null;
  max: number | null;
  unit: string | null;
}

export interface BackConfig {
  backgroundColor: string;
}

export interface CommentConfig {
  text: string;
  isVisible: boolean;
}

export interface TimeConfig {
  axis: TimeAxis;
}

export interface DashboardComponentConfig {
  id: string;
  type: ComponentType;
  mnemonics: string[];
  title: string;
  grid: ComponentGrid;
  ui: ComponentUi;
  back_config: BackConfig;
  comment_config: CommentConfig;
  time_config: TimeConfig;
}

export interface PageLayout {
  components: DashboardComponentConfig[];
}

/* ------------------------------------------------------------------ */
/* Page DTOs (mirror app/api/pages.py)                                */
/* ------------------------------------------------------------------ */

export interface DashboardPageDto {
  id: number;
  name: string;
  well_uid: string | null;
  well_name: string | null;
  region: string | null;
  owner_id: number | null;
  layout: PageLayout;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CreatePageBody {
  name: string;
  well_uid?: string | null;
  well_name?: string | null;
  region?: string | null;
  layout?: PageLayout;
}

export interface UpdatePageBody {
  name?: string;
  well_uid?: string | null;
  well_name?: string | null;
  region?: string | null;
  layout?: PageLayout;
}

const PAGES_KEY = ['pages'] as const;

/** List all saved dashboard pages. */
export function usePages(): UseQueryResult<DashboardPageDto[]> {
  return useQuery<DashboardPageDto[]>({
    queryKey: PAGES_KEY,
    queryFn: async () => {
      const { data } = await http.get<DashboardPageDto[]>('/pages');
      return data;
    },
  });
}

/** Fetch a single page by id (for the editor/viewer). */
export function useGetPage(
  id: number | null,
): UseQueryResult<DashboardPageDto> {
  return useQuery<DashboardPageDto>({
    queryKey: ['pages', id],
    enabled: id != null,
    queryFn: async () => {
      const { data } = await http.get<DashboardPageDto>(`/pages/${id}`);
      return data;
    },
  });
}

export function useCreatePage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CreatePageBody) => {
      const { data } = await http.post<DashboardPageDto>('/pages', body);
      return data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: PAGES_KEY });
    },
  });
}

export function useUpdatePage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, body }: { id: number; body: UpdatePageBody }) => {
      const { data } = await http.put<DashboardPageDto>(`/pages/${id}`, body);
      return data;
    },
    onSuccess: (page) => {
      void qc.invalidateQueries({ queryKey: PAGES_KEY });
      void qc.invalidateQueries({ queryKey: ['pages', page.id] });
    },
  });
}

export function useDeletePage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await http.delete(`/pages/${id}`);
      return id;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: PAGES_KEY });
    },
  });
}

export function useDuplicatePage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, name }: { id: number; name?: string }) => {
      const params = name ? `?name=${encodeURIComponent(name)}` : '';
      const { data } = await http.post<DashboardPageDto>(
        `/pages/${id}/duplicate${params}`,
      );
      return data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: PAGES_KEY });
    },
  });
}

/* ------------------------------------------------------------------ */
/* Parameter catalog                                                  */
/* ------------------------------------------------------------------ */

/** One entry of the mnemonic dictionary (ParameterCatalog). */
export interface ParameterDef {
  mnemonic: string;
  description?: string | null;
  default_unit?: string | null;
  wits_id?: string | null;
}

/**
 * The mnemonic catalog used to populate the component builder's picker.
 *
 * Primary source is GET /api/parameters. The endpoint may not be mounted in
 * every deployment, so on any failure we fall back to a small built-in list of
 * common mudlogging mnemonics rather than leaving the picker empty.
 */
const FALLBACK_PARAMETERS: ParameterDef[] = [
  { mnemonic: 'DEPTH', description: 'Measured depth', default_unit: 'm' },
  { mnemonic: 'ROP', description: 'Rate of penetration', default_unit: 'm/h' },
  { mnemonic: 'WOB', description: 'Weight on bit', default_unit: 'klbf' },
  { mnemonic: 'RPM', description: 'Rotary speed', default_unit: 'rpm' },
  { mnemonic: 'TORQUE', description: 'Torque', default_unit: 'kN.m' },
  { mnemonic: 'SPP', description: 'Standpipe pressure', default_unit: 'kPa' },
  { mnemonic: 'TOTGAS', description: 'Total gas', default_unit: '%' },
  { mnemonic: 'FLOWIN', description: 'Flow in', default_unit: 'L/min' },
  { mnemonic: 'HKLD', description: 'Hook load', default_unit: 'klbf' },
  { mnemonic: 'MWIN', description: 'Mud weight in', default_unit: 'kg/m3' },
  { mnemonic: 'LITH', description: 'Lithology', default_unit: null },
];

export function useParameters(): UseQueryResult<ParameterDef[]> {
  return useQuery<ParameterDef[]>({
    queryKey: ['parameters'],
    staleTime: 5 * 60_000,
    queryFn: async () => {
      try {
        const { data } = await http.get<ParameterDef[]>('/parameters');
        if (Array.isArray(data) && data.length > 0) return data;
        return FALLBACK_PARAMETERS;
      } catch {
        return FALLBACK_PARAMETERS;
      }
    },
  });
}
