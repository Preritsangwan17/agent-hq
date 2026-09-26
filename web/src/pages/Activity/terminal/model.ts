/** Activity terminal model: level / type-group metadata, persisted filter state and the row predicate. */
import type { EventLevel, HQEvent } from '@/lib/types';

export const LEVELS: readonly EventLevel[] = ['debug', 'info', 'warn', 'error', 'alert'];

export const LEVEL_META: Readonly<Record<EventLevel, { label: string; short: string; color: string; text: string }>> = {
  debug: { label: 'debug', short: 'DBG', color: '#64748B', text: '#7C8798' },
  info: { label: 'info', short: 'INF', color: '#7DD3FC', text: '#D5DBE6' },
  warn: { label: 'warn', short: 'WRN', color: '#FBBF24', text: '#FDE68A' },
  error: { label: 'error', short: 'ERR', color: '#F87171', text: '#FECACA' },
  alert: { label: 'alert', short: 'ALR', color: '#E879F9', text: '#F5D0FE' },
};

export interface TypeGroup {
  id: string;
  label: string;
  match: (type: string) => boolean;
}

export const TYPE_GROUPS: readonly TypeGroup[] = [
  { id: 'task', label: 'task', match: (t) => t.startsWith('task.') && t !== 'task.handoff' },
  { id: 'handoff', label: 'handoff', match: (t) => t === 'task.handoff' },
  { id: 'opp', label: 'opp', match: (t) => t.startsWith('opp.') },
  { id: 'needs', label: 'needs', match: (t) => t.startsWith('needs.') },
  { id: 'agent', label: 'agent', match: (t) => t.startsWith('agent.') },
  { id: 'control', label: 'control', match: (t) => t.startsWith('control.') || t.startsWith('settings.') },
  { id: 'mail', label: 'mail', match: (t) => t.startsWith('mail.') },
  { id: 'notification', label: 'notify', match: (t) => t === 'notification' },
  { id: 'worker', label: 'worker', match: (t) => t.startsWith('worker.') },
  { id: 'log', label: 'log', match: (t) => t === 'log' },
];

export function typeGroup(type: string): string {
  for (const g of TYPE_GROUPS) if (g.match(type)) return g.id;
  return 'other';
}

/** agent chip key: agent id, or "system" for events without an agent */
export const SYSTEM = 'system';
export const agentKey = (e: HQEvent) => e.agent_id ?? SYSTEM;

export interface ActivityFilters {
  hiddenAgents: string[];
  hiddenLevels: EventLevel[];
  hiddenTypes: string[];
  q: string;
}

export const DEFAULT_ACTIVITY_FILTERS: ActivityFilters = { hiddenAgents: [], hiddenLevels: ['debug'], hiddenTypes: [], q: '' };

export function normalizeActivityFilters(f: Partial<ActivityFilters> | null | undefined): ActivityFilters {
  const d = DEFAULT_ACTIVITY_FILTERS;
  return {
    hiddenAgents: Array.isArray(f?.hiddenAgents) ? f.hiddenAgents : d.hiddenAgents,
    hiddenLevels: Array.isArray(f?.hiddenLevels) ? f.hiddenLevels : d.hiddenLevels,
    hiddenTypes: Array.isArray(f?.hiddenTypes) ? f.hiddenTypes : d.hiddenTypes,
    q: typeof f?.q === 'string' ? f.q : '',
  };
}

export function makePredicate(f: ActivityFilters, q: string): (e: HQEvent) => boolean {
  const ha = new Set(f.hiddenAgents);
  const hl = new Set<string>(f.hiddenLevels);
  const ht = new Set(f.hiddenTypes);
  const needle = q.trim().toLowerCase();
  return (e) => {
    if (hl.has(e.level)) return false;
    if (ha.size && ha.has(agentKey(e))) return false;
    if (ht.size && ht.has(typeGroup(e.type))) return false;
    if (needle) {
      const hay = `${e.message} ${e.type} ${e.agent_id ?? ''}`.toLowerCase();
      if (!hay.includes(needle)) return false;
    }
    return true;
  };
}

/** Toggle `key` in a hidden-list; `solo` shows only `key` (or everything, if it was already solo). */
export function toggleHidden<T extends string>(hidden: readonly T[], key: T, all: readonly T[], solo: boolean): T[] {
  if (solo) {
    const others = all.filter((k) => k !== key);
    const alreadySolo = !hidden.includes(key) && others.every((k) => hidden.includes(k));
    return alreadySolo ? [] : others;
  }
  return hidden.includes(key) ? hidden.filter((k) => k !== key) : [...hidden, key];
}

/** Per-minute counts for the last `minutes` minutes (oldest first). */
export function perMinute(events: readonly HQEvent[], now: number, minutes = 30): number[] {
  const out = new Array<number>(minutes).fill(0);
  const start = now - minutes * 60_000;
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    const t = Date.parse(e.ts);
    if (!Number.isFinite(t)) continue;
    if (t < start) break;
    if (e.level === 'debug') continue;
    const idx = Math.min(minutes - 1, Math.floor((t - start) / 60_000));
    out[idx]++;
  }
  return out;
}
