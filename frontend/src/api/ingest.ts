import { useQuery } from '@tanstack/react-query';
import { http } from './http';
import type { WellStatus, WellCurvesResponse } from './types';

/**
 * React Query hooks for the live ingest layer.
 *
 *   useIngestWells()              -> GET /api/ingest/wells
 *   useWellCurves(uid, mnemonics) -> GET /api/ingest/wells/{uid}/curves
 *
 * As with the rest of the app, nothing is requested at module-evaluation
 * time; all fetching happens lazily inside the hooks.
 */

/** List all warm wells the ingest service is tracking. */
export function useIngestWells() {
  return useQuery<WellStatus[]>({
    queryKey: ['ingest', 'wells'],
    queryFn: async () => {
      const { data } = await http.get<WellStatus[]>('/ingest/wells');
      return data;
    },
    // Wells list is cheap and the WS `status` frames also refresh it; poll
    // as a fallback so the warm list stays current even without a socket.
    refetchInterval: 10_000,
  });
}

/**
 * Seed/backfill curve data for one well over REST. Primarily used to seed a
 * chart before the WS snapshot arrives, or for non-streaming reads.
 */
export function useWellCurves(
  uid: string | null,
  mnemonics: string[],
  limit = 500,
) {
  const mnemonicsKey = mnemonics.join(',');
  return useQuery<WellCurvesResponse>({
    queryKey: ['ingest', 'curves', uid, mnemonicsKey, limit],
    enabled: !!uid && mnemonics.length > 0,
    queryFn: async () => {
      const params = new URLSearchParams();
      if (mnemonicsKey) params.set('mnemonics', mnemonicsKey);
      params.set('limit', String(limit));
      const { data } = await http.get<WellCurvesResponse>(
        `/ingest/wells/${uid}/curves?${params.toString()}`,
      );
      return data;
    },
  });
}
