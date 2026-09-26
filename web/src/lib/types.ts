/**
 * Wire types mirroring docs/CONTRACT.md §3–§5 exactly (field names are the API's snake_case).
 * Enumerations come from the contract and hq/db/migrations/0001_init.sql. Where the backend may add values later,
 * unions are widened with `(string & {})` so unknown values still type-check without losing autocomplete.
 */

/** ISO-8601 UTC timestamp, e.g. "2026-09-26T13:45:00Z". Display in Asia/Kolkata. */
export type ISODate = string;
type Open<T extends string> = T | (string & {});

// ── agents ────────────────────────────────────────────────────────────
export type AgentStatus = 'idle' | 'working' | 'paused' | 'error' | 'stuck' | 'offline' | 'disabled';
export type CostTier = 'local' | 'claude' | 'external';
export type AdapterKind = Open<'sim' | 'script' | 'openai_compatible' | 'claude_code' | 'http' | 'browser'>;
export type ScheduleMode = 'on_demand' | 'interval' | 'cron';

export interface AgentSchedule {
  mode: ScheduleMode;
  minutes?: number;
  cron?: string;
}

export interface AgentLive {
  agent_id: string;
  now_line: string | null;
  /** 0..1 */
  progress: number | null;
  current_task_id: string | null;
  opportunity_id: string | null;
  model_id: string | null;
  tok_s: number | null;
  heartbeat_at: ISODate | null;
  updated_at: ISODate;
}

export interface Agent {
  id: string;
  name: string;
  /** single emoji or lucide icon name */
  avatar: string;
  color: string;
  role: string;
  adapter: AdapterKind;
  model: string | null;
  capabilities: string[];
  cost_tier: CostTier;
  concurrency: number;
  schedule: AgentSchedule;
  enabled: boolean;
  paused: boolean;
  status: AgentStatus;
  builtin: boolean;
  side_effects: string[];
  tasks_today: number;
  errors_today: number;
  tokens_today: number;
  restarts: number;
  last_error: string | null;
  live: AgentLive | null;
  description: string;
  /** outputs still needing Prerit's approval (wizard-created agents start at 5) */
  probation_runs_left?: number;
}

/** Body of POST /api/agents (AgentConfig without side-effect caps). */
export interface AgentConfig {
  id: string;
  name: string;
  avatar: string;
  color: string;
  role: string;
  description: string;
  adapter: AdapterKind;
  adapter_config: Record<string, unknown>;
  model: string | null;
  capabilities: string[];
  cost_tier: CostTier;
  concurrency: number;
  schedule: AgentSchedule;
  enabled: boolean;
}

/** PATCH /api/agents/{id} */
export interface AgentPatch {
  paused?: boolean;
  enabled?: boolean;
  model?: string | null;
  concurrency?: number;
  schedule?: AgentSchedule;
  name?: string;
  avatar?: string;
  color?: string;
}

/** Entry of GET /api/agents/meta `capabilities` (shape owned by backend; only `id` is guaranteed). */
export interface Capability {
  id: string;
  label?: string;
  group?: string;
  description?: string;
  side_effect?: boolean;
  phase_a?: boolean;
  [k: string]: unknown;
}

export interface AgentsMeta {
  capabilities: Capability[];
  adapters: string[];
  reserved_side_effects: string[];
  palette: string[];
}

// ── events ────────────────────────────────────────────────────────────
export type EventLevel = 'debug' | 'info' | 'warn' | 'error' | 'alert';

export type EventType =
  | 'agent.status'
  | 'agent.added'
  | 'agent.updated'
  | 'agent.removed'
  | 'task.created'
  | 'task.leased'
  | 'task.succeeded'
  | 'task.failed'
  | 'task.retry'
  | 'task.dead'
  | 'task.escalated'
  | 'task.handoff'
  | 'opp.created'
  | 'opp.stage'
  | 'opp.updated'
  | 'control.pause'
  | 'control.freeze'
  | 'settings.updated'
  | 'needs.created'
  | 'needs.updated'
  | 'notification'
  | 'mail.mock_sent'
  | 'worker.heartbeat'
  | 'worker.started'
  | 'worker.stopped'
  | 'log';

/** All event types the SSE stream can carry (persisted ones) — used to register EventSource listeners. */
export const EVENT_TYPES: readonly EventType[] = [
  'agent.status', 'agent.added', 'agent.updated', 'agent.removed',
  'task.created', 'task.leased', 'task.succeeded', 'task.failed', 'task.retry', 'task.dead', 'task.escalated',
  'task.handoff', 'opp.created', 'opp.stage', 'opp.updated', 'control.pause', 'control.freeze', 'settings.updated',
  'needs.created', 'needs.updated', 'notification', 'mail.mock_sent', 'worker.heartbeat', 'worker.started',
  'worker.stopped', 'log',
];

export interface TaskEventData {
  task_id: string;
  capability: string;
  agent_id?: string;
  attempt?: number;
}

export interface HandoffData {
  from_agent: string;
  to_agent: string;
  capability: string;
  opportunity_id: string | null;
}

/** Type-specific `data` payloads (CONTRACT §4). */
export interface EventDataMap {
  'agent.status': { status: AgentStatus };
  'agent.added': { agent: Agent };
  'agent.updated': { agent: Agent };
  'agent.removed': { agent: Agent };
  'task.created': TaskEventData;
  'task.leased': TaskEventData;
  'task.succeeded': TaskEventData;
  'task.failed': TaskEventData;
  'task.retry': TaskEventData;
  'task.dead': TaskEventData;
  'task.escalated': TaskEventData;
  'task.handoff': HandoffData;
  'opp.created': { opp: OppSummary };
  'opp.stage': { opp: OppSummary; from: Stage; to: Stage };
  'opp.updated': { opp: OppSummary };
  'control.pause': { paused: boolean; reason: string | null };
  'control.freeze': { freeze_outbound: boolean };
  'settings.updated': { settings: Settings };
  'needs.created': { need: Need };
  'needs.updated': { need: Need };
  notification: { severity: string; title: string; body: string | null; url: string | null };
  'mail.mock_sent': { to: string; subject: string; application_id: string | null };
  'worker.heartbeat': Record<string, unknown>;
  'worker.started': Record<string, unknown>;
  'worker.stopped': Record<string, unknown>;
  log: Record<string, unknown>;
}

/** `any` default mirrors the contract's `data: any`; narrow with `isEvent(e, 'opp.stage')`. */
export interface HQEvent<D = any> {
  id: number;
  ts: ISODate;
  type: Open<EventType>;
  level: EventLevel;
  agent_id: string | null;
  opportunity_id: string | null;
  task_id: string | null;
  message: string;
  data: D;
}
/** Contract name. Prefer `HQEvent` in components to avoid shadowing the DOM `Event`. */
export type Event<D = unknown> = HQEvent<D>;

export function isEvent<K extends EventType>(e: HQEvent, type: K): e is HQEvent<EventDataMap[K]> {
  return e.type === type;
}

// ── pay ───────────────────────────────────────────────────────────────
export type PayStatus = 'listed' | 'unknown' | 'variable' | 'unpaid' | 'fee_required';
export type PayPeriod = 'hour' | 'day' | 'week' | 'month' | 'year' | 'lump' | 'unknown';
export type LivingCostConfidence = 'high' | 'medium' | 'low' | 'provisional';

export interface PayBenefits {
  housing?: boolean;
  meals?: boolean;
  travel?: boolean;
  allowance_inr?: number;
}

export interface Pay {
  raw: string | null;
  status: PayStatus;
  min: number | null;
  max: number | null;
  currency: string | null;
  period: Open<PayPeriod> | null;
  monthly_inr_min: number | null;
  monthly_inr_mid: number | null;
  monthly_inr_max: number | null;
  hourly_inr_min: number | null;
  hourly_inr_max: number | null;
  fx_rate: number | null;
  fx_date: string | null;
  living_cost_monthly_inr: number | null;
  living_cost_basis: string | null;
  living_cost_confidence: LivingCostConfidence | null;
  /** monthly_inr_min / living_cost_monthly_inr, null if either unknown */
  ratio: number | null;
  benefits: PayBenefits;
}

// ── opportunities ─────────────────────────────────────────────────────
export type Stage =
  | 'found'
  | 'verified'
  | 'drafted'
  | 'checked'
  | 'applied'
  | 'replied'
  | 'interview'
  | 'offer'
  | 'rejected'
  | 'filtered'
  | 'frozen'
  | 'skipped';

export type OppKind = Open<
  'internship' | 'job' | 'part_time' | 'contract' | 'freelance' | 'fellowship' | 'program' | 'research_internship'
>;
export type RoleType = Open<'ml' | 'data' | 'software' | 'research' | 'other'>;
export type WorkMode = 'remote' | 'onsite' | 'hybrid' | 'unknown';
export type ApplyChannel = Open<'email' | 'ats_form' | 'portal' | 'manual'>;
export type EligibilityStatus = Open<'unknown' | 'eligible' | 'eligible_gaps' | 'ineligible' | 'needs_info' | 'borderline'>;
export type ScamStatus = Open<'unchecked' | 'clean' | 'suspicious' | 'scam'>;
export type DeadlineConfidence = Open<'high' | 'medium' | 'low' | 'rolling'>;

export interface OppSummary {
  id: string;
  company_name: string;
  title: string;
  kind: OppKind;
  role_type: RoleType | null;
  city: string | null;
  country_iso2: string | null;
  lat: number | null;
  lon: number | null;
  work_mode: WorkMode | null;
  stage: Stage;
  stage_reason: string | null;
  is_simulated: boolean;
  fit_score: number | null;
  eligibility_status: EligibilityStatus;
  scam_status: ScamStatus;
  deadline_at: ISODate | null;
  deadline_confidence: DeadlineConfidence | null;
  pay: Pay;
  url: string | null;
  apply_channel: ApplyChannel;
  source_label: string | null;
  active_agent_id: string | null;
  needs_prerit: boolean;
  updated_at: ISODate;
  first_seen_at: ISODate;
}

export type ApplicationStatus = Open<
  | 'drafting'
  | 'checking'
  | 'awaiting_approval'
  | 'queued'
  | 'submitted'
  | 'needs_prerit'
  | 'failed'
  | 'withdrawn'
  | 'historical_frozen'
  | 'skipped'
>;
export type RunMode = 'dry_run' | 'self_test' | 'live';

export interface Application {
  id: string;
  channel: ApplyChannel;
  status: ApplicationStatus;
  mode: RunMode;
  submitted_at: ISODate | null;
  created_at: ISODate;
}

export type DocumentKind = Open<
  | 'cover_letter'
  | 'cold_email'
  | 'research_statement'
  | 'profile_summary'
  | 'form_answers'
  | 'resume_html'
  | 'resume_pdf'
  | 'compact_pdf'
  | 'followup'
  | 'reply'
>;
export type DocumentStatus = Open<'draft' | 'checking' | 'passed' | 'failed' | 'sent' | 'historical'>;

export interface Document {
  id: string;
  kind: DocumentKind;
  version: number;
  status: DocumentStatus;
  author_agent: string | null;
  author_model: string | null;
  content_text: string | null;
  created_at: ISODate;
  file_url: string | null;
}

export interface OppDetail extends OppSummary {
  summary: string | null;
  notes_unverified: string | null;
  applications: Application[];
  documents: Document[];
  timeline: HQEvent[];
  gates: unknown[];
  eligibility_checks: unknown[];
  needs: Need[];
}

// ── needs prerit ──────────────────────────────────────────────────────
export type NeedKind = Open<
  | 'submit_form'
  | 'approve'
  | 'missing_info'
  | 'review_letter'
  | 'decision'
  | 'captcha'
  | 'login'
  | 'interview'
  | 'offer'
  | 'assessment'
  | 'legal'
  | 'money'
  | 'confirm_legacy'
>;
export type NeedStatus = 'open' | 'done' | 'snoozed' | 'dismissed';

export interface NeedAnswer {
  label: string;
  value: string;
  copy?: boolean;
}

export interface Need {
  id: string;
  opportunity_id: string | null;
  kind: NeedKind;
  title: string;
  instructions_md: string | null;
  answers: NeedAnswer[];
  files: { name: string; path: string }[];
  direct_url: string | null;
  /** 0..100, higher = more urgent (default 50) */
  priority: number;
  due_at: ISODate | null;
  est_minutes: number | null;
  status: NeedStatus;
  created_at: ISODate;
  /** structured extras (probation task id, decision options …) */
  payload?: Record<string, unknown>;
}

// ── stats / settings / snapshot ───────────────────────────────────────
export interface PayStats {
  pipeline_median_inr: number | null;
  pipeline_max_inr: number | null;
  best_offer_inr: number | null;
  median_applied_inr: number | null;
}

export interface Stats {
  found: number;
  verified: number;
  drafted: number;
  applied: number;
  replies: number;
  interviews: number;
  offers: number;
  rejected: number;
  filtered: number;
  success_rate: number | null;
  needs_open: number;
  claude_cost_today_usd: number;
  claude_budget_usd: number;
  claude_calls_today: number;
  local_tokens_today: number;
  pay: PayStats;
  by_stage: Record<string, number>;
  sim: boolean;
}

export type Mode = 'dry_run' | 'self_test' | 'live';
export type Autonomy = 'auto' | 'approve_first';

export interface QuietHours {
  enabled: boolean;
  start: string;
  end: string;
}

/** Known settings keys (CONTRACT §3) plus anything else the backend adds. */
export interface Settings {
  global_pause: boolean;
  freeze_outbound: boolean;
  mode: Mode;
  autonomy: Autonomy;
  sim_enabled: boolean;
  sim_speed: number;
  keep_awake: boolean;
  eligibility_threshold: number;
  min_pay_ratio: number;
  funded_program_min_inr: number;
  fit_draft_threshold: number;
  fit_polish_threshold: number;
  daily_draft_cap: number;
  claude_daily_budget_usd: number;
  claude_daily_call_cap: number;
  email_daily_cap: number;
  quiet_hours: QuietHours;
  unknown_pay_policy: Open<'decision' | 'reject' | 'accept'>;
  [key: string]: unknown;
}

export interface Snapshot {
  settings: Settings;
  agents: Agent[];
  opportunities: OppSummary[];
  /** last 200, oldest first */
  events: HQEvent[];
  stats: Stats;
  needs: Need[];
  server_time: ISODate;
  last_event_id: number;
}

// ── misc endpoints ────────────────────────────────────────────────────
export interface Health {
  ok: boolean;
  worker_alive: boolean;
  worker_heartbeat_at: ISODate | null;
  version: string;
}

export interface AuthStatus {
  configured: boolean;
  /** optional hint from backend: request came from loopback (setup allowed) */
  loopback?: boolean;
}

export interface ApiErrorBody {
  error: string;
  detail?: unknown;
}

export interface EventsQuery {
  after?: number;
  before?: number;
  limit?: number;
  agent?: string;
  level?: EventLevel;
  type?: string;
  q?: string;
}

export interface OppQuery {
  stage?: Stage;
  q?: string;
  sim?: 0 | 1;
  limit?: number;
}

// ── profile / security (Settings) ─────────────────────────────────────
export type SharePolicy = 'forms' | 'on_request' | 'never';

export interface AvailabilityWindow {
  from: string;
  to: string;
  hours_per_week: number;
  mode: 'remote' | 'onsite' | 'any';
}

export interface ProfileField {
  key: string;
  label: string;
  value: string | AvailabilityWindow[] | null;
  share_policy: SharePolicy;
  confirmed: boolean;
  required_for_live: boolean;
  updated_at: ISODate | null;
  kind: 'text' | 'number' | 'choice' | 'windows' | 'date';
  hint: string;
  choices: string[];
}

export interface ProfileFact {
  id: string;
  category: string;
  project: string | null;
  text: string;
  phrasings: string[];
  evidence_url: string | null;
  evidence: string | null;
  source: string;
  status: 'verified' | 'pending' | 'retired';
  note: string | null;
}

export interface Profile {
  facts: ProfileFact[];
  fields: ProfileField[];
  required_missing: string[];
}

export interface SecurityInfo {
  lan: boolean;
  allowed_hosts: string[];
  loopback: boolean;
  https: boolean;
  session_days: number;
  secrets_present: string[];
  force_dry_run: boolean;
}

export interface AuditEntry {
  id: string;
  ts: ISODate;
  actor: string;
  action: string;
  target: string | null;
  before: unknown;
  after: unknown;
  remote_addr: string | null;
}

// ── strategist ────────────────────────────────────────────────────────
export interface StrategyAction {
  type: string;
  params?: Record<string, unknown>;
  rationale?: string;
  risk?: 'low' | 'medium' | 'high' | (string & {});
  status?: string;
}

export interface StrategyReport {
  date: string;
  report_md: string | null;
  proposed_actions: StrategyAction[];
  applied_actions: StrategyAction[];
  created_at: ISODate;
}

/** POST /api/agents/validate — dry run for the Add Agent wizard. */
export interface AgentValidation {
  ok: boolean;
  errors: { field: string; message: string }[];
  yaml: string | null;
  probe: { ok: boolean; url: string; status?: number; error?: string; detail?: { models?: string[] } | null } | null;
}
