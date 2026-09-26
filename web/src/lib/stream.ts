/**
 * SSE client for GET /api/stream (CONTRACT §4).
 * - `EventSource(withCredentials)`; resumes with `?after=<lastEventId>` (a fresh EventSource cannot set
 *   Last-Event-ID), so the server replays missed events or sends `resync` → we refetch /api/snapshot.
 * - Own reconnect loop with jittered exponential backoff (1 s → 30 s); a watchdog reopens the stream if nothing
 *   (not even the 10 s worker heartbeat) arrives for 75 s, and we reconnect immediately on `online`/tab focus.
 * - Messages are handed to the store's per-frame batcher; connection status lives in `useHQ().conn`.
 */
import { useEffect } from 'react';
import { api } from './api';
import { enqueueStream, loadSnapshot, useHQ } from './store';
import { EVENT_TYPES, type AgentLive, type HQEvent } from './types';

const MAX_BACKOFF_MS = 30_000;
/**
 * EventSource only delivers named events we subscribe to. Contract types live in `EVENT_TYPES` (types.ts);
 * these are tolerated extras the backend may emit. Unnamed frames (`message`) are always received.
 */
const EXTRA_EVENT_TYPES = [
  'task.cancelled', 'task.deferred', 'agent.invalid', 'agent.error', 'budget.deferred',
  // phase (b): models, benchmarks, roles, Claude budget
  'model.discovered', 'model.status', 'benchmark.started', 'benchmark.progress', 'benchmark.done', 'roles.updated',
  'budget.updated', 'budget.capped', 'claude.status',
  // settings / pipeline / inbox / strategist (phases c–e)
  'profile.updated', 'source.updated', 'fetch.error', 'gate.result', 'document.created', 'application.updated',
  'mail.received', 'mail.classified', 'thread.locked', 'thread.unlocked', 'followup.scheduled', 'strategy.report',
  'golive.updated',
];
const STALE_MS = 75_000;

class HQStream {
  private es: EventSource | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private watchdog: ReturnType<typeof setInterval> | undefined;
  private attempts = 0;
  private running = false;
  private lastMsgAt = 0;
  private lastConnStamp = 0;
  private resyncing = false;

  start(): void {
    if (this.running) return;
    this.running = true;
    this.attempts = 0;
    this.open();
    this.watchdog = setInterval(this.checkStale, 10_000);
    window.addEventListener('online', this.kick);
    document.addEventListener('visibilitychange', this.onVisible);
  }

  stop(): void {
    this.running = false;
    clearTimeout(this.retryTimer);
    clearInterval(this.watchdog);
    window.removeEventListener('online', this.kick);
    document.removeEventListener('visibilitychange', this.onVisible);
    this.close();
    useHQ.getState().setConn({ sse: 'closed' });
  }

  /** Force an immediate reconnect (e.g. after login or when the user clicks the status dot). */
  reconnect(): void {
    if (!this.running) return;
    clearTimeout(this.retryTimer);
    this.close();
    this.attempts = 0;
    this.open();
  }

  private close(): void {
    if (this.es) {
      this.es.onopen = null;
      this.es.onerror = null;
      this.es.close();
      this.es = null;
    }
  }

  private open(): void {
    const after = useHQ.getState().lastEventId;
    const url = `${import.meta.env.VITE_API_BASE ?? ''}/api/stream${after ? `?after=${after}` : ''}`;
    useHQ.getState().setConn({ sse: this.attempts ? 'reconnecting' : 'connecting', attempts: this.attempts });
    let es: EventSource;
    try {
      es = new EventSource(url, { withCredentials: true });
    } catch (err) {
      this.scheduleRetry(String(err));
      return;
    }
    this.es = es;
    this.lastMsgAt = Date.now();
    es.onopen = () => {
      this.attempts = 0;
      this.lastMsgAt = Date.now();
      useHQ.getState().setConn({ sse: 'open', attempts: 0, lastError: null, lastMessageAt: Date.now() });
    };
    es.onerror = (e) => {
      // A server-sent frame named `event: error` arrives here too (as a MessageEvent with data) — treat it as data.
      if (e instanceof MessageEvent && typeof e.data === 'string') {
        this.onEvent(e as MessageEvent<string>);
        return;
      }
      if (this.es !== es) return;
      this.close();
      this.scheduleRetry('stream error');
    };
    for (const t of [...EVENT_TYPES, ...EXTRA_EVENT_TYPES]) es.addEventListener(t, this.onEvent as EventListener);
    es.addEventListener('message', this.onEvent as EventListener);
    es.addEventListener('agent.live', this.onLive as EventListener);
    es.addEventListener('resync', this.onResync);
  }

  private scheduleRetry(reason: string): void {
    if (!this.running) return;
    this.attempts += 1;
    const base = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** (this.attempts - 1));
    const delay = Math.round(base * (0.8 + Math.random() * 0.4));
    useHQ.getState().setConn({ sse: 'reconnecting', attempts: this.attempts, lastError: reason });
    clearTimeout(this.retryTimer);
    this.retryTimer = setTimeout(() => this.open(), delay);
    // An EventSource can't see HTTP status; after repeated failures check whether the session expired.
    if (this.attempts === 3 || this.attempts % 6 === 0) {
      api.auth.me().catch((err: unknown) => {
        if ((err as { status?: number })?.status === 401 && !window.location.pathname.startsWith('/login')) {
          window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname)}`);
        }
      });
    }
  }

  private touch(): void {
    const now = Date.now();
    this.lastMsgAt = now;
    if (now - this.lastConnStamp > 1000) {
      this.lastConnStamp = now;
      useHQ.getState().setConn({ lastMessageAt: now });
    }
  }

  private onEvent = (e: MessageEvent<string>): void => {
    this.touch();
    let ev: HQEvent;
    try {
      ev = JSON.parse(e.data) as HQEvent;
    } catch {
      return;
    }
    if (!ev || typeof ev !== 'object') return;
    if (!ev.type && e.type !== 'message') ev.type = e.type;
    if (!ev.id && e.lastEventId) ev.id = Number(e.lastEventId) || 0;
    enqueueStream({ kind: 'event', event: ev });
  };

  private onLive = (e: MessageEvent<string>): void => {
    this.touch();
    try {
      const live = JSON.parse(e.data) as AgentLive;
      if (live?.agent_id) enqueueStream({ kind: 'live', live });
    } catch {
      /* ignore malformed frame */
    }
  };

  private onResync = (): void => {
    this.touch();
    if (this.resyncing) return;
    this.resyncing = true;
    loadSnapshot()
      .catch(() => undefined)
      .finally(() => {
        this.resyncing = false;
      });
  };

  private checkStale = (): void => {
    if (!this.running || !this.es) return;
    if (this.es.readyState === EventSource.OPEN && Date.now() - this.lastMsgAt > STALE_MS) {
      this.reconnect();
    }
  };

  private kick = (): void => {
    if (this.running && (!this.es || this.es.readyState === EventSource.CLOSED)) this.reconnect();
  };

  private onVisible = (): void => {
    if (!document.hidden) this.kick();
  };
}

export const hqStream = new HQStream();

/**
 * Mount once (app shell): loads the snapshot, then opens the stream. Retries the snapshot with backoff if the
 * server is down. Returns nothing — read `useHQ(s => s.ready / s.loadError / s.conn)`.
 */
export function useLiveConnection(enabled = true): void {
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    const boot = async () => {
      try {
        await loadSnapshot();
        if (!cancelled) hqStream.start();
      } catch {
        if (cancelled) return;
        attempt += 1;
        timer = setTimeout(boot, Math.min(MAX_BACKOFF_MS, 1000 * 2 ** attempt));
      }
    };
    void boot();
    return () => {
      cancelled = true;
      clearTimeout(timer);
      hqStream.stop();
    };
  }, [enabled]);
}

/** Connection status for UI (SSE state + consecutive failures). */
export function useStreamStatus() {
  return useHQ((s) => s.conn);
}
