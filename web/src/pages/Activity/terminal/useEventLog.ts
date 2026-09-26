/**
 * The terminal's event buffer: starts from the store's events, keeps appending what the stream delivers (beyond
 * the store's 2000 ring buffer, up to LOG_CAP), and can page older history from GET /api/events?before=.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { useHQ } from '@/lib/store';
import type { HQEvent } from '@/lib/types';

export const LOG_CAP = 10_000;
const PAGE = 200;

export interface EventLog {
  /** oldest first */
  events: HQEvent[];
  loadOlder: () => Promise<number>;
  loadingOlder: boolean;
  /** the server has nothing older */
  exhausted: boolean;
  olderError: string | null;
}

function appendNewer(prev: HQEvent[], incoming: readonly HQEvent[]): HQEvent[] {
  const last = prev.length ? prev[prev.length - 1].id : -Infinity;
  let i = incoming.length;
  while (i > 0 && incoming[i - 1].id > last) i--;
  if (i === incoming.length) return prev;
  const next = prev.concat(incoming.slice(i));
  return next.length > LOG_CAP ? next.slice(next.length - LOG_CAP) : next;
}

export function useEventLog(): EventLog {
  const [events, setEvents] = useState<HQEvent[]>(() => useHQ.getState().events.slice());
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [exhausted, setExhausted] = useState(false);
  const [olderError, setOlderError] = useState<string | null>(null);
  const firstId = useRef<number | null>(null);
  firstId.current = events[0]?.id ?? null;

  useEffect(() => {
    setEvents((prev) => appendNewer(prev, useHQ.getState().events));
    return useHQ.subscribe((s, p) => {
      if (s.events !== p.events) setEvents((prev) => appendNewer(prev, s.events));
    });
  }, []);

  const loadOlder = useCallback(async () => {
    const before = firstId.current;
    if (before == null) return 0;
    setLoadingOlder(true);
    setOlderError(null);
    try {
      const r = await api.events({ before, limit: PAGE });
      const older = r.events.filter((e) => e.id < before).sort((a, b) => a.id - b.id);
      if (older.length < PAGE) setExhausted(true);
      if (older.length) {
        setEvents((prev) => {
          const head = prev[0]?.id ?? Infinity;
          return [...older.filter((e) => e.id < head), ...prev];
        });
      }
      return older.length;
    } catch (err) {
      setOlderError(err instanceof Error ? err.message : String(err));
      return 0;
    } finally {
      setLoadingOlder(false);
    }
  }, []);

  return { events, loadOlder, loadingOlder, exhausted, olderError };
}
