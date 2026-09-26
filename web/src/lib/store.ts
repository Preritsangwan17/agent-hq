/**
 * Global live state (zustand): the /api/snapshot plus everything the SSE stream changes afterwards.
 *
 * Incoming stream messages are queued with `enqueueStream()` and applied in ONE `set()` per animation frame
 * (copy-on-write maps, events ring buffer capped at 2000) so a burst of events never re-renders more than once
 * per frame. `task.handoff` events are re-emitted on `handoffBus` after the flush (graph particles), and every
 * applied event on `eventBus`.
 *
 * `live[agentId]` is the authoritative AgentLive (updated ~4/s per agent); `agents[id].live` is only the
 * snapshot copy and is not updated by the stream to avoid churning agent objects.
 */
import { useMemo } from 'react';
import { create } from 'zustand';
import { useShallow } from 'zustand/react/shallow';
import { api } from './api';
import { eventBus, handoffBus, type HandoffPulse } from './bus';
import type {
  Agent,
  AgentLive,
  AgentPatch,
  HQEvent,
  Need,
  OppSummary,
  Settings,
  Snapshot,
  Stage,
  Stats,
} from './types';

export const EVENTS_CAP = 2000;

export type SseStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed';

export interface ConnState {
  sse: SseStatus;
  /** consecutive failed attempts since the last successful open */
  attempts: number;
  /** epoch ms of the last message received (throttled to ~1 s resolution) */
  lastMessageAt: number | null;
  lastError: string | null;
}

export interface WorkerState {
  /** null = unknown yet */
  alive: boolean | null;
  heartbeatAt: string | null;
  version: string | null;
}

export type StreamMessage = { kind: 'event'; event: HQEvent } | { kind: 'live'; live: AgentLive };

export const DEFAULT_SETTINGS: Settings = {
  global_pause: false,
  freeze_outbound: false,
  mode: 'dry_run',
  autonomy: 'auto',
  sim_enabled: true,
  sim_speed: 1,
  keep_awake: true,
  eligibility_threshold: 0.8,
  min_pay_ratio: 1,
  funded_program_min_inr: 5000,
  fit_draft_threshold: 60,
  fit_polish_threshold: 75,
  daily_draft_cap: 20,
  cloud_daily_budget_usd: 2,
  cloud_daily_call_cap: 40,
  local_ai_enabled: true,
  grok_enabled: true,
  cloud_mode: 'saver',
  email_daily_cap: 10,
  quiet_hours: { enabled: false, start: '23:00', end: '07:00' },
  unknown_pay_policy: 'decision',
};

export interface HQState {
  /** snapshot loaded at least once */
  ready: boolean;
  loadError: string | null;
  settings: Settings;
  agents: Record<string, Agent>;
  /** display order of agents (snapshot order, new agents appended) */
  agentOrder: string[];
  live: Record<string, AgentLive>;
  opportunities: Record<string, OppSummary>;
  /** oldest first, at most EVENTS_CAP */
  events: HQEvent[];
  lastEventId: number;
  stats: Stats | null;
  needs: Record<string, Need>;
  serverTime: string | null;
  /** server_time − local time at snapshot (ms); add to Date.now() for server-aligned clocks */
  clockSkewMs: number;
  /** ISO time when the current global pause started (from control.pause), if known */
  pausedAt: string | null;
  pauseReason: string | null;
  worker: WorkerState;
  conn: ConnState;
  /** unacknowledged notifications (header bell) */
  notificationsUnacked: number;

  applySnapshot: (s: Snapshot) => void;
  setNotificationsUnacked: (n: number) => void;
  setStats: (s: Stats) => void;
  setConn: (p: Partial<ConnState>) => void;
  setWorker: (p: Partial<WorkerState>) => void;
  setLoadError: (msg: string | null) => void;
  /** local-only merge (use the async actions below to persist) */
  mergeSettings: (p: Partial<Settings>) => void;
  upsertOpp: (o: OppSummary) => void;
  upsertAgent: (a: Agent) => void;
  upsertNeed: (n: Need) => void;
}

export const useHQ = create<HQState>()((set) => ({
  ready: false,
  loadError: null,
  settings: DEFAULT_SETTINGS,
  agents: {},
  agentOrder: [],
  live: {},
  opportunities: {},
  events: [],
  lastEventId: 0,
  stats: null,
  needs: {},
  serverTime: null,
  clockSkewMs: 0,
  pausedAt: null,
  pauseReason: null,
  worker: { alive: null, heartbeatAt: null, version: null },
  conn: { sse: 'idle', attempts: 0, lastMessageAt: null, lastError: null },
  notificationsUnacked: 0,

  applySnapshot: (s) => {
    const agents: Record<string, Agent> = {};
    const live: Record<string, AgentLive> = {};
    for (const a of s.agents) {
      agents[a.id] = a;
      if (a.live) live[a.id] = a.live;
    }
    const opportunities: Record<string, OppSummary> = {};
    for (const o of s.opportunities) opportunities[o.id] = o;
    const needs: Record<string, Need> = {};
    for (const n of s.needs) needs[n.id] = n;
    const skew = Date.parse(s.server_time) - Date.now();
    set((prev) => ({
      ready: true,
      loadError: null,
      settings: { ...DEFAULT_SETTINGS, ...s.settings },
      agents,
      agentOrder: s.agents.map((a) => a.id),
      live,
      opportunities,
      needs,
      stats: s.stats,
      // keep newer local events if the snapshot is older than what we already streamed
      events: mergeEvents(s.events, prev.events.filter((e) => e.id > s.last_event_id)),
      lastEventId: Math.max(s.last_event_id, 0),
      serverTime: s.server_time,
      clockSkewMs: Number.isFinite(skew) ? skew : 0,
      pausedAt: s.settings.global_pause ? prev.pausedAt : null,
      pauseReason: s.settings.global_pause ? prev.pauseReason : null,
      notificationsUnacked: s.notifications_unacked ?? prev.notificationsUnacked,
    }));
  },
  setNotificationsUnacked: (n) => set({ notificationsUnacked: Math.max(0, n) }),
  setStats: (stats) => set({ stats }),
  setConn: (p) => set((st) => ({ conn: { ...st.conn, ...p } })),
  setWorker: (p) => set((st) => ({ worker: { ...st.worker, ...p } })),
  setLoadError: (loadError) => set({ loadError }),
  mergeSettings: (p) => set((st) => ({ settings: { ...st.settings, ...p } })),
  upsertOpp: (o) => set((st) => ({ opportunities: { ...st.opportunities, [o.id]: o } })),
  upsertAgent: (a) =>
    set((st) => ({
      agents: { ...st.agents, [a.id]: a },
      agentOrder: st.agentOrder.includes(a.id) ? st.agentOrder : [...st.agentOrder, a.id],
    })),
  upsertNeed: (n) => set((st) => ({ needs: { ...st.needs, [n.id]: n } })),
}));

function mergeEvents(base: HQEvent[], extra: HQEvent[]): HQEvent[] {
  const all = extra.length ? [...base, ...extra].sort((a, b) => a.id - b.id) : base.slice();
  return all.length > EVENTS_CAP ? all.slice(all.length - EVENTS_CAP) : all;
}

// ── per-frame batching ────────────────────────────────────────────────

let pending: StreamMessage[] = [];
let scheduled = false;
let rafId = 0;
let fallbackTimer: ReturnType<typeof setTimeout> | undefined;

/** Queue a stream message; applied on the next animation frame (or ≤400 ms when the tab is hidden). */
export function enqueueStream(msg: StreamMessage): void {
  pending.push(msg);
  if (scheduled) return;
  scheduled = true;
  if (typeof document !== 'undefined' && !document.hidden) rafId = requestAnimationFrame(flushStream);
  fallbackTimer = setTimeout(flushStream, document.hidden ? 250 : 400);
}

/** Apply all queued messages now (exported for tests/mocks). */
export function flushStream(): void {
  if (!scheduled) return;
  scheduled = false;
  cancelAnimationFrame(rafId);
  clearTimeout(fallbackTimer);
  const batch = pending;
  pending = [];
  if (batch.length) applyBatch(batch);
}

const STATS_EVENTS = /^(opp\.|needs\.|task\.(succeeded|dead))/;

function applyBatch(batch: StreamMessage[]): void {
  const s = useHQ.getState();
  let { agents, agentOrder, live, opportunities, needs, settings, worker, lastEventId, pausedAt, pauseReason } = s;
  let notificationsUnacked = s.notificationsUnacked;
  const cow = { agents: false, live: false, opps: false, needs: false };
  const fresh: HQEvent[] = [];
  const handoffs: HandoffPulse[] = [];
  let statsDirty = false;

  const touchAgents = () => {
    if (!cow.agents) {
      agents = { ...agents };
      cow.agents = true;
    }
  };
  const touchOpps = () => {
    if (!cow.opps) {
      opportunities = { ...opportunities };
      cow.opps = true;
    }
  };
  const touchNeeds = () => {
    if (!cow.needs) {
      needs = { ...needs };
      cow.needs = true;
    }
  };

  for (const m of batch) {
    if (m.kind === 'live') {
      if (!cow.live) {
        live = { ...live };
        cow.live = true;
      }
      live[m.live.agent_id] = m.live;
      continue;
    }
    const ev = m.event;
    if (ev.id && ev.id <= lastEventId) continue; // replay duplicate
    if (ev.id) lastEventId = ev.id;
    fresh.push(ev);
    if (STATS_EVENTS.test(ev.type)) statsDirty = true;
    const d = (ev.data ?? {}) as Record<string, any>;

    switch (ev.type) {
      case 'agent.status': {
        const a = ev.agent_id ? agents[ev.agent_id] : undefined;
        if (a && d.status && a.status !== d.status) {
          touchAgents();
          agents[a.id] = { ...a, status: d.status };
        }
        break;
      }
      case 'agent.added':
      case 'agent.updated': {
        const a = d.agent as Agent | undefined;
        if (a?.id) {
          touchAgents();
          agents[a.id] = a;
          if (!agentOrder.includes(a.id)) agentOrder = [...agentOrder, a.id];
        }
        break;
      }
      case 'agent.removed': {
        const id = (d.agent as Agent | undefined)?.id ?? ev.agent_id;
        if (id && agents[id]) {
          touchAgents();
          delete agents[id];
          agentOrder = agentOrder.filter((x) => x !== id);
        }
        break;
      }
      case 'opp.created':
      case 'opp.stage':
      case 'opp.updated': {
        const o = d.opp as OppSummary | undefined;
        if (o?.id) {
          touchOpps();
          opportunities[o.id] = o;
        }
        break;
      }
      case 'needs.created':
      case 'needs.updated': {
        const n = d.need as Need | undefined;
        if (n?.id) {
          touchNeeds();
          needs[n.id] = n;
        }
        break;
      }
      case 'control.pause':
        settings = { ...settings, global_pause: !!d.paused };
        pausedAt = d.paused ? ev.ts : null;
        pauseReason = d.paused ? (d.reason ?? null) : null;
        break;
      case 'control.freeze':
        settings = { ...settings, freeze_outbound: !!d.freeze_outbound };
        break;
      case 'settings.updated':
        if (d.settings && typeof d.settings === 'object') settings = { ...settings, ...d.settings };
        break;
      case 'mode.changed':
        if (typeof d.mode === 'string') settings = { ...settings, mode: d.mode as Settings['mode'] };
        break;
      case 'notification':
        notificationsUnacked += 1;
        break;
      case 'worker.heartbeat':
      case 'worker.started':
        worker = { ...worker, alive: true, heartbeatAt: ev.ts };
        break;
      case 'worker.stopped':
        worker = { ...worker, alive: false };
        break;
      case 'task.handoff':
        handoffs.push({
          id: ev.id,
          ts: ev.ts,
          from_agent: d.from_agent,
          to_agent: d.to_agent,
          capability: d.capability,
          opportunity_id: d.opportunity_id ?? ev.opportunity_id ?? null,
        });
        break;
      default:
        break;
    }
  }

  const patch: Partial<HQState> = { lastEventId };
  if (fresh.length) {
    const next = s.events.concat(fresh);
    patch.events = next.length > EVENTS_CAP ? next.slice(next.length - EVENTS_CAP) : next;
  }
  if (cow.agents) patch.agents = agents;
  if (agentOrder !== s.agentOrder) patch.agentOrder = agentOrder;
  if (cow.live) patch.live = live;
  if (cow.opps) patch.opportunities = opportunities;
  if (cow.needs) patch.needs = needs;
  if (settings !== s.settings) patch.settings = settings;
  if (notificationsUnacked !== s.notificationsUnacked) patch.notificationsUnacked = notificationsUnacked;
  if (worker !== s.worker) patch.worker = worker;
  if (pausedAt !== s.pausedAt) patch.pausedAt = pausedAt;
  if (pauseReason !== s.pauseReason) patch.pauseReason = pauseReason;
  useHQ.setState(patch);

  for (const h of handoffs) handoffBus.emit(h);
  for (const e of fresh) eventBus.emit(e);
  if (statsDirty) scheduleStatsRefresh();
}

// ── server sync helpers ───────────────────────────────────────────────

let statsTimer: ReturnType<typeof setTimeout> | undefined;
let lastStatsAt = 0;

/** Throttled GET /api/stats (≤ 1 per 2.5 s) after pipeline events. */
export function scheduleStatsRefresh(): void {
  if (statsTimer) return;
  const wait = Math.max(300, 2500 - (Date.now() - lastStatsAt));
  statsTimer = setTimeout(async () => {
    statsTimer = undefined;
    lastStatsAt = Date.now();
    try {
      useHQ.getState().setStats(await api.stats());
    } catch {
      /* next event retries */
    }
  }, wait);
}

/** GET /api/snapshot → store. Throws on failure (and records `loadError`). */
export async function loadSnapshot(): Promise<Snapshot> {
  try {
    const snap = await api.snapshot();
    useHQ.getState().applySnapshot(snap);
    return snap;
  } catch (err) {
    useHQ.getState().setLoadError(err instanceof Error ? err.message : String(err));
    throw err;
  }
}

// ── actions (optimistic where safe) ───────────────────────────────────

export async function pauseAll(reason = 'Kill switch (UI)'): Promise<void> {
  const st = useHQ.getState();
  const prev = st.settings.global_pause;
  st.mergeSettings({ global_pause: true });
  useHQ.setState({ pausedAt: new Date().toISOString(), pauseReason: reason });
  try {
    await api.pauseAll(reason);
  } catch (err) {
    useHQ.getState().mergeSettings({ global_pause: prev });
    throw err;
  }
}

export async function resumeAll(): Promise<void> {
  await api.resumeAll();
  useHQ.getState().mergeSettings({ global_pause: false });
  useHQ.setState({ pausedAt: null, pauseReason: null });
}

export async function setFreezeOutbound(on: boolean): Promise<void> {
  const r = await api.freezeOutbound(on);
  useHQ.getState().mergeSettings({ freeze_outbound: r.freeze_outbound });
}

export async function updateSettings(patch: Partial<Settings>): Promise<Settings> {
  const r = await api.patchSettings(patch);
  useHQ.getState().mergeSettings(r.settings);
  return r.settings;
}

export async function patchAgent(id: string, patch: AgentPatch): Promise<Agent> {
  const a = await api.patchAgent(id, patch);
  useHQ.getState().upsertAgent(a);
  return a;
}

export async function resolveNeed(
  id: string,
  status: 'done' | 'snoozed' | 'dismissed',
  snooze_hours?: number,
  choice?: string,
) {
  const n = await api.patchNeed(id, { status, snooze_hours, choice });
  useHQ.getState().upsertNeed(n);
  scheduleStatsRefresh();
  return n;
}

/** Display-only override (audited server-side; never triggers actions). */
export async function overrideStage(id: string, stage: Stage, reason: string): Promise<OppSummary> {
  const o = await api.setStage(id, stage, reason);
  useHQ.getState().upsertOpp(o);
  scheduleStatsRefresh();
  return o;
}

// ── selector hooks ────────────────────────────────────────────────────

export const useSettings = () => useHQ((s) => s.settings);
export const useIsPaused = () => useHQ((s) => !!s.settings.global_pause);
export const useAgent = (id: string | null | undefined) => useHQ((s) => (id ? s.agents[id] : undefined));
export const useAgentLive = (id: string | null | undefined) => useHQ((s) => (id ? s.live[id] : undefined));
export const useOpp = (id: string | null | undefined) => useHQ((s) => (id ? s.opportunities[id] : undefined));
export const useStats = () => useHQ((s) => s.stats);
export const useConn = () => useHQ((s) => s.conn);

/** Agents in display order. */
export function useAgentsList(): Agent[] {
  const [agents, order] = useHQ(useShallow((s) => [s.agents, s.agentOrder] as const));
  return useMemo(() => order.map((id) => agents[id]).filter(Boolean), [agents, order]);
}

/** All opportunities, most recently updated first. */
export function useOppList(): OppSummary[] {
  const opps = useHQ((s) => s.opportunities);
  return useMemo(() => Object.values(opps).sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1)), [opps]);
}

/** Open needs, most urgent first (priority desc, then due date). */
export function useOpenNeeds(): Need[] {
  const needs = useHQ((s) => s.needs);
  return useMemo(
    () =>
      Object.values(needs)
        .filter((n) => n.status === 'open')
        .sort((a, b) => b.priority - a.priority || (a.due_at ?? '9').localeCompare(b.due_at ?? '9')),
    [needs],
  );
}

export function useOpenNeedsCount(): number {
  return useHQ((s) => {
    let n = 0;
    for (const k in s.needs) if (s.needs[k].status === 'open') n++;
    return n;
  });
}
