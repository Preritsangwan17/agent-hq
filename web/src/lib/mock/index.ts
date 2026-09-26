/**
 * Mock mode (VITE_MOCK=1): patches `window.fetch` for `/api/*` and `window.EventSource` for `/api/stream`, both
 * answered by the in-browser Simulator, so api.ts / stream.ts / the store run their real code paths.
 *
 * Handy switches (query string, persisted in sessionStorage):
 *   ?mock_auth=out     → /api/auth/me returns 401 (see the login redirect)
 *   ?mock_setup=1      → /api/auth/status says {configured:false} (the "Set your passcode" screen)
 *   ?mock_speed=2      → sim_speed
 *   ?mock_paused=1     → start globally paused
 * Passcode "wrong" is rejected; anything else ≥ 6 chars logs in.
 */
import type { AgentConfig, AgentPatch, Stage } from '../types';
import { CAPABILITY_VOCAB, RESERVED_SIDE_EFFECTS } from './data';
import { Simulator, type SimMessage } from './sim';
import { AGENT_PALETTE } from '@/theme/tokens';

let sim: Simulator | null = null;

export function getSimulator(): Simulator {
  if (!sim) {
    sim = new Simulator();
    sim.start();
  }
  return sim;
}

const SS = {
  get(k: string): string | null {
    try {
      return sessionStorage.getItem(k);
    } catch {
      return null;
    }
  },
  set(k: string, v: string | null): void {
    try {
      if (v == null) sessionStorage.removeItem(k);
      else sessionStorage.setItem(k, v);
    } catch {
      /* private mode */
    }
  },
};

function readSwitches(): void {
  const q = new URLSearchParams(window.location.search);
  if (q.get('mock_auth') === 'out') SS.set('hq-mock-auth', 'out');
  if (q.get('mock_auth') === 'in') SS.set('hq-mock-auth', null);
  if (q.has('mock_setup')) SS.set('hq-mock-setup', q.get('mock_setup') === '1' ? '1' : null);
}

type Json = unknown;
const json = (status: number, body: Json) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const err = (status: number, error: string, detail?: unknown) => json(status, { error, detail });

async function readBody(init?: RequestInit): Promise<Record<string, unknown>> {
  if (!init?.body || typeof init.body !== 'string') return {};
  try {
    return JSON.parse(init.body) as Record<string, unknown>;
  } catch {
    return {};
  }
}

const PUBLIC = new Set(['/api/health', '/api/auth/status', '/api/auth/login', '/api/auth/setup', '/api/auth/logout']);

async function handle(url: URL, init: RequestInit | undefined): Promise<Response> {
  const s = getSimulator();
  const method = (init?.method ?? 'GET').toUpperCase();
  const path = url.pathname.replace(/\/+$/, '');
  const q = url.searchParams;
  const loggedIn = SS.get('hq-mock-auth') !== 'out';

  if (method !== 'GET') {
    const h = new Headers(init?.headers);
    if (h.get('X-HQ') !== '1') return err(403, 'missing X-HQ header');
  }
  if (!PUBLIC.has(path) && !loggedIn) return err(401, 'not authenticated');

  const body = method === 'GET' ? {} : await readBody(init);
  let m: RegExpMatchArray | null;

  // auth
  if (path === '/api/health') {
    return json(200, { ok: true, worker_alive: true, worker_heartbeat_at: new Date().toISOString(), version: '0.1.0-mock' });
  }
  if (path === '/api/auth/status') return json(200, { configured: SS.get('hq-mock-setup') !== '1', loopback: true });
  if (path === '/api/auth/setup' && method === 'POST') {
    const pass = String(body.passcode ?? '');
    if (pass.length < 6) return err(400, 'Passcode must be at least 6 characters');
    SS.set('hq-mock-setup', null);
    SS.set('hq-mock-auth', null);
    return json(200, { ok: true });
  }
  if (path === '/api/auth/login' && method === 'POST') {
    const pass = String(body.passcode ?? '');
    if (pass === 'wrong' || pass.length < 6) return err(401, 'Wrong passcode');
    SS.set('hq-mock-auth', null);
    return json(200, { ok: true });
  }
  if (path === '/api/auth/logout' && method === 'POST') {
    SS.set('hq-mock-auth', 'out');
    return json(200, { ok: true });
  }
  if (path === '/api/auth/me')
    return loggedIn
      ? json(200, { ok: true, owner: { name: 'Prerit Sangwan', email: 'sangwanprerit40@gmail.com', linkedin: 'https://www.linkedin.com/in/prerit-sangwan-1b7572304', github: 'https://github.com/Preritsangwan17' } })
      : err(401, 'not authenticated');

  // data
  if (path === '/api/snapshot') return json(200, s.snapshot());
  if (path === '/api/stats') return json(200, s.stats());
  if (path === '/api/events') {
    let evs = s.events;
    const after = Number(q.get('after') ?? 0);
    const before = Number(q.get('before') ?? 0);
    if (after) evs = evs.filter((e) => e.id > after);
    if (before) evs = evs.filter((e) => e.id < before);
    if (q.get('agent')) evs = evs.filter((e) => e.agent_id === q.get('agent'));
    if (q.get('level')) evs = evs.filter((e) => e.level === q.get('level'));
    if (q.get('type')) evs = evs.filter((e) => e.type === q.get('type') || e.type.startsWith(`${q.get('type')}.`));
    if (q.get('q')) {
      const needle = q.get('q')!.toLowerCase();
      evs = evs.filter((e) => e.message.toLowerCase().includes(needle));
    }
    const limit = Math.min(500, Number(q.get('limit') ?? 200) || 200);
    return json(200, { events: after ? evs.slice(0, limit) : evs.slice(-limit) });
  }
  if (path === '/api/opportunities') {
    let items = [...s.opps.values()];
    if (q.get('stage')) items = items.filter((o) => o.stage === q.get('stage'));
    if (q.get('sim')) items = items.filter((o) => o.is_simulated === (q.get('sim') === '1'));
    if (q.get('q')) {
      const needle = q.get('q')!.toLowerCase();
      items = items.filter((o) => `${o.company_name} ${o.title} ${o.city}`.toLowerCase().includes(needle));
    }
    items.sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
    return json(200, { items: items.slice(0, Number(q.get('limit') ?? 500) || 500) });
  }
  if ((m = path.match(/^\/api\/opportunities\/([^/]+)\/stage$/)) && method === 'PATCH') {
    const o = s.overrideStage(decodeURIComponent(m[1]), body.stage as Stage, String(body.reason ?? ''));
    return o ? json(200, o) : err(404, 'opportunity not found');
  }
  if ((m = path.match(/^\/api\/opportunities\/([^/]+)$/))) {
    const d = s.detail(decodeURIComponent(m[1]));
    return d ? json(200, d) : err(404, 'opportunity not found');
  }

  // agents
  if (path === '/api/agents/meta') {
    return json(200, {
      capabilities: CAPABILITY_VOCAB.map((id) => ({
        id,
        group: id.split('.')[0],
        side_effect: RESERVED_SIDE_EFFECTS.includes(id),
      })),
      adapters: ['sim', 'script', 'openai_compatible', 'claude_code', 'http', 'browser'],
      reserved_side_effects: RESERVED_SIDE_EFFECTS,
      palette: [...AGENT_PALETTE],
    });
  }
  if (path === '/api/agents' && method === 'GET') {
    return json(200, { agents: s.snapshot().agents });
  }
  if (path === '/api/agents' && method === 'POST') {
    const cfg = body as unknown as AgentConfig;
    if (!cfg.id || !/^[a-z][a-z0-9_-]{1,31}$/.test(cfg.id)) return err(422, 'invalid agent id');
    if (s.agents.has(cfg.id)) return err(409, 'agent id already exists');
    if ((cfg.capabilities ?? []).some((c) => RESERVED_SIDE_EFFECTS.includes(c))) {
      return err(422, 'side-effect capabilities are reserved for built-in agents');
    }
    return json(200, s.createAgent({ ...cfg, adapter_config: cfg.adapter_config ?? {}, enabled: cfg.enabled ?? true, concurrency: cfg.concurrency ?? 1 }));
  }
  if ((m = path.match(/^\/api\/agents\/([^/]+)$/))) {
    const id = decodeURIComponent(m[1]);
    const a = s.agents.get(id);
    if (!a) return err(404, 'agent not found');
    if (method === 'PATCH') return json(200, s.patchAgent(id, body as AgentPatch));
    if (method === 'DELETE') {
      if (a.builtin) return err(400, "Built-in agents can't be deleted, only disabled");
      s.deleteAgent(id);
      return json(200, { ok: true });
    }
  }

  // control / settings / needs
  if (path === '/api/control/pause-all' && method === 'POST') {
    s.pauseAll((body.reason as string) ?? null);
    return json(200, { paused: true });
  }
  if (path === '/api/control/resume-all' && method === 'POST') {
    if (body.confirm !== 'RESUME') return err(400, 'confirm must be "RESUME"');
    s.resumeAll();
    return json(200, { paused: false });
  }
  if (path === '/api/control/freeze-outbound' && method === 'POST') {
    s.freeze(!!body.on);
    return json(200, { freeze_outbound: !!body.on });
  }
  if (path === '/api/settings' && method === 'GET') return json(200, { settings: s.settings });
  if (path === '/api/settings' && method === 'PATCH') return json(200, { settings: s.patchSettings(body) });
  if (path === '/api/needs' && method === 'GET') {
    const status = q.get('status');
    const items = [...s.needs.values()].filter((n) => !status || n.status === status);
    return json(200, { items: items.sort((a, b) => b.priority - a.priority) });
  }
  if ((m = path.match(/^\/api\/needs\/([^/]+)$/)) && method === 'PATCH') {
    const n = s.patchNeed(
      decodeURIComponent(m[1]),
      body.status as 'done' | 'snoozed' | 'dismissed',
      body.snooze_hours as number | undefined,
    );
    return n ? json(200, n) : err(404, 'need not found');
  }
  if (path === '/api/sim/reset' && method === 'POST') return json(200, { ok: true, purged: s.resetSim() });

  return err(404, `mock: no route for ${method} ${path}`);
}

/** EventSource look-alike fed by the simulator (named events, lastEventId, resync, onopen/onerror). */
class MockEventSource extends EventTarget {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSED = 2;
  readonly url: string;
  readonly withCredentials: boolean;
  readyState = 0;
  onopen: ((this: EventSource, ev: globalThis.Event) => unknown) | null = null;
  onmessage: ((this: EventSource, ev: MessageEvent) => unknown) | null = null;
  onerror: ((this: EventSource, ev: globalThis.Event) => unknown) | null = null;
  private unsub: (() => void) | null = null;

  constructor(url: string | URL, init?: EventSourceInit) {
    super();
    this.url = String(url);
    this.withCredentials = !!init?.withCredentials;
    setTimeout(() => this.connect(), 30);
  }

  private connect(): void {
    if (this.readyState === 2) return;
    if (SS.get('hq-mock-auth') === 'out') {
      this.readyState = 2;
      this.fire(new globalThis.Event('error'));
      return;
    }
    const s = getSimulator();
    this.readyState = 1;
    this.fire(new globalThis.Event('open'));
    const after = Number(new URL(this.url, window.location.origin).searchParams.get('after') ?? 0);
    if (after) {
      const replay = s.eventsAfter(after);
      if (replay === 'resync') this.deliver({ event: 'resync', data: {} });
      else for (const e of replay) this.deliver({ event: e.type, id: e.id, data: e });
    }
    this.unsub = s.subscribe((m) => this.deliver(m));
  }

  private deliver(m: SimMessage): void {
    if (this.readyState !== 1) return;
    const ev = new MessageEvent(m.event, {
      data: JSON.stringify(m.data),
      lastEventId: m.id != null ? String(m.id) : '',
    });
    this.fire(ev);
  }

  private fire(ev: globalThis.Event): void {
    this.dispatchEvent(ev);
    const self = this as unknown as EventSource;
    if (ev.type === 'open') this.onopen?.call(self, ev);
    else if (ev.type === 'error') this.onerror?.call(self, ev);
    else if (ev.type === 'message') this.onmessage?.call(self, ev as MessageEvent);
  }

  close(): void {
    this.readyState = 2;
    this.unsub?.();
    this.unsub = null;
  }
}

/** Install fetch + EventSource interceptors. Call before rendering the app. */
export function installMock(): void {
  readSwitches();
  const s = getSimulator();
  const q = new URLSearchParams(window.location.search);
  const speed = Number(q.get('mock_speed'));
  if (speed) s.patchSettings({ sim_speed: speed });
  if (q.get('mock_paused') === '1') s.pauseAll('Mock: started paused');

  const realFetch = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, window.location.origin);
    if (url.origin !== window.location.origin || !url.pathname.startsWith('/api/')) return realFetch(input, init);
    await new Promise((r) => setTimeout(r, 40 + Math.random() * 120));
    if (init?.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    return handle(url, init);
  };
  window.EventSource = MockEventSource as unknown as typeof EventSource;
  console.info('%c[Agent HQ] mock mode — in-browser simulator, no backend', 'color:#22D3EE');
}
