/**
 * Typed REST client for the Agent HQ API (CONTRACT §2–§3).
 * - Same-origin fetch with `credentials: 'include'` (session cookie `hq_session`).
 * - Mutations (POST/PATCH/PUT/DELETE) send `X-HQ: 1` (CSRF guard; the browser adds Origin).
 * - Errors are thrown as `ApiError` carrying the backend's `{error, detail}` JSON.
 * - A 401 on a protected route redirects to /login (override with `setUnauthorizedHandler`).
 * In mock mode (VITE_MOCK=1) `window.fetch` is patched by src/lib/mock, so this module is unchanged.
 */
import type {
  Agent,
  AgentConfig,
  AgentPatch,
  AgentValidation,
  AgentsMeta,
  ApiErrorBody,
  AuditEntry,
  AuthStatus,
  BudgetState,
  EventsQuery,
  HQEvent,
  Model,
  ModelsResponse,
  RoleAssignment,
  Health,
  Need,
  NeedStatus,
  OppDetail,
  OppQuery,
  OppSummary,
  Profile,
  ProfileFact,
  ProfileField,
  SecurityInfo,
  StrategyReport,
  Settings,
  Snapshot,
  Stage,
  Stats,
} from './types';

const BASE: string = import.meta.env.VITE_API_BASE ?? '';

export class ApiError extends Error {
  readonly status: number;
  readonly body: ApiErrorBody | null;
  constructor(status: number, body: ApiErrorBody | null, fallback: string) {
    super(body?.error || fallback);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
  get detail(): unknown {
    return this.body?.detail;
  }
}

type UnauthorizedHandler = (path: string) => void;

let onUnauthorized: UnauthorizedHandler = () => {
  const here = window.location.pathname + window.location.search;
  if (window.location.pathname.startsWith('/login')) return;
  window.location.assign(`/login?next=${encodeURIComponent(here)}`);
};

/** Let the router own navigation on 401 (called once by the app shell). */
export function setUnauthorizedHandler(fn: UnauthorizedHandler): void {
  onUnauthorized = fn;
}

export type Query = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  body?: unknown;
  query?: Query;
  signal?: AbortSignal;
  /** Don't redirect on 401 (auth endpoints, background polling). */
  noAuthRedirect?: boolean;
}

function buildUrl(path: string, query?: Query): string {
  let url = BASE + path;
  if (query) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null || v === '') continue;
      qs.set(k, String(v));
    }
    const s = qs.toString();
    if (s) url += (url.includes('?') ? '&' : '?') + s;
  }
  return url;
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? 'GET';
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (method !== 'GET') headers['X-HQ'] = '1';
  let body: string | undefined;
  if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.body);
  }

  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), {
      method,
      headers,
      body,
      credentials: 'include',
      signal: opts.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    throw new ApiError(0, { error: 'Network error — is the HQ server running?', detail: String(err) }, 'Network error');
  }

  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (!res.ok) {
    const errBody: ApiErrorBody | null =
      data && typeof data === 'object' && 'error' in (data as object)
        ? (data as ApiErrorBody)
        : { error: text?.slice(0, 200) || res.statusText || `HTTP ${res.status}` };
    if (res.status === 401 && !opts.noAuthRedirect) onUnauthorized(path);
    throw new ApiError(res.status, errBody, `HTTP ${res.status}`);
  }
  return data as T;
}

export const http = {
  get: <T>(path: string, query?: Query, opts?: Omit<RequestOptions, 'method' | 'query'>) =>
    request<T>(path, { ...opts, method: 'GET', query }),
  post: <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...opts, method: 'POST', body: body ?? {} }),
  patch: <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...opts, method: 'PATCH', body: body ?? {} }),
  del: <T>(path: string, opts?: Omit<RequestOptions, 'method'>) => request<T>(path, { ...opts, method: 'DELETE' }),
};

const enc = encodeURIComponent;

/** One function per endpoint in CONTRACT §3. */
export const api = {
  health: () => http.get<Health>('/api/health', undefined, { noAuthRedirect: true }),
  snapshot: () => http.get<Snapshot>('/api/snapshot'),
  events: (q: EventsQuery = {}) => http.get<{ events: HQEvent[] }>('/api/events', { ...q }),

  opportunities: (q: OppQuery = {}) => http.get<{ items: OppSummary[] }>('/api/opportunities', { ...q }),
  opportunity: (id: string) => http.get<OppDetail>(`/api/opportunities/${enc(id)}`),
  setStage: (id: string, stage: Stage, reason: string) =>
    http.patch<OppSummary>(`/api/opportunities/${enc(id)}/stage`, { stage, reason }),

  agents: () => http.get<{ agents: Agent[] }>('/api/agents'),
  agentsMeta: () => http.get<AgentsMeta>('/api/agents/meta'),
  createAgent: (cfg: AgentConfig) => http.post<Agent>('/api/agents', cfg),
  validateAgent: (cfg: AgentConfig) => http.post<AgentValidation>('/api/agents/validate', cfg),
  patchAgent: (id: string, patch: AgentPatch) => http.patch<Agent>(`/api/agents/${enc(id)}`, patch),
  deleteAgent: (id: string) => http.del<{ ok: boolean }>(`/api/agents/${enc(id)}`),

  pauseAll: (reason?: string) => http.post<{ paused: true }>('/api/control/pause-all', { reason }),
  resumeAll: () => http.post<{ paused: false }>('/api/control/resume-all', { confirm: 'RESUME' }),
  freezeOutbound: (on: boolean) => http.post<{ freeze_outbound: boolean }>('/api/control/freeze-outbound', { on }),

  settings: () => http.get<{ settings: Settings }>('/api/settings'),
  patchSettings: (patch: Partial<Settings>) => http.patch<{ settings: Settings }>('/api/settings', patch),

  needs: (status: NeedStatus | 'all' = 'open') =>
    http.get<{ items: Need[] }>('/api/needs', status === 'all' ? undefined : { status }),
  patchNeed: (id: string, body: { status: 'done' | 'snoozed' | 'dismissed'; snooze_hours?: number }) =>
    http.patch<Need>(`/api/needs/${enc(id)}`, body),

  stats: () => http.get<Stats>('/api/stats'),

  profile: () => http.get<Profile>('/api/profile'),
  patchProfileField: (key: string, value: unknown, share_policy?: string) =>
    http.patch<ProfileField>(`/api/profile/fields/${enc(key)}`, { value, share_policy }),
  patchFact: (id: string, status: ProfileFact['status']) => http.patch<ProfileFact>(`/api/profile/facts/${enc(id)}`, { status }),
  security: () => http.get<SecurityInfo>('/api/security'),
  audit: (q: { limit?: number; action?: string } = {}) => http.get<{ items: AuditEntry[] }>('/api/audit', { ...q }),
  strategyLatest: () => http.get<{ report: StrategyReport | null; next_run_at: string }>('/api/strategy/latest'),
  models: () => http.get<ModelsResponse>('/api/models'),
  rescanModels: () => http.post<{ queued: boolean }>('/api/models/rescan'),
  benchmark: (suite: 'quick' | 'full', model_id?: string) =>
    http.post<{ queued: boolean }>('/api/models/benchmark', { suite, model_id }),
  setRole: (role: string, model_id: string) => http.patch<{ roles: RoleAssignment[] }>('/api/roles', { role, model_id }),
  resetRole: (role: string) => http.patch<{ roles: RoleAssignment[] }>('/api/roles', { role, reset: true }),
  pinModel: (id: string, pinned: boolean) => http.post<Model>(`/api/models/${id}/pin`, { pinned }),
  unloadModel: (id: string) => http.post<{ ok: boolean }>(`/api/models/${id}/unload`),
  budget: () => http.get<BudgetState>('/api/budget'),
  recheckClaude: () => http.post<{ queued: boolean }>('/api/claude/recheck'),
  changePasscode: (current: string, next: string) =>
    http.post<{ ok: boolean }>('/api/auth/change-passcode', { current, new: next }),
  simReset: () => http.post<{ ok?: boolean; purged?: number }>('/api/sim/reset'),

  auth: {
    status: () => http.get<AuthStatus>('/api/auth/status', undefined, { noAuthRedirect: true }),
    me: () => http.get<{ ok: boolean }>('/api/auth/me', undefined, { noAuthRedirect: true }),
    login: (passcode: string) => http.post<{ ok: boolean }>('/api/auth/login', { passcode }, { noAuthRedirect: true }),
    setup: (passcode: string) => http.post<{ ok: boolean }>('/api/auth/setup', { passcode }, { noAuthRedirect: true }),
    logout: () => http.post<{ ok: boolean }>('/api/auth/logout', {}, { noAuthRedirect: true }),
  },
};

export type Api = typeof api;
