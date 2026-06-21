import { useQuery } from '@tanstack/react-query';
import { http, healthURL } from './http';
import axios from 'axios';
import type { Well, Wellbore, LogHeader, WellTreeNode } from './types';

/**
 * React Query hooks. All network access happens lazily inside these hooks;
 * nothing is requested at module-evaluation time.
 */

export interface HealthStatus {
  status: string;
  [k: string]: unknown;
}

export function useHealth() {
  return useQuery<HealthStatus>({
    queryKey: ['health'],
    queryFn: async () => {
      const { data } = await axios.get<HealthStatus>(healthURL, { timeout: 5000 });
      return data;
    },
    refetchInterval: 15_000,
    retry: 1,
  });
}

export function useWells() {
  return useQuery<Well[]>({
    queryKey: ['wells'],
    queryFn: async () => {
      const { data } = await http.get<Well[]>('/wells');
      return data;
    },
  });
}

/**
 * The well -> wellbore tree. Falls back to composing the tree client-side
 * if the backend does not expose a dedicated /tree endpoint.
 */
export function useTree() {
  return useQuery<WellTreeNode[]>({
    queryKey: ['tree'],
    queryFn: async () => {
      const { data } = await http.get<WellTreeNode[]>('/tree');
      return data;
    },
  });
}

export function useWellbores(wellUid: string | null) {
  return useQuery<Wellbore[]>({
    queryKey: ['wellbores', wellUid],
    enabled: !!wellUid,
    queryFn: async () => {
      const { data } = await http.get<Wellbore[]>(`/wells/${wellUid}/wellbores`);
      return data;
    },
  });
}

export function useLogs(wellUid: string | null, wellboreUid: string | null) {
  return useQuery<LogHeader[]>({
    queryKey: ['logs', wellUid, wellboreUid],
    enabled: !!wellUid && !!wellboreUid,
    queryFn: async () => {
      const { data } = await http.get<LogHeader[]>(
        `/wells/${wellUid}/wellbores/${wellboreUid}/logs`,
      );
      return data;
    },
  });
}
