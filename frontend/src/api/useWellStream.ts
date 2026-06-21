import { useEffect, useRef, useState } from 'react';
import { ReconnectingWebSocket, type WsStatus } from './ws';
import type {
  IngestCurves,
  IngestPoint,
  WsServerMessage,
  WellStatus,
} from './types';

/**
 * Buffered live state for a single subscribed well.
 *
 * `curves` holds a fixed-window ring (last `windowSize` points per mnemonic)
 * built from the WS `snapshot` (seed) and subsequent `data` frames (append).
 * `rev` is a monotonically increasing revision counter that bumps on every
 * mutation so consumers (charts, readouts) can cheaply detect new data.
 */
export interface WellStreamState {
  status: WsStatus;
  /** Mnemonic -> windowed points. Mutated in place; read via `rev`. */
  curves: IngestCurves;
  /** Bumps whenever curves change. */
  rev: number;
  /** Latest `status` frame from the server, if any. */
  wells: WellStatus[] | null;
}

function isServerMessage(d: unknown): d is WsServerMessage {
  return !!d && typeof d === 'object' && 'type' in (d as Record<string, unknown>);
}

function appendWindowed(
  target: IngestCurves,
  incoming: IngestCurves,
  windowSize: number,
  replace: boolean,
): boolean {
  let changed = false;
  for (const mnem of Object.keys(incoming)) {
    const pts = incoming[mnem];
    if (!pts || pts.length === 0) continue;
    const existing = replace ? [] : target[mnem] ?? [];
    const merged: IngestPoint[] = existing.concat(pts);
    // Fixed-window scroll: keep only the last `windowSize` points.
    target[mnem] =
      merged.length > windowSize ? merged.slice(merged.length - windowSize) : merged;
    changed = true;
  }
  return changed;
}

/**
 * Open ONE WebSocket subscription for `wellUid` and expose a live, windowed
 * buffer of its curves. Designed so multiple consumers (several readouts plus
 * a chart) share a single connection: render this hook once near the top of
 * the dashboard and thread its state down via props.
 *
 * The socket is (re)subscribed when `wellUid` changes and fully closed on
 * unmount, satisfying the "subscribe on select, unsubscribe/resubscribe on
 * change" contract.
 */
export function useWellStream(
  wellUid: string | null,
  windowSize = 500,
): WellStreamState {
  const [status, setStatus] = useState<WsStatus>('idle');
  const [wells, setWells] = useState<WellStatus[] | null>(null);
  const [rev, setRev] = useState(0);

  // The curve buffer is a mutable ref so high-frequency appends do not churn
  // React state; `rev` is the signal that drives re-render.
  const curvesRef = useRef<IngestCurves>({});

  useEffect(() => {
    // Reset buffers whenever the viewed well changes.
    curvesRef.current = {};
    setRev((r) => r + 1);

    if (!wellUid) {
      setStatus('idle');
      return;
    }

    const socket = new ReconnectingWebSocket();

    const offStatus = socket.onStatus(setStatus);
    const offMessage = socket.onMessage((data: unknown) => {
      if (!isServerMessage(data)) return;

      if (data.type === 'status') {
        const msg = data as { wells?: WellStatus[] };
        if (Array.isArray(msg.wells)) setWells(msg.wells);
        return;
      }

      if (data.type === 'snapshot' || data.type === 'data') {
        const msg = data as { wellUid?: string; curves?: IngestCurves };
        // Ignore frames for a well we are not currently viewing.
        if (msg.wellUid && msg.wellUid !== wellUid) return;
        if (!msg.curves) return;
        const changed = appendWindowed(
          curvesRef.current,
          msg.curves,
          windowSize,
          data.type === 'snapshot', // snapshot seeds/replaces, data appends
        );
        if (changed) setRev((r) => r + 1);
      }
    });

    socket.connect();
    socket.subscribe(wellUid);

    return () => {
      offMessage();
      offStatus();
      socket.unsubscribe(wellUid);
      socket.close();
    };
  }, [wellUid, windowSize]);

  return { status, curves: curvesRef.current, rev, wells };
}
