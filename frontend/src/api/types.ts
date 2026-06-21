/**
 * TypeScript types mirroring the backend WITSML 1.4.1.1 domain model.
 * These are intentionally permissive where the WITSML spec allows optionals.
 */

export interface Well {
  uid: string;
  name: string;
  /** Operator / field region descriptor. */
  region?: string | null;
  country?: string | null;
  operator?: string | null;
  status?: string | null;
  /** Number of wellbores, if the backend pre-aggregates it. */
  wellboreCount?: number;
}

export interface Wellbore {
  uid: string;
  /** Parent well uid. */
  wellUid: string;
  name: string;
  status?: string | null;
  /** e.g. "drilling", "completed". */
  purposeRange?: string | null;
  mdCurrent?: number | null;
}

export interface LogHeader {
  uid: string;
  wellUid: string;
  wellboreUid: string;
  name: string;
  /** Index curve mnemonic, e.g. "DEPTH" or "TIME". */
  indexType: 'depth' | 'time' | string;
  indexCurve?: string;
  startIndex?: number | null;
  endIndex?: number | null;
  /** Curve mnemonics available in this log. */
  mnemonics: string[];
  unitsByMnemonic?: Record<string, string>;
}

export interface CurveSample {
  /** Index value (depth or time-epoch-ms depending on indexType). */
  index: number;
  /** Mnemonic -> value. Nulls represent gaps. */
  values: Record<string, number | null>;
}

export interface MudLog {
  uid: string;
  wellUid: string;
  wellboreUid: string;
  name: string;
  mdTop?: number | null;
  mdBottom?: number | null;
  intervals: GeologyInterval[];
}

export interface GeologyInterval {
  uid: string;
  mdTop: number;
  mdBottom: number;
  lithology?: string | null;
  description?: string | null;
  /** Optional show/gas readings attached to the interval. */
  gasReadingAvg?: number | null;
}

/**
 * Tree node returned by the /tree endpoint: a well with its nested wellbores.
 */
export interface WellTreeNode extends Well {
  wellbores: Wellbore[];
}

/* ------------------------------------------------------------------ */
/* Live ingest / streaming domain model                               */
/* ------------------------------------------------------------------ */

/**
 * A warm well as exposed by the ingest layer (GET /api/ingest/wells).
 * These are the wells the ingest service is actively tracking.
 */
export interface WellStatus {
  uid: string;
  name: string;
  /** Whether the well is currently receiving fresh data. */
  growing?: boolean;
  /** Epoch millis of the last update seen by the ingest service. */
  lastUpdate?: number | null;
  /** Optional index type so consumers can label the x-axis. */
  indexType?: 'depth' | 'time' | string;
  /** Current measured depth, if known. */
  mdCurrent?: number | null;
  status?: string | null;
}

/**
 * A single live sample for one mnemonic.
 *   i = index (epoch millis for time logs, float depth for depth logs)
 *   v = value
 *   u = unit of measure
 */
export interface IngestPoint {
  i: number;
  v: number;
  u?: string;
}

/** Mnemonic -> ordered samples. */
export type IngestCurves = Record<string, IngestPoint[]>;

/** Response of GET /api/ingest/wells/{uid}/curves. */
export interface WellCurvesResponse {
  wellUid: string;
  curves: IngestCurves;
}

/* WebSocket protocol message shapes. */
export interface WsSnapshotMessage {
  type: 'snapshot' | 'data';
  wellUid: string;
  curves: IngestCurves;
}

export interface WsStatusMessage {
  type: 'status';
  wells: WellStatus[];
}

export type WsServerMessage =
  | WsSnapshotMessage
  | WsStatusMessage
  | { type: string; [k: string]: unknown };
