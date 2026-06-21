/**
 * ReconnectingWebSocket
 *
 * A thin auto-reconnecting WebSocket wrapper used for live curve / event
 * streaming. It connects to `${VITE_WS_BASE_URL}/ws` and supports:
 *   - exponential backoff reconnect
 *   - per-well subscription (re-sent automatically on reconnect)
 *   - a Last-Event-ID style resume placeholder so the server can replay
 *     anything missed during a disconnect.
 *
 * Nothing connects at import time; call `connect()` explicitly from a
 * component / effect.
 */

export type WsMessageHandler = (data: unknown) => void;
export type WsStatus = 'idle' | 'connecting' | 'open' | 'closed';

export interface ReconnectingWebSocketOptions {
  /** Override the base URL (defaults to import.meta.env.VITE_WS_BASE_URL). */
  baseUrl?: string;
  /** Initial reconnect delay in ms (doubles up to maxDelayMs). */
  minDelayMs?: number;
  maxDelayMs?: number;
}

export class ReconnectingWebSocket {
  private ws: WebSocket | null = null;
  private url: string;
  private minDelay: number;
  private maxDelay: number;
  private currentDelay: number;
  private shouldRun = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  private subscribedWells = new Set<string>();
  private messageHandlers = new Set<WsMessageHandler>();
  private statusHandlers = new Set<(s: WsStatus) => void>();

  /** Last event id seen, for resume-on-reconnect. */
  private lastEventId: string | null = null;

  constructor(opts: ReconnectingWebSocketOptions = {}) {
    const base = opts.baseUrl ?? import.meta.env.VITE_WS_BASE_URL ?? 'ws://localhost:8000';
    this.url = `${base.replace(/\/$/, '')}/ws`;
    this.minDelay = opts.minDelayMs ?? 1000;
    this.maxDelay = opts.maxDelayMs ?? 30_000;
    this.currentDelay = this.minDelay;
  }

  connect(): void {
    this.shouldRun = true;
    this.open();
  }

  private open(): void {
    if (!this.shouldRun) return;
    this.setStatus('connecting');

    // Pass resume token as a query param (Last-Event-ID style placeholder).
    const resume = this.lastEventId ? `?lastEventId=${encodeURIComponent(this.lastEventId)}` : '';
    let socket: WebSocket;
    try {
      socket = new WebSocket(`${this.url}${resume}`);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = socket;

    socket.onopen = () => {
      this.currentDelay = this.minDelay;
      this.setStatus('open');
      // Re-send all active subscriptions after a (re)connect.
      for (const wellUid of this.subscribedWells) {
        this.send({ type: 'subscribe', wellUid });
      }
    };

    socket.onmessage = (ev: MessageEvent) => {
      let data: unknown = ev.data;
      try {
        data = JSON.parse(ev.data as string);
      } catch {
        /* leave as raw string */
      }
      if (data && typeof data === 'object' && 'eventId' in (data as Record<string, unknown>)) {
        this.lastEventId = String((data as Record<string, unknown>).eventId);
      }
      for (const h of this.messageHandlers) h(data);
    };

    socket.onclose = () => {
      this.setStatus('closed');
      this.scheduleReconnect();
    };

    socket.onerror = () => {
      // onclose will follow and handle reconnect.
      try {
        socket.close();
      } catch {
        /* ignore */
      }
    };
  }

  private scheduleReconnect(): void {
    if (!this.shouldRun || this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.open();
    }, this.currentDelay);
    this.currentDelay = Math.min(this.currentDelay * 2, this.maxDelay);
  }

  private send(payload: unknown): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    }
  }

  /** Subscribe to live updates for a well. Persists across reconnects. */
  subscribe(wellUid: string): void {
    this.subscribedWells.add(wellUid);
    this.send({ type: 'subscribe', wellUid });
  }

  unsubscribe(wellUid: string): void {
    this.subscribedWells.delete(wellUid);
    this.send({ type: 'unsubscribe', wellUid });
  }

  /** Register a message handler. Returns an unsubscribe function. */
  onMessage(handler: WsMessageHandler): () => void {
    this.messageHandlers.add(handler);
    return () => this.messageHandlers.delete(handler);
  }

  onStatus(handler: (s: WsStatus) => void): () => void {
    this.statusHandlers.add(handler);
    return () => this.statusHandlers.delete(handler);
  }

  private setStatus(s: WsStatus): void {
    for (const h of this.statusHandlers) h(s);
  }

  close(): void {
    this.shouldRun = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        /* ignore */
      }
      this.ws = null;
    }
  }
}
