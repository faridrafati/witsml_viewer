import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query';
import { http } from './http';
import type { AccessLevel, AuthUser } from '../store/auth';

/**
 * React Query hooks for the admin console:
 *   - Users        (CRUD + page grants)  -> /api/admin/users
 *   - Servers      (CRUD + connection test) -> /api/servers
 *   - Units        (list/create)         -> /api/units
 *   - Pages        (for the grant picker) -> /api/pages
 *
 * Shapes mirror the documented backend contracts (app/db/models.py). The
 * bearer token is attached by the interceptor registered in src/api/auth.ts.
 */

/* ------------------------------------------------------------------ */
/* Users                                                              */
/* ------------------------------------------------------------------ */

export interface AdminUser extends AuthUser {
  page_grants?: number[];
}

export interface CreateUserBody {
  username: string;
  password: string;
  first_name?: string | null;
  last_name?: string | null;
  phone?: string | null;
  address?: string | null;
  position?: string | null;
  access_level?: AccessLevel;
  is_active?: boolean;
}

export interface UpdateUserBody {
  password?: string;
  first_name?: string | null;
  last_name?: string | null;
  phone?: string | null;
  address?: string | null;
  position?: string | null;
  access_level?: AccessLevel;
  is_active?: boolean;
}

const USERS_KEY = ['admin', 'users'] as const;

export function useUsers(): UseQueryResult<AdminUser[]> {
  return useQuery<AdminUser[]>({
    queryKey: USERS_KEY,
    queryFn: async () => {
      const { data } = await http.get<AdminUser[]>('/admin/users');
      return data;
    },
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CreateUserBody) => {
      const { data } = await http.post<AdminUser>('/admin/users', body);
      return data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: USERS_KEY });
    },
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, body }: { id: number; body: UpdateUserBody }) => {
      const { data } = await http.put<AdminUser>(`/admin/users/${id}`, body);
      return data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: USERS_KEY });
    },
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await http.delete(`/admin/users/${id}`);
      return id;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: USERS_KEY });
    },
  });
}

/** Replace the set of page ids a user may access. */
export function useSetUserPages() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, pageIds }: { id: number; pageIds: number[] }) => {
      const { data } = await http.put<AdminUser>(`/admin/users/${id}/pages`, {
        page_ids: pageIds,
      });
      return data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: USERS_KEY });
    },
  });
}

/* ------------------------------------------------------------------ */
/* Server connections                                                 */
/* ------------------------------------------------------------------ */

export interface ServerConnection {
  id: number;
  name: string;
  url: string;
  username: string;
  verify_ssl: boolean;
  version?: string | null;
}

export interface CreateServerBody {
  name: string;
  url: string;
  username: string;
  password: string;
  verify_ssl?: boolean;
}

export interface UpdateServerBody {
  name?: string;
  url?: string;
  username?: string;
  password?: string;
  verify_ssl?: boolean;
}

export interface TestServerResult {
  ok: boolean;
  version?: string | null;
  detail?: string | null;
}

const SERVERS_KEY = ['admin', 'servers'] as const;

export function useServers(): UseQueryResult<ServerConnection[]> {
  return useQuery<ServerConnection[]>({
    queryKey: SERVERS_KEY,
    queryFn: async () => {
      const { data } = await http.get<ServerConnection[]>('/servers');
      return data;
    },
  });
}

export function useCreateServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CreateServerBody) => {
      const { data } = await http.post<ServerConnection>('/servers', body);
      return data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: SERVERS_KEY });
    },
  });
}

export function useUpdateServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, body }: { id: number; body: UpdateServerBody }) => {
      const { data } = await http.put<ServerConnection>(`/servers/${id}`, body);
      return data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: SERVERS_KEY });
    },
  });
}

export function useDeleteServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await http.delete(`/servers/${id}`);
      return id;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: SERVERS_KEY });
    },
  });
}

export function useTestServer() {
  return useMutation({
    mutationFn: async (id: number) => {
      const { data } = await http.post<TestServerResult>(`/servers/${id}/test`);
      return data;
    },
  });
}

/* ------------------------------------------------------------------ */
/* Units                                                              */
/* ------------------------------------------------------------------ */

export interface UnitDef {
  id: number;
  name: string;
  from_unit: string;
  to_unit: string;
  expression: string;
  is_builtin: boolean;
}

export interface CreateUnitBody {
  name: string;
  from_unit: string;
  to_unit: string;
  expression: string;
  is_builtin?: boolean;
}

const UNITS_KEY = ['admin', 'units'] as const;

export function useUnits(): UseQueryResult<UnitDef[]> {
  return useQuery<UnitDef[]>({
    queryKey: UNITS_KEY,
    queryFn: async () => {
      const { data } = await http.get<UnitDef[]>('/units/');
      return data;
    },
  });
}

export function useCreateUnit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CreateUnitBody) => {
      const { data } = await http.post<UnitDef>('/units/', body);
      return data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: UNITS_KEY });
    },
  });
}

/* ------------------------------------------------------------------ */
/* Pages (for the grant picker)                                       */
/* ------------------------------------------------------------------ */

export interface PageSummary {
  id: number;
  name: string;
}

export function usePageSummaries(): UseQueryResult<PageSummary[]> {
  return useQuery<PageSummary[]>({
    queryKey: ['admin', 'page-summaries'],
    queryFn: async () => {
      const { data } = await http.get<PageSummary[]>('/pages');
      return data.map((p) => ({ id: p.id, name: p.name }));
    },
  });
}
