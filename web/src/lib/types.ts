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
  submission_ref?: string | null;
  doc_kind?: string | null;
  approved_at?: ISODate | null;
  message_id?: string | null;
  answers?: NeedAnswer[];
  reviewed_at?: ISODate | null;
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
  subject?: string | null;
  parent_id?: string | null;
  lineage?: string[];
}

export interface FactCheckVerdict {
  layer: string;
  verdict: string;
  checker_model: string | null;
  rules: string[];
  span: string | null;
  explanation: string | null;
}

export interface DocSentence {
  id: string | null;
  idx: number;
  text: string | null;
  kind: string | null;
  fact_ids: string[];
  job_quote_ids: string[];
  checks: FactCheckVerdict[];
}

export interface GateResult {
  id: string;
  application_id: string;
  document_id: string | null;
  gate: string;
  passed: boolean;
  details: Record<string, unknown>;
  ts: ISODate;
}

export interface EligibilityCheck {
  id: string;
  method: string;
  model_id: string | null;
  requirements: Record<string, unknown>;
  quotes: ({ quote: string; requirement?: string; met?: boolean | null } | string)[];
  verdict: string;
  confidence: number | null;
  created_at: ISODate;
}

export interface ScamCheck {
  verdict: string;
  signals: ({ id?: string; label?: string; detail?: string; weight?: number; quote?: string } | string)[];
  created_at: ISODate;
}

export interface OppRun {
  id: string;
  task_id: string | null;
  capability: string;
  agent_id: string;
  model_id: string | null;
  status: string;
  cost_usd: number | null;
  duration_ms: number | null;
  parent_run_id: string | null;
  escalated_from_run_id: string | null;
  error: string | null;
  started_at: ISODate;
}

export interface OppDetail extends OppSummary {
  summary: string | null;
  notes_unverified: string | null;
  applications: Application[];
  documents: Document[];
  timeline: HQEvent[];
  gates: GateResult[];
  eligibility_checks: EligibilityCheck[];
  needs: Need[];
  description_available?: boolean;
  location_raw?: string | null;
  apply_url?: string | null;
  automation?: string | null;
  posted_at?: ISODate | null;
  fit_breakdown?: Record<string, number>;
  benefits?: Record<string, unknown>;
  eligibility_confidence?: number | null;
  parse?: Record<string, unknown>;
  requirements?: Record<string, unknown>;
  job_quotes?: { id: string; text: string }[];
  scam_checks?: ScamCheck[];
  sources?: { source_id: string; source_name: string | null; external_id: string | null; source_url: string | null; first_seen: ISODate; last_seen: ISODate }[];
  runs?: OppRun[];
  document_sentences?: Record<string, DocSentence[]>;
}

export interface Source {
  id: string;
  name: string;
  kind: string;
  config: Record<string, unknown>;
  automation: string;
  tos_status: 'unreviewed' | 'allowed' | 'restricted' | 'prohibited';
  tos_url: string | null;
  tos_reviewed_at: ISODate | null;
  poll_interval_min: number;
  last_polled_at: ISODate | null;
  last_ok_at: ISODate | null;
  consecutive_errors: number;
  disabled_until: ISODate | null;
  enabled: boolean;
  added_by: string;
  opportunities: number;
}

export interface SourcesResponse {
  items: Source[];
  manual_lane: string[];
  mode: RunMode;
}

export interface FetchLogRow {
  id: number;
  ts: ISODate;
  method: string;
  url: string;
  domain: string;
  status: number | null;
  bytes: number | null;
  from_cache: number;
  source_id: string | null;
  blocked_reason: string | null;
  duration_ms: number | null;
}

export interface FetchLogResponse {
  items: FetchLogRow[];
  methods: Record<string, number>;
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
  /** filled | needs_prerit | never | file */
  status?: string;
  note?: string | null;
  required?: boolean;
}

export interface Need {
  id: string;
  opportunity_id: string | null;
  application_id?: string | null;
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
  notifications_unacked?: number;
}

// ── phase (d): inbox, notifications, Gmail, go-live ──────────────────
export interface InboxThread {
  id: string;
  gmail_thread_id: string | null;
  subject: string | null;
  counterpart: string | null;
  classification: string | null;
  locked: boolean;
  lock_reason: string | null;
  locked_at: ISODate | null;
  unlocked_at: ISODate | null;
  alert_ack_at: ISODate | null;
  last_message_at: ISODate | null;
  messages: number;
  inbound: number;
  drafts: number;
  last: { direction: string; from_addr: string | null; snippet: string | null; date: ISODate | null; classification: string | null } | null;
  opportunity: { id: string; company_name: string; title: string; stage: Stage; is_simulated: boolean } | null;
  simulated: boolean;
  gmail_url: string | null;
}

export interface InboxMessage {
  id: string;
  direction: 'inbound' | 'outbound';
  from_addr: string | null;
  to_addr: string | null;
  date: ISODate | null;
  subject: string | null;
  classification: string | null;
  confidence: number | null;
  reason: string | null;
  lock_terms: string[];
  body: string;
}

export interface ReplyDraft {
  id: string;
  status: string;
  subject: string | null;
  text: string | null;
  author: string | null;
  created_at: ISODate;
}

export interface InboxThreadDetail extends InboxThread {
  items: InboxMessage[];
  reply_drafts: ReplyDraft[];
}

export interface InboxList {
  items: InboxThread[];
  counts: { all: number; locked: number; alerts: number; drafts: number };
  unacked_alerts: string[];
}

export interface NotificationRow {
  id: string;
  severity: 'info' | 'warn' | 'alert';
  title: string;
  body: string | null;
  url: string | null;
  mac_delivered: number;
  acknowledged_at: ISODate | null;
  created_at: ISODate;
}

export interface GmailInfo {
  client_configured: boolean;
  connected: boolean;
  scopes: string[];
  send_scope: boolean;
  compose_scope: boolean;
  state: { connected?: boolean; healthy?: boolean; email?: string; error?: string | null; history_id?: string | null;
    last_poll_at?: ISODate; last_ok_at?: ISODate; checked_at?: ISODate; last_full_sync_at?: ISODate };
  oauth: { status: 'idle' | 'pending' | 'done' | 'error'; error: string | null; purpose: string | null; scopes: string[] };
  forced_dry_run: boolean;
  refusal: { reason: string; at: ISODate } | null;
}

export interface GoLiveItem {
  id: string;
  gate: boolean;
  label: string;
  ok: boolean;
  detail: string;
}

export interface GoLiveState {
  mode: RunMode;
  live_since: ISODate | null;
  items: GoLiveItem[];
  ready_for_send_scope: boolean;
  ready_for_env: boolean;
  ready_for_live: boolean;
  confirm_phrase: string;
  env_file_live: boolean;
  forced_dry_run: boolean;
  restart_required?: boolean;
  restart_command?: string;
}

// ── misc endpoints ────────────────────────────────────────────────────
export interface Health {
  ok: boolean;
  /** the worker refused to start for safety (send-capable Gmail grant while HQ_FORCE_DRY_RUN is on) */
  worker_refusal?: string | null;
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

// ── models / roles / budget (phase b) ─────────────────────────────────
export interface ModelScore {
  n?: number | null;
  accuracy?: number | null;
  precision?: number | null;
  recall?: number | null;
  f1?: number | null;
  json_valid_first?: number | null;
  json_valid_after_repair?: number | null;
  tok_s_gen?: number | null;
  tok_s_prompt?: number | null;
  ttft_ms?: number | null;
  peak_footprint_gb?: number | null;
}

export interface Model {
  id: string;
  runtime: 'mlx' | 'ollama' | 'lmstudio' | 'llamacpp' | (string & {});
  name: string;
  modality: string;
  complete: boolean;
  incomplete_reason: string | null;
  runtime_supported: boolean;
  size_gb: number | null;
  params_b: number | null;
  quant: string | null;
  ctx_len: number | null;
  est_ram_gb: number | null;
  measured_ram_gb: number | null;
  status: 'available' | 'loaded' | 'broken' | 'unsupported' | (string & {});
  pinned: boolean;
  model_type: string | null;
  roles: string[];
  ranked_in: Record<string, number>;
  scores: Record<string, ModelScore>;
  role_scores: Record<string, number>;
  last_benchmark_at: ISODate | null;
  note?: string | null;
}

export interface RoleAssignment {
  role: string;
  label: string;
  ranked: { model_id: string; score: number | null; source: 'auto' | 'override'; reason: string | null }[];
  needs_claude_signoff?: boolean;
}

export interface MemoryState {
  total_gb: number;
  available_gb: number;
  pool_used_gb: number;
  pool_budget_gb: number;
  pressure: 'normal' | 'warn' | 'critical';
  user_active: boolean;
  on_battery: boolean;
  usability_mode: boolean;
  usability_reason?: string | null;
  servers?: { model_id: string; port: number; pid: number; footprint_gb: number | null; need_gb: number; in_use: number }[];
  stale?: boolean;
}

export interface BenchState {
  running: boolean;
  model_id?: string;
  task?: string;
  progress?: number;
  eta_s?: number | null;
  finished_at?: ISODate;
  error?: string;
}

export type CloudProvider = 'claude' | 'xai' | 'codex';

/** One cloud provider's status as the worker last saw it (login / key checks — free, no model is called). */
export interface ProviderState {
  available: boolean;
  reason: string | null;
  checked: boolean;
  /** Settings › Models & Budget switch (`llm_<provider>_enabled`) when the worker last checked */
  enabled?: boolean;
  /** hit its usage limit; HQ makes no calls to it until the rest is over */
  resting?: boolean;
  logged_in?: boolean;
  installed?: boolean;
  version?: string | null;
  key_present?: boolean;
  models?: string[];
  model?: string | null;
  signoff_model?: string | null;
}

export interface ClaudeState {
  /** true when any switched-on cloud provider can take a call */
  available: boolean | null;
  logged_in: boolean;
  reason?: string | null;
  model?: string | null;
  signoff_model?: string | null;
  checked_at?: ISODate;
  /** preferred switched-on provider (null = every cloud model is off) */
  provider?: CloudProvider | null;
  /** first switched-on provider that is reachable now */
  using?: CloudProvider | null;
  providers?: Partial<Record<CloudProvider, ProviderState>>;
  local_enabled?: boolean;
}

export interface ModelsResponse {
  models: Model[];
  roles: RoleAssignment[];
  servers: { model_id: string; pid: number; port: number; started_at: ISODate; footprint_gb: number | null; status: string }[];
  memory: MemoryState;
  benchmark: BenchState;
  claude: ClaudeState;
  /** Settings › Models & Budget › Local models */
  local_enabled?: boolean;
}

export interface BudgetState {
  date_ist: string;
  spent_usd: number;
  reserved_usd: number;
  budget_usd: number;
  calls: number;
  call_cap: number;
  by_task: Record<string, { calls: number; spent_usd: number }>;
  deferred_tasks: number;
  claude_available: boolean | null;
  last_error: string | null;
  resets_at: ISODate;
  /** preferred switched-on cloud provider (`cloud_llm`; auto → xai when HQ_XAI_API_KEY is set, else claude, then codex) */
  provider?: CloudProvider | null;
  /** first switched-on provider that is reachable now */
  using?: CloudProvider | null;
  cloud_model?: string | null;
  cloud_reason?: string | null;
  claude?: ProviderState | null;
  xai?: ProviderState | null;
  codex?: ProviderState | null;
}
