/**
 * In-browser simulator mirroring the backend's phase-(a) sim (CONTRACT §7–§8): a task queue worked by the 10
 * agents, stage transitions found → verified → drafted → checked → applied → replied → interview/offer/rejected,
 * transient failures with retries, needs/alerts, pause/resume, and the exact event shapes of /api/stream.
 * Used only when VITE_MOCK=1.
 */
import { STAGE_META } from '@/theme/tokens';
import type {
  Agent,
  AgentConfig,
  AgentLive,
  AgentPatch,
  Application,
  Document,
  EventLevel,
  HQEvent,
  Need,
  NeedKind,
  OppDetail,
  OppSummary,
  Settings,
  Snapshot,
  Stage,
  Stats,
} from '../types';
import {
  LEGACY,
  NOW_LINES,
  POOL,
  TITLE_VARIANTS,
  agentTokS,
  buildAgents,
  buildPay,
  type LegacySeed,
  type PoolItem,
} from './data';

export interface SimMessage {
  event: string;
  id?: number;
  data: unknown;
}
type Listener = (m: SimMessage) => void;

interface SimTask {
  id: string;
  capability: string;
  oppId: string | null;
  attempts: number;
  notBefore: number;
  createdAt: number;
}

interface Job {
  task: SimTask;
  agentId: string;
  start: number;
  end: number;
  nextStepAt: number;
  stepMs: number;
  lines: string[];
  lineIdx: number;
  tokS: number | null;
  tokens: number;
}

type Outcome = 'interview' | 'rejected' | 'offer' | 'info';

interface OppMeta {
  pool: PoolItem;
  legacy: LegacySeed | null;
  reached: number;
  replyAt: number | null;
  draftLoops: number;
  draftVersion: number;
  appId: string | null;
  appAt: string | null;
}

const REACH: Record<Stage, number> = {
  found: 0, verified: 1, drafted: 2, checked: 3, applied: 4, replied: 5, interview: 6, offer: 7,
  rejected: 5, filtered: 0, frozen: 0, skipped: 0,
};
const TERMINAL = new Set<Stage>(['offer', 'rejected', 'filtered', 'frozen', 'skipped']);
const EVENTS_KEEP = 5000;

const rand = (a: number, b: number) => a + Math.random() * (b - a);
const randInt = (a: number, b: number) => Math.floor(rand(a, b + 1));
const pick = <T,>(xs: readonly T[]): T => xs[Math.floor(Math.random() * xs.length)];
const iso = (ms: number) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');

const CROCKFORD = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
export function ulid(t = Date.now()): string {
  let time = '';
  let x = Math.max(0, Math.floor(t));
  for (let i = 0; i < 10; i++) {
    time = CROCKFORD[x % 32] + time;
    x = Math.floor(x / 32);
  }
  let r = '';
  for (let i = 0; i < 16; i++) r += CROCKFORD[Math.floor(Math.random() * 32)];
  return time + r;
}

function fill(line: string, p: PoolItem | null): string {
  if (!p) return line.replace(/\{[a-z]+\}/g, '…');
  return line
    .replace(/\{company\}/g, p.company)
    .replace(/\{title\}/g, p.title)
    .replace(/\{city\}/g, p.city)
    .replace(/\{raw\}/g, p.pay.raw);
}

function domainOf(company: string): string {
  return `${company.toLowerCase().replace(/\(.*?\)/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}.example`;
}

export const DEFAULT_MOCK_SETTINGS: Settings = {
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
  claude_daily_budget_usd: 5,
  claude_daily_call_cap: 40,
  email_daily_cap: 10,
  quiet_hours: { enabled: false, start: '23:00', end: '07:00' },
  unknown_pay_policy: 'decision',
};

const SETTINGS_WHITELIST = new Set(Object.keys(DEFAULT_MOCK_SETTINGS).filter((k) => k !== 'global_pause'));

export class Simulator {
  settings: Settings = { ...DEFAULT_MOCK_SETTINGS };
  agents = new Map<string, Agent>();
  live = new Map<string, AgentLive>();
  opps = new Map<string, OppSummary>();
  meta = new Map<string, OppMeta>();
  needs = new Map<string, Need>();
  events: HQEvent[] = [];
  private nextEventId = 1;
  private queue: SimTask[] = [];
  private jobs = new Map<string, Job>();
  private listeners = new Set<Listener>();
  private timer: ReturnType<typeof setInterval> | undefined;
  private nextScoutAt = 0;
  private nextInboxAt = 0;
  private nextStrategistAt = 0;
  private nextHeartbeatAt = 0;
  private claudeCost = 0;
  private claudeCalls = 0;
  private localTokens = 0;

  constructor() {
    for (const a of buildAgents()) this.agents.set(a.id, a);
    this.seed();
  }

  // ── lifecycle / subscription ────────────────────────────────────────
  start(): void {
    if (this.timer) return;
    const now = Date.now();
    this.nextScoutAt = now + 6000;
    this.nextInboxAt = now + 15000;
    this.nextStrategistAt = now + 90000;
    this.nextHeartbeatAt = now + 2000;
    this.timer = setInterval(this.tick, 200);
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  }

  private broadcast(m: SimMessage): void {
    for (const fn of this.listeners) fn(m);
  }

  eventsAfter(after: number): HQEvent[] | 'resync' {
    if (!this.events.length) return [];
    const first = this.events[0].id;
    if (after < first - 1) return 'resync';
    const out = this.events.filter((e) => e.id > after);
    return out.length > 500 ? 'resync' : out;
  }

  // ── events ──────────────────────────────────────────────────────────
  private emit(
    type: string,
    level: EventLevel,
    message: string,
    extra: { agent_id?: string | null; opportunity_id?: string | null; task_id?: string | null; data?: unknown } = {},
    ts: number = Date.now(),
  ): HQEvent {
    const ev: HQEvent = {
      id: this.nextEventId++,
      ts: iso(ts),
      type,
      level,
      agent_id: extra.agent_id ?? null,
      opportunity_id: extra.opportunity_id ?? null,
      task_id: extra.task_id ?? null,
      message,
      data: extra.data ?? {},
    };
    this.events.push(ev);
    if (this.events.length > EVENTS_KEEP) this.events.splice(0, this.events.length - EVENTS_KEEP);
    this.broadcast({ event: type, id: ev.id, data: ev });
    return ev;
  }

  private emitLive(agentId: string): void {
    const l = this.live.get(agentId);
    if (l) this.broadcast({ event: 'agent.live', data: l });
  }

  private setAgent(id: string, patch: Partial<Agent>, announce: 'status' | 'updated' | false = false): Agent | null {
    const a = this.agents.get(id);
    if (!a) return null;
    const next = { ...a, ...patch };
    this.agents.set(id, next);
    if (announce === 'status' && patch.status && patch.status !== a.status) {
      this.emit('agent.status', 'debug', `${a.name} → ${patch.status}`, { agent_id: id, data: { status: patch.status } });
    } else if (announce === 'updated') {
      this.emit('agent.updated', 'info', `${a.name} updated`, { agent_id: id, data: { agent: this.agentOut(next) } });
    }
    return next;
  }

  private agentOut(a: Agent): Agent {
    return { ...a, live: this.live.get(a.id) ?? null };
  }

  // ── opportunities ───────────────────────────────────────────────────
  private label(o: OppSummary): string {
    return `${o.company_name} · ${o.title}`;
  }

  private createOpp(p: PoolItem, at: number, legacy: LegacySeed | null = null): OppSummary {
    const id = ulid(at);
    const variant = legacy ? '' : this.titleVariant(p);
    const deadline = p.deadlineDays == null ? null : iso(at + p.deadlineDays * 86400000 + randInt(0, 20) * 3600000);
    const opp: OppSummary = {
      id,
      company_name: p.company,
      title: p.title + variant,
      kind: p.kind,
      role_type: p.role_type,
      city: p.city,
      country_iso2: p.country,
      lat: p.lat,
      lon: p.lon,
      work_mode: p.work_mode,
      stage: legacy ? 'frozen' : 'found',
      stage_reason: legacy ? 'Imported from legacy shortlist — historical, not re-sent' : `Found via ${p.source}`,
      is_simulated: !legacy,
      fit_score: legacy ? p.fit : null,
      eligibility_status: legacy ? 'needs_info' : 'unknown',
      scam_status: legacy ? 'clean' : 'unchecked',
      deadline_at: deadline,
      deadline_confidence: p.deadlineDays == null ? 'rolling' : pick(['high', 'medium'] as const),
      pay: buildPay(p.pay, p.living),
      url: `https://${domainOf(p.company)}/careers/${p.key}`,
      apply_channel: p.channel,
      source_label: legacy ? 'legacy shortlist 2026-09-26' : p.source,
      active_agent_id: null,
      needs_prerit: false,
      updated_at: iso(at),
      first_seen_at: iso(at),
    };
    this.opps.set(id, opp);
    this.meta.set(id, {
      pool: p,
      legacy,
      reached: 0,
      replyAt: null,
      draftLoops: 0,
      draftVersion: 0,
      appId: legacy ? ulid(at) : null,
      appAt: legacy ? iso(at - 86400000 * 3) : null,
    });
    return opp;
  }

  private titleVariant(p: PoolItem): string {
    const used = new Set([...this.opps.values()].filter((o) => o.company_name === p.company).map((o) => o.title));
    for (const v of TITLE_VARIANTS) if (!used.has(p.title + v)) return v;
    return ` #${used.size + 1}`;
  }

  private updateOpp(id: string, patch: Partial<OppSummary>, at = Date.now()): OppSummary | null {
    const o = this.opps.get(id);
    if (!o) return null;
    const next = { ...o, ...patch, updated_at: iso(at) };
    this.opps.set(id, next);
    return next;
  }

  private setStage(id: string, stage: Stage, reason: string, at = Date.now(), agentId: string | null = null): void {
    const prev = this.opps.get(id);
    if (!prev) return;
    const m = this.meta.get(id)!;
    m.reached = Math.max(m.reached, REACH[stage]);
    const o = this.updateOpp(id, { stage, stage_reason: reason }, at)!;
    this.emit(
      'opp.stage',
      stage === 'filtered' || stage === 'rejected' ? 'info' : stage === 'interview' || stage === 'offer' ? 'alert' : 'info',
      `${this.label(o)} → ${STAGE_META[stage].label}${reason ? ` · ${reason}` : ''}`,
      { agent_id: agentId, opportunity_id: id, data: { opp: o, from: prev.stage, to: stage } },
      at,
    );
  }

  private oppUpdated(id: string, patch: Partial<OppSummary>, message: string, agentId: string | null = null, at = Date.now()) {
    const o = this.updateOpp(id, patch, at);
    if (o) this.emit('opp.updated', 'info', message, { agent_id: agentId, opportunity_id: id, data: { opp: o } }, at);
  }

  // ── needs ───────────────────────────────────────────────────────────
  private addNeed(n: Omit<Need, 'id' | 'status' | 'created_at' | 'files' | 'answers'> & Partial<Need>, at = Date.now()) {
    const need: Need = {
      id: ulid(at),
      status: 'open',
      created_at: iso(at),
      files: [],
      answers: [],
      ...n,
    };
    this.needs.set(need.id, need);
    this.emit('needs.created', need.kind === 'interview' || need.kind === 'offer' ? 'alert' : 'info', `Needs Prerit: ${need.title}`, {
      opportunity_id: need.opportunity_id,
      data: { need },
    }, at);
    if (need.opportunity_id && this.opps.get(need.opportunity_id)?.needs_prerit === false) {
      this.oppUpdated(need.opportunity_id, { needs_prerit: true }, `Needs you: ${need.title}`, null, at);
    }
    return need;
  }

  patchNeed(id: string, status: 'done' | 'snoozed' | 'dismissed', snoozeHours?: number): Need | null {
    const n = this.needs.get(id);
    if (!n) return null;
    const next: Need = {
      ...n,
      status,
      due_at: status === 'snoozed' ? iso(Date.now() + (snoozeHours ?? 4) * 3600000) : n.due_at,
    };
    this.needs.set(id, next);
    this.emit('needs.updated', 'info', `Need ${status}: ${n.title}`, { opportunity_id: n.opportunity_id, data: { need: next } });
    if (n.opportunity_id) {
      const stillOpen = [...this.needs.values()].some((x) => x.opportunity_id === n.opportunity_id && x.status === 'open');
      if (!stillOpen) this.oppUpdated(n.opportunity_id, { needs_prerit: false }, 'No open items for this opportunity');
    }
    return next;
  }

  // ── seeding (history before "now") ──────────────────────────────────
  private seed(): void {
    const now = Date.now();
    const actions: { t: number; fn: () => void }[] = [];
    const at = (t: number, fn: () => void) => actions.push({ t, fn });

    // Legacy frozen items, imported ~2h ago.
    const importAt = now - 2 * 3600000 - 12 * 60000;
    at(importAt, () => {
      this.emit('worker.started', 'info', 'Worker started (sim adapter, dry run)', {}, importAt - 60000);
      for (const l of LEGACY) {
        const o = this.createOpp(l, importAt, l);
        this.emit('opp.created', 'info', `Imported legacy: ${this.label(o)} (historical, frozen)`, {
          opportunity_id: o.id,
          data: { opp: o },
        }, importAt);
      }
      this.addNeed({
        opportunity_id: null,
        kind: 'confirm_legacy',
        title: `Which of these ${LEGACY.length} legacy applications did you actually send?`,
        instructions_md:
          'The old session left letters for these roles but no record of sending. Tick the ones you sent so ' +
          'follow-ups stay correct; the rest stay frozen until a fresh gated draft.',
        answers: LEGACY.map((l) => ({ label: l.company, value: l.title })),
        direct_url: null,
        priority: 70,
        due_at: null,
        est_minutes: 1,
      }, importAt + 1000);
    });

    const plan: [string, Stage][] = [
      ['lumina', 'applied'], ['kestrel', 'replied'], ['vanta', 'checked'], ['northwind', 'verified'],
      ['helix', 'drafted'], ['alpenglow', 'applied'], ['rheinwerk', 'filtered'], ['isar', 'found'],
      ['formosa', 'interview'], ['tatami', 'drafted'], ['merlion', 'verified'], ['thames', 'offer'],
      ['oasis', 'rejected'], ['canal', 'applied'], ['sahyadri', 'verified'], ['bluefin', 'verified'],
      ['ganga', 'drafted'], ['pixelwise', 'found'], ['jade', 'checked'], ['certify', 'filtered'],
      ['orion', 'filtered'], ['aurora', 'filtered'], ['denali', 'applied'], ['polaris', 'rejected'],
      ['kaizen', 'found'],
    ];
    const flow: Stage[] = ['found', 'verified', 'drafted', 'checked', 'applied', 'replied'];

    plan.forEach(([key, target], i) => {
      const p = POOL.find((x) => x.key === key)!;
      const depth = target === 'filtered' ? 1 : target === 'interview' || target === 'offer' || target === 'rejected' ? 6 : flow.indexOf(target);
      const span = Math.max(1, depth) * rand(6, 14) * 60000;
      let t = now - span - rand(2, 40) * 60000 - (target === 'found' ? 0 : 5 * 60000) - i * 1000;
      let id = '';
      at(t, () => {
        const o = this.createOpp(p, t);
        id = o.id;
        this.bumpAgent('scout', 1);
        this.emit('task.succeeded', 'info', `Scout ✓ discover.ats — ${this.label(o)}`, { agent_id: 'scout', opportunity_id: o.id, data: { task_id: ulid(t), capability: 'discover.ats', agent_id: 'scout' } }, t);
        this.emit('opp.created', 'info', `New: ${this.label(o)} (${o.city})`, { agent_id: 'scout', opportunity_id: o.id, data: { opp: o } }, t);
      });
      if (target === 'found') return;
      const stepAt = (st: Stage) => {
        t += rand(3, 9) * 60000;
        const tt = t;
        at(tt, () => this.seedTransition(id, st, tt));
      };
      if (target === 'filtered') {
        stepAt('filtered');
        return;
      }
      const path: Stage[] =
        target === 'interview' || target === 'offer' || target === 'rejected'
          ? [...flow.slice(1), target]
          : flow.slice(1, flow.indexOf(target) + 1);
      for (const st of path) stepAt(st);
    });

    actions.sort((a, b) => a.t - b.t);
    for (const a of actions) a.fn();

    // seeded Claude/token usage for the day
    this.claudeCost = 0.84;
    this.claudeCalls = 14;
    this.localTokens = 1_240_000;

    // continue the flow for anything mid-pipeline
    for (const o of this.opps.values()) {
      if (!o.is_simulated) continue;
      const next = this.nextCapFor(o);
      if (next) this.enqueue(next, o.id, now);
    }
    this.nextHeartbeatAt = now;
    this.emit('worker.heartbeat', 'debug', 'worker heartbeat', { data: { queue: this.queue.length } }, now - 1000);
  }

  private seedTransition(id: string, st: Stage, t: number): void {
    const o = this.opps.get(id);
    const m = this.meta.get(id);
    if (!o || !m) return;
    const p = m.pool;
    const task = (agentId: string, cap: string) => {
      this.bumpAgent(agentId, 1, agentTokS(agentId) ? randInt(900, 4200) : 0);
      this.emit('task.succeeded', 'info', `${this.agents.get(agentId)?.name} ✓ ${cap} — ${this.label(o)}`, {
        agent_id: agentId, opportunity_id: id, data: { task_id: ulid(t), capability: cap, agent_id: agentId },
      }, t);
    };
    const handoff = (from: string, to: string, cap: string) =>
      this.emit('task.handoff', 'debug', `${from} → ${to} (${cap})`, { agent_id: from, opportunity_id: id, data: { from_agent: from, to_agent: to, capability: cap, opportunity_id: id } }, t);

    switch (st) {
      case 'filtered':
        task('verifier', 'verify.eligibility');
        this.updateOpp(id, {
          scam_status: p.flag === 'scam' ? 'scam' : 'clean',
          eligibility_status: p.flag === 'ineligible' ? 'ineligible' : 'eligible',
        }, t);
        this.setStage(id, 'filtered', p.filterReason ?? 'Filtered', t, 'verifier');
        break;
      case 'verified': {
        task('verifier', 'verify.eligibility');
        const fit = Math.max(0, Math.min(99, p.fit + randInt(-3, 3)));
        this.updateOpp(id, { fit_score: fit, eligibility_status: Math.random() < 0.2 ? 'eligible_gaps' : 'eligible', scam_status: 'clean' }, t);
        if (p.flag === 'unknown_pay') {
          this.setStage(id, 'verified', 'Pay not listed — your call', t, 'verifier');
          this.addNeed({
            opportunity_id: id, kind: 'decision', title: `Unknown pay — keep ${p.company}?`,
            instructions_md: `**${p.title}** doesn't list a stipend. Keep it in the pipeline (drafts continue) or drop it.`,
            direct_url: o.url, priority: 55, due_at: o.deadline_at, est_minutes: 0.5,
            answers: [{ label: 'Listed pay', value: p.pay.raw }],
          }, t + 1000);
        } else {
          this.setStage(id, 'verified', fit >= 60 ? `Fit ${fit} · eligible` : `Fit ${fit} < 60 — parked`, t, 'verifier');
          if (fit >= 60) handoff('verifier', 'writer', 'draft.cover_letter');
        }
        break;
      }
      case 'drafted':
        task('writer', 'draft.cover_letter');
        m.draftVersion = 1;
        this.setStage(id, 'drafted', 'Draft v1 · 11 sentences, 9 facts cited', t, 'writer');
        handoff('writer', 'factchecker', 'factcheck.sentence');
        break;
      case 'checked':
        task('factchecker', 'factcheck.sentence');
        handoff('factchecker', 'reviewer', 'factcheck.signoff');
        task('reviewer', 'factcheck.signoff');
        this.setStage(id, 'checked', 'All gates passed · Claude sign-off', t, 'reviewer');
        handoff('reviewer', 'resume', 'build.resume');
        break;
      case 'applied': {
        task('resume', 'build.resume');
        const cap = o.apply_channel === 'email' ? 'apply.email_send' : 'apply.manual_pack';
        task('applicant', cap);
        m.appId = ulid(t);
        m.appAt = iso(t);
        if (cap === 'apply.email_send') {
          this.emit('mail.mock_sent', 'info', `Mock mail → careers@${domainOf(p.company)}`, {
            agent_id: 'applicant', opportunity_id: id,
            data: { to: `careers@${domainOf(p.company)}`, subject: `Application: ${o.title}`, application_id: m.appId },
          }, t);
          this.setStage(id, 'applied', 'Emailed (mock mailbox · dry run)', t, 'applicant');
        } else {
          this.setStage(id, 'applied', 'Manual pack ready — needs you (≈2 min)', t, 'applicant');
          this.addNeed(this.submitNeed(this.opps.get(id)!), t + 1000);
        }
        break;
      }
      case 'replied':
        task('inbox', 'inbox.classify');
        this.setStage(id, 'replied', 'Reply received (auto-classified)', t, 'inbox');
        break;
      case 'interview':
      case 'offer':
      case 'rejected':
        this.finishOutcome(id, st, t);
        break;
      default:
        break;
    }
  }

  private submitNeed(o: OppSummary) {
    return {
      opportunity_id: o.id,
      kind: 'submit_form' as NeedKind,
      title: `Submit ${o.company_name} application (ATS form)`,
      instructions_md:
        'Open the form, paste the answers below (copy buttons), attach the files, submit, then press **I submitted it**.',
      answers: [
        { label: 'Full name', value: 'Prerit Sangwan', copy: true },
        { label: 'University', value: 'Bennett University', copy: true },
        { label: 'Degree', value: 'B.Tech CSE (AI/ML), 2nd year', copy: true },
        { label: 'Why this role? (≤ 300 chars)', value: `[SIM] Short answer drafted and fact-checked for ${o.company_name}.`, copy: true },
        { label: 'Phone', value: 'Needs you — not stored until confirmed', copy: false },
      ],
      files: [
        { name: 'resume.pdf', path: `data/artifacts/${o.id}/resume.pdf` },
        { name: 'cover_letter.pdf', path: `data/artifacts/${o.id}/cover_letter.pdf` },
      ],
      direct_url: o.url,
      priority: 60,
      due_at: o.deadline_at,
      est_minutes: 2,
    };
  }

  private finishOutcome(id: string, st: Stage, t: number): void {
    const o = this.opps.get(id)!;
    if (st === 'interview') {
      this.setStage(id, 'interview', 'Interview request — notify-only lock', t, 'inbox');
      this.addNeed({
        opportunity_id: id, kind: 'interview', title: `Interview request — ${o.company_name}`,
        instructions_md: 'Agents take **no action** on interviews. Reply yourself; the thread is locked for outbound.',
        direct_url: null, priority: 95, due_at: iso(t + 2 * 86400000), est_minutes: 5,
      }, t + 500);
      this.emit('notification', 'alert', `Interview request from ${o.company_name}`, {
        opportunity_id: id, data: { severity: 'alert', title: `Interview: ${o.company_name}`, body: o.title, url: `/o/${id}` },
      }, t + 600);
    } else if (st === 'offer') {
      this.setStage(id, 'offer', 'Offer received — notify-only lock', t, 'inbox');
      this.addNeed({
        opportunity_id: id, kind: 'offer', title: `Offer — ${o.company_name} (SIM)`,
        instructions_md: 'Offers, money and contracts are yours to handle. Compare pay on the detail page.',
        direct_url: null, priority: 98, due_at: iso(t + 5 * 86400000), est_minutes: 10,
      }, t + 500);
      this.emit('notification', 'alert', `Offer from ${o.company_name}`, {
        opportunity_id: id, data: { severity: 'alert', title: `Offer: ${o.company_name}`, body: o.title, url: `/o/${id}` },
      }, t + 600);
    } else {
      this.setStage(id, 'rejected', 'Rejection email (auto-classified)', t, 'inbox');
    }
  }

  private bumpAgent(id: string, tasks: number, tokens = 0): void {
    const a = this.agents.get(id);
    if (!a) return;
    this.agents.set(id, { ...a, tasks_today: a.tasks_today + tasks, tokens_today: a.tokens_today + tokens });
    this.localTokens += tokens;
  }

  // ── queue / dispatch ────────────────────────────────────────────────
  private nextCapFor(o: OppSummary): string | null {
    const m = this.meta.get(o.id);
    switch (o.stage) {
      case 'found':
        return 'verify.eligibility';
      case 'verified':
        return (o.fit_score ?? 0) >= 60 && m?.pool.flag !== 'unknown_pay' ? 'draft.cover_letter' : null;
      case 'drafted':
        return 'factcheck.sentence';
      case 'checked':
        return 'build.resume';
      case 'applied':
        if (m && m.replyAt == null) m.replyAt = Date.now() + rand(30, 90) * 1000;
        return null;
      default:
        return null;
    }
  }

  private capAgent(cap: string, requireIdle: boolean): Agent | null {
    for (const a of this.agents.values()) {
      if (!a.enabled || a.paused || !a.capabilities.includes(cap)) continue;
      if (requireIdle && (this.jobs.has(a.id) || a.status === 'error')) continue;
      return a;
    }
    return null;
  }

  private enqueue(capability: string, oppId: string | null, now = Date.now(), from: string | null = null): SimTask {
    const task: SimTask = { id: ulid(now), capability, oppId, attempts: 0, notBefore: now, createdAt: now };
    this.queue.push(task);
    const to = this.capAgent(capability, false);
    this.emit('task.created', 'debug', `queued ${capability}`, {
      agent_id: to?.id ?? null, opportunity_id: oppId, task_id: task.id, data: { task_id: task.id, capability },
    }, now);
    if (from && to) {
      this.emit('task.handoff', 'debug', `${from} → ${to.id} (${capability})`, {
        agent_id: from, opportunity_id: oppId, task_id: task.id,
        data: { from_agent: from, to_agent: to.id, capability, opportunity_id: oppId },
      }, now);
    }
    return task;
  }

  private get speed(): number {
    const s = Number(this.settings.sim_speed) || 1;
    return Math.min(4, Math.max(0.25, s));
  }

  private tick = (): void => {
    const now = Date.now();
    if (now >= this.nextHeartbeatAt) {
      this.nextHeartbeatAt = now + 10000;
      this.emit('worker.heartbeat', 'debug', 'worker heartbeat', { data: { queue: this.queue.length, running: this.jobs.size } });
    }
    if (this.settings.global_pause || !this.settings.sim_enabled) return;
    const speed = this.speed;

    if (now >= this.nextScoutAt) {
      this.nextScoutAt = now + (rand(25, 60) * 1000) / speed;
      if (!this.queue.some((t) => t.capability === 'discover.ats')) this.enqueue('discover.ats', null, now);
    }
    if (now >= this.nextInboxAt) {
      this.nextInboxAt = now + (rand(30, 50) * 1000) / speed;
      if (!this.queue.some((t) => t.capability === 'inbox.poll')) this.enqueue('inbox.poll', null, now);
    }
    if (now >= this.nextStrategistAt) {
      this.nextStrategistAt = now + (rand(150, 240) * 1000) / speed;
      this.enqueue('strategy.daily_review', null, now);
    }

    for (const task of [...this.queue]) {
      if (task.notBefore > now) continue;
      const agent = this.capAgent(task.capability, true);
      if (!agent) continue;
      this.queue.splice(this.queue.indexOf(task), 1);
      this.startJob(agent, task, now, speed);
    }

    for (const job of [...this.jobs.values()]) {
      if (now >= job.end) this.finishJob(job, now);
      else if (now >= job.nextStepAt) this.stepJob(job, now);
    }
  };

  private startJob(agent: Agent, task: SimTask, now: number, speed: number): void {
    const dur = (rand(2000, 8000) / speed) * (agent.cost_tier === 'claude' ? 1.3 : 1);
    const steps = randInt(3, 6);
    const p = task.oppId ? this.meta.get(task.oppId)?.pool ?? null : null;
    const lines = (NOW_LINES[task.capability] ?? [`Working on ${task.capability}…`]).map((l) => fill(l, p));
    const range = agentTokS(agent.id);
    const tokS = range ? rand(range[0], range[1]) : null;
    const job: Job = {
      task, agentId: agent.id, start: now, end: now + dur, stepMs: dur / steps, nextStepAt: now + dur / steps,
      lines, lineIdx: 0, tokS, tokens: 0,
    };
    this.jobs.set(agent.id, job);
    this.live.set(agent.id, {
      agent_id: agent.id,
      now_line: lines[0],
      progress: 0.04,
      current_task_id: task.id,
      opportunity_id: task.oppId,
      model_id: agent.model,
      tok_s: tokS ? Math.round(tokS) : null,
      heartbeat_at: iso(now),
      updated_at: iso(now),
    });
    this.setAgent(agent.id, { status: 'working' }, 'status');
    if (task.oppId) {
      const o = this.updateOpp(task.oppId, { active_agent_id: agent.id }, now);
      if (o) this.emit('opp.updated', 'debug', `${agent.name} working on ${this.label(o)}`, { agent_id: agent.id, opportunity_id: o.id, data: { opp: o } });
    }
    this.emit('task.leased', 'debug', `${agent.name} leased ${task.capability}`, {
      agent_id: agent.id, opportunity_id: task.oppId, task_id: task.id,
      data: { task_id: task.id, capability: task.capability, agent_id: agent.id, attempt: task.attempts + 1 },
    });
    this.emitLive(agent.id);
  }

  private stepJob(job: Job, now: number): void {
    job.nextStepAt = now + job.stepMs;
    job.lineIdx = Math.min(job.lines.length - 1, job.lineIdx + 1);
    const progress = Math.min(0.97, (now - job.start) / (job.end - job.start));
    const l = this.live.get(job.agentId);
    if (!l) return;
    const tokS = job.tokS ? Math.round(job.tokS * rand(0.9, 1.1)) : null;
    if (tokS) job.tokens += Math.round((tokS * job.stepMs) / 1000);
    this.live.set(job.agentId, {
      ...l,
      now_line: job.lines[job.lineIdx],
      progress,
      tok_s: tokS,
      heartbeat_at: iso(now),
      updated_at: iso(now),
    });
    this.emitLive(job.agentId);
  }

  private endJob(agentId: string, now: number): void {
    this.jobs.delete(agentId);
    const a = this.agents.get(agentId);
    this.live.set(agentId, {
      agent_id: agentId, now_line: null, progress: null, current_task_id: null, opportunity_id: null,
      model_id: a?.model ?? null, tok_s: null, heartbeat_at: iso(now), updated_at: iso(now),
    });
    this.emitLive(agentId);
  }

  private finishJob(job: Job, now: number): void {
    const { task, agentId } = job;
    const agent = this.agents.get(agentId)!;
    this.endJob(agentId, now);
    if (task.oppId) this.updateOpp(task.oppId, { active_agent_id: null }, now);
    const failed = Math.random() < 0.05;
    if (failed && task.oppId) {
      const o = this.opps.get(task.oppId);
      if (o) this.emit('opp.updated', 'debug', `${agent.name} released ${this.label(o)}`, { agent_id: agentId, opportunity_id: o.id, data: { opp: o } });
    }

    if (failed) {
      task.attempts += 1;
      const err = pick(['upstream timeout (sim)', 'JSON repair failed (sim)', 'HTTP 503 from board (sim)']);
      this.setAgent(agentId, { errors_today: agent.errors_today + 1, last_error: err, status: 'idle' }, false);
      this.emit('task.failed', 'warn', `${agent.name} ✗ ${task.capability}: ${err}`, {
        agent_id: agentId, opportunity_id: task.oppId, task_id: task.id,
        data: { task_id: task.id, capability: task.capability, agent_id: agentId, attempt: task.attempts },
      });
      if (task.attempts < 4) {
        const backoff = ((2 ** task.attempts) * 1500 + rand(0, 800)) / this.speed;
        task.notBefore = now + backoff;
        this.queue.push(task);
        this.emit('task.retry', 'warn', `retry ${task.capability} in ${(backoff / 1000).toFixed(1)}s (attempt ${task.attempts + 1}/4)`, {
          agent_id: agentId, opportunity_id: task.oppId, task_id: task.id,
          data: { task_id: task.id, capability: task.capability, agent_id: agentId, attempt: task.attempts + 1 },
        });
      } else {
        this.emit('task.dead', 'error', `${task.capability} dead after 4 attempts`, {
          agent_id: agentId, opportunity_id: task.oppId, task_id: task.id,
          data: { task_id: task.id, capability: task.capability, agent_id: agentId, attempt: task.attempts },
        });
      }
      this.emit('agent.status', 'debug', `${agent.name} → idle`, { agent_id: agentId, data: { status: 'idle' } });
      return;
    }

    const tokens = job.tokens || (job.tokS ? randInt(600, 3800) : 0);
    this.bumpAgent(agentId, 1, tokens);
    const o = task.oppId ? this.opps.get(task.oppId) : undefined;
    this.emit('task.succeeded', 'info', `${agent.name} ✓ ${task.capability}${o ? ` — ${this.label(o)}` : ''}`, {
      agent_id: agentId, opportunity_id: task.oppId, task_id: task.id,
      data: { task_id: task.id, capability: task.capability, agent_id: agentId },
    });
    this.setAgent(agentId, { status: 'idle' }, 'status');
    this.applyEffect(task, agentId, now);
  }

  // ── pipeline effects ────────────────────────────────────────────────
  private applyEffect(task: SimTask, agentId: string, now: number): void {
    const id = task.oppId;
    const o = id ? this.opps.get(id) : undefined;
    const m = id ? this.meta.get(id) : undefined;
    switch (task.capability) {
      case 'discover.ats': {
        const active = [...this.opps.values()].filter((x) => x.is_simulated && !TERMINAL.has(x.stage));
        if (active.length > 60) {
          this.emit('log', 'info', 'Scout: 60+ open sim opportunities — skipping discovery', { agent_id: agentId });
          break;
        }
        const busy = new Set(active.map((x) => this.meta.get(x.id)?.pool.key));
        const candidates = POOL.filter((p) => !busy.has(p.key));
        const n = Math.min(candidates.length, randInt(1, 2));
        if (!n) {
          this.emit('log', 'info', 'Scout: no new postings on 14 boards', { agent_id: agentId });
          break;
        }
        for (let i = 0; i < n; i++) {
          const p = candidates.splice(Math.floor(Math.random() * candidates.length), 1)[0];
          const opp = this.createOpp(p, now);
          this.emit('opp.created', 'info', `New: ${this.label(opp)} (${opp.city})`, {
            agent_id: agentId, opportunity_id: opp.id, data: { opp },
          });
          this.enqueue('verify.eligibility', opp.id, now, agentId);
        }
        break;
      }
      case 'verify.eligibility': {
        if (!o || !m) break;
        const p = m.pool;
        if (p.flag === 'scam' || p.flag === 'ineligible' || p.flag === 'expired') {
          this.updateOpp(o.id, {
            scam_status: p.flag === 'scam' ? 'scam' : 'clean',
            eligibility_status: p.flag === 'ineligible' ? 'ineligible' : 'eligible',
            fit_score: p.flag === 'scam' ? null : p.fit,
          }, now);
          this.setStage(o.id, 'filtered', p.filterReason ?? 'Filtered', now, agentId);
          break;
        }
        const fit = Math.max(0, Math.min(99, p.fit + randInt(-4, 4)));
        this.updateOpp(o.id, {
          fit_score: fit,
          eligibility_status: Math.random() < 0.2 ? 'eligible_gaps' : 'eligible',
          scam_status: 'clean',
        }, now);
        if (o.pay.living_cost_monthly_inr) {
          this.emit('log', 'debug', `Living cost ${p.city}: ₹${o.pay.living_cost_monthly_inr.toLocaleString('en-IN')}/mo (provisional)`, {
            agent_id: agentId, opportunity_id: o.id,
          });
        }
        if (p.flag === 'unknown_pay') {
          this.setStage(o.id, 'verified', 'Pay not listed — your call', now, agentId);
          this.addNeed({
            opportunity_id: o.id, kind: 'decision', title: `Unknown pay — keep ${p.company}?`,
            instructions_md: `**${o.title}** doesn't list a stipend. Keep it (drafting continues) or drop it.`,
            direct_url: o.url, priority: 55, due_at: o.deadline_at, est_minutes: 0.5,
            answers: [{ label: 'Listed pay', value: p.pay.raw }],
          });
        } else if (fit >= 60) {
          this.setStage(o.id, 'verified', `Fit ${fit} · eligible`, now, agentId);
          this.enqueue('draft.cover_letter', o.id, now, agentId);
        } else {
          this.setStage(o.id, 'verified', `Fit ${fit} < 60 — parked`, now, agentId);
        }
        break;
      }
      case 'draft.cover_letter': {
        if (!o || !m) break;
        m.draftVersion += 1;
        this.setStage(o.id, 'drafted', `Draft v${m.draftVersion} · ${randInt(9, 13)} sentences, ${randInt(7, 11)} facts cited`, now, agentId);
        this.enqueue('factcheck.sentence', o.id, now, agentId);
        break;
      }
      case 'factcheck.sentence': {
        if (!o || !m) break;
        if (m.draftLoops < 1 && Math.random() < 0.2) {
          m.draftLoops += 1;
          const rule = pick(["BANNED_CLAIM 'production'", "NUM_NOT_IN_FACTS '300+'", "WRONG_PROJECT 'RandomForest' in book project"]);
          this.emit('log', 'warn', `Fact gate blocked 1 sentence: ${rule} — rewrite requested`, { agent_id: agentId, opportunity_id: o.id });
          this.oppUpdated(o.id, { stage_reason: 'Rewrite requested by Fact-Checker' }, `${this.label(o)}: rewrite requested`, agentId, now);
          this.enqueue('draft.cover_letter', o.id, now, agentId);
        } else {
          this.enqueue('factcheck.signoff', o.id, now, agentId);
        }
        break;
      }
      case 'factcheck.signoff': {
        if (!o) break;
        const cost = rand(0.03, 0.09);
        this.claudeCost += cost;
        this.claudeCalls += 1;
        this.setStage(o.id, 'checked', `All gates passed · Claude sign-off $${cost.toFixed(2)}`, now, agentId);
        this.enqueue('build.resume', o.id, now, agentId);
        break;
      }
      case 'build.resume': {
        if (!o) break;
        this.oppUpdated(o.id, { stage_reason: 'Résumé PDF ready (1 page)' }, `${this.label(o)}: résumé ready`, agentId, now);
        this.enqueue(o.apply_channel === 'email' ? 'apply.email_send' : 'apply.manual_pack', o.id, now, agentId);
        break;
      }
      case 'apply.email_send': {
        if (!o || !m) break;
        if (this.settings.freeze_outbound) {
          this.emit('log', 'warn', `Outbound frozen — ${this.label(o)} held`, { agent_id: agentId, opportunity_id: o.id });
          const t = this.enqueue('apply.email_send', o.id, now);
          t.notBefore = now + 15000;
          break;
        }
        m.appId = ulid(now);
        m.appAt = iso(now);
        const to = `careers@${domainOf(o.company_name)}`;
        this.emit('mail.mock_sent', 'info', `Mock mail → ${to}`, {
          agent_id: agentId, opportunity_id: o.id, data: { to, subject: `Application: ${o.title}`, application_id: m.appId },
        });
        this.setStage(o.id, 'applied', 'Emailed (mock mailbox · dry run)', now, agentId);
        m.replyAt = now + (rand(40, 110) * 1000) / this.speed;
        this.enqueue('followup.schedule', o.id, now, agentId);
        break;
      }
      case 'apply.manual_pack': {
        if (!o || !m) break;
        m.appId = ulid(now);
        m.appAt = iso(now);
        this.setStage(o.id, 'applied', 'Manual pack ready — needs you (≈2 min)', now, agentId);
        this.addNeed(this.submitNeed(this.opps.get(o.id)!));
        m.replyAt = now + (rand(60, 140) * 1000) / this.speed;
        break;
      }
      case 'followup.schedule': {
        if (!o) break;
        this.emit('log', 'info', `Follow-up for ${o.company_name} scheduled in 10 days (one only)`, { agent_id: agentId, opportunity_id: o.id });
        break;
      }
      case 'inbox.poll': {
        const due = [...this.opps.values()].filter((x) => {
          const mm = this.meta.get(x.id);
          return x.is_simulated && x.stage === 'applied' && mm?.replyAt != null && mm.replyAt <= now;
        });
        if (!due.length) {
          this.emit('log', 'debug', 'Inbox: no new replies', { agent_id: agentId });
          break;
        }
        for (const x of due.slice(0, 2)) {
          this.meta.get(x.id)!.replyAt = null;
          this.enqueue('inbox.classify', x.id, now, agentId);
        }
        break;
      }
      case 'inbox.classify': {
        if (!o) break;
        const r = Math.random();
        const outcome: Outcome = r < 0.25 ? 'interview' : r < 0.7 ? 'rejected' : r < 0.78 ? 'offer' : 'info';
        this.setStage(o.id, 'replied', outcome === 'info' ? 'Reply: info request — draft only' : `Reply classified: ${outcome}`, now, agentId);
        if (outcome !== 'info') this.finishOutcome(o.id, outcome, now + 50);
        break;
      }
      case 'strategy.daily_review': {
        const cost = rand(0.12, 0.25);
        this.claudeCost += cost;
        this.claudeCalls += 1;
        const verified = [...this.opps.values()].filter((x) => (this.meta.get(x.id)?.reached ?? 0) >= 1).length;
        this.emit('log', 'info', `Strategist: daily review — ${verified} verified today · top source Greenhouse · 2 proposals ($${cost.toFixed(2)})`, {
          agent_id: agentId, data: { proposals: ['Add ATS slug: pixelwise', 'Raise fit_draft_threshold to 62'] },
        });
        break;
      }
      default:
        break;
    }
  }

  // ── commands (API) ──────────────────────────────────────────────────
  pauseAll(reason: string | null): void {
    if (this.settings.global_pause) return;
    this.settings = { ...this.settings, global_pause: true };
    const now = Date.now();
    for (const job of [...this.jobs.values()]) {
      this.endJob(job.agentId, now);
      job.task.notBefore = now;
      this.queue.unshift(job.task);
      this.emit('log', 'warn', `Cancelled ${job.task.capability} on ${job.agentId} (global pause) — requeued`, { agent_id: job.agentId, task_id: job.task.id });
    }
    for (const a of this.agents.values()) this.setAgent(a.id, { status: 'paused' }, 'status');
    this.emit('control.pause', 'alert', `PAUSE ALL${reason ? ` — ${reason}` : ''}`, { data: { paused: true, reason } });
  }

  resumeAll(): void {
    if (!this.settings.global_pause) return;
    this.settings = { ...this.settings, global_pause: false };
    for (const a of this.agents.values()) {
      this.setAgent(a.id, { status: !a.enabled ? 'disabled' : a.paused ? 'paused' : 'idle' }, 'status');
    }
    this.emit('control.pause', 'info', 'Resumed — agents back online', { data: { paused: false, reason: null } });
  }

  freeze(on: boolean): void {
    this.settings = { ...this.settings, freeze_outbound: on };
    this.emit('control.freeze', on ? 'warn' : 'info', on ? 'Outbound frozen' : 'Outbound unfrozen', { data: { freeze_outbound: on } });
  }

  patchSettings(patch: Record<string, unknown>): Settings {
    const clean: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(patch)) if (SETTINGS_WHITELIST.has(k) && k !== 'mode') clean[k] = v;
    this.settings = { ...this.settings, ...clean } as Settings;
    this.emit('settings.updated', 'info', `Settings updated: ${Object.keys(clean).join(', ') || 'nothing'}`, { data: { settings: this.settings } });
    return this.settings;
  }

  patchAgent(id: string, patch: AgentPatch): Agent | null {
    const a = this.agents.get(id);
    if (!a) return null;
    const next: Partial<Agent> = { ...patch };
    if (patch.paused !== undefined || patch.enabled !== undefined) {
      const paused = patch.paused ?? a.paused;
      const enabled = patch.enabled ?? a.enabled;
      if ((paused || !enabled) && this.jobs.has(id)) {
        const job = this.jobs.get(id)!;
        this.endJob(id, Date.now());
        this.queue.unshift(job.task);
      }
      next.status = !enabled ? 'disabled' : paused || this.settings.global_pause ? 'paused' : 'idle';
    }
    const out = this.setAgent(id, next, 'updated');
    return out ? this.agentOut(out) : null;
  }

  createAgent(cfg: AgentConfig): Agent {
    const agent: Agent = {
      id: cfg.id, name: cfg.name, avatar: cfg.avatar, color: cfg.color, role: cfg.role, adapter: cfg.adapter,
      model: cfg.model, capabilities: cfg.capabilities, cost_tier: cfg.cost_tier, concurrency: cfg.concurrency,
      schedule: cfg.schedule, enabled: cfg.enabled, paused: false, status: cfg.enabled ? 'idle' : 'disabled',
      builtin: false, side_effects: [], tasks_today: 0, errors_today: 0, tokens_today: 0, restarts: 0,
      last_error: null, live: null, description: cfg.description,
    };
    this.agents.set(agent.id, agent);
    this.emit('agent.added', 'info', `Agent added: ${agent.name}`, { agent_id: agent.id, data: { agent } });
    return agent;
  }

  deleteAgent(id: string): void {
    const a = this.agents.get(id);
    if (!a) return;
    this.agents.delete(id);
    this.jobs.delete(id);
    this.live.delete(id);
    this.emit('agent.removed', 'info', `Agent removed: ${a.name}`, { agent_id: id, data: { agent: a } });
  }

  overrideStage(id: string, stage: Stage, reason: string): OppSummary | null {
    const o = this.opps.get(id);
    if (!o) return null;
    this.setStage(id, stage, `Manual override: ${reason || 'display only'}`);
    return this.opps.get(id) ?? null;
  }

  resetSim(): number {
    let n = 0;
    for (const [id, o] of [...this.opps]) {
      if (!o.is_simulated) continue;
      this.opps.delete(id);
      this.meta.delete(id);
      n++;
    }
    for (const [id, need] of [...this.needs]) {
      if (need.opportunity_id && !this.opps.has(need.opportunity_id)) this.needs.delete(id);
    }
    this.queue = this.queue.filter((t) => !t.oppId || this.opps.has(t.oppId));
    this.emit('log', 'warn', `Sim reset: purged ${n} simulated opportunities`);
    this.broadcast({ event: 'resync', data: {} });
    return n;
  }

  // ── read models ─────────────────────────────────────────────────────
  stats(): Stats {
    const opps = [...this.opps.values()];
    const by_stage: Record<string, number> = {};
    for (const s of Object.keys(STAGE_META)) by_stage[s] = 0;
    for (const o of opps) by_stage[o.stage] = (by_stage[o.stage] ?? 0) + 1;
    const reached = (n: number) => opps.filter((o) => o.stage !== 'filtered' && (this.meta.get(o.id)?.reached ?? 0) >= n).length;
    const applied = reached(4);
    const interviews = by_stage.interview + by_stage.offer;
    const median = (xs: number[]) => {
      if (!xs.length) return null;
      const s = [...xs].sort((a, b) => a - b);
      const mid = Math.floor(s.length / 2);
      return s.length % 2 ? s[mid] : Math.round((s[mid - 1] + s[mid]) / 2);
    };
    const monthly = (o: OppSummary) => o.pay.monthly_inr_mid ?? o.pay.monthly_inr_min;
    const live = opps.filter((o) => !['filtered', 'rejected', 'skipped'].includes(o.stage));
    const pipe = live.map(monthly).filter((x): x is number => x != null);
    const offers = opps.filter((o) => o.stage === 'offer').map(monthly).filter((x): x is number => x != null);
    const appliedPay = opps
      .filter((o) => (this.meta.get(o.id)?.reached ?? 0) >= 4)
      .map(monthly)
      .filter((x): x is number => x != null);
    return {
      found: opps.length,
      verified: reached(1),
      drafted: reached(2),
      applied,
      replies: reached(5),
      interviews,
      offers: by_stage.offer,
      rejected: by_stage.rejected,
      filtered: by_stage.filtered,
      success_rate: applied ? interviews / applied : null,
      needs_open: [...this.needs.values()].filter((n) => n.status === 'open').length,
      claude_cost_today_usd: Math.round(this.claudeCost * 100) / 100,
      claude_budget_usd: this.settings.claude_daily_budget_usd,
      claude_calls_today: this.claudeCalls,
      local_tokens_today: this.localTokens,
      pay: {
        pipeline_median_inr: median(pipe),
        pipeline_max_inr: pipe.length ? Math.max(...pipe) : null,
        best_offer_inr: offers.length ? Math.max(...offers) : null,
        median_applied_inr: median(appliedPay),
      },
      by_stage,
      sim: this.settings.sim_enabled,
    };
  }

  snapshot(): Snapshot {
    return {
      settings: this.settings,
      agents: [...this.agents.values()].map((a) => this.agentOut(a)),
      opportunities: [...this.opps.values()],
      events: this.events.slice(-200),
      stats: this.stats(),
      needs: [...this.needs.values()].filter((n) => n.status === 'open' || n.status === 'snoozed'),
      server_time: iso(Date.now()),
      last_event_id: this.nextEventId - 1,
    };
  }

  detail(id: string): OppDetail | null {
    const o = this.opps.get(id);
    const m = this.meta.get(id);
    if (!o || !m) return null;
    const p = m.pool;
    const reached = m.reached;
    const applications: Application[] = [];
    const documents: Document[] = [];
    if (m.legacy) {
      applications.push({ id: m.appId!, channel: o.apply_channel, status: 'historical_frozen', mode: 'dry_run', submitted_at: null, created_at: o.first_seen_at });
      documents.push({ id: `${id}-letter`, kind: 'cover_letter', version: 1, status: 'historical', author_agent: null, author_model: 'legacy session', content_text: m.legacy.letter, created_at: o.first_seen_at, file_url: null });
      documents.push({ id: `${id}-resume`, kind: 'resume_pdf', version: 1, status: 'historical', author_agent: null, author_model: null, content_text: null, created_at: o.first_seen_at, file_url: null });
    } else {
      if (reached >= 2) {
        documents.push({
          id: `${id}-letter`, kind: 'cover_letter', version: Math.max(1, m.draftVersion), status: reached >= 3 ? 'passed' : 'checking',
          author_agent: 'writer', author_model: this.agents.get('writer')?.model ?? null,
          content_text: `Dear ${o.company_name} team,\n\n[SIMULATED DRAFT — produced by the sim adapter for UI testing; it is not a real letter and was never sent.]\n\nI am applying for the ${o.title} position${o.city ? ` in ${o.city}` : ''}. Paragraphs here would cite verified facts (F-*) and quotes from the job posting (J-*).\n\nSincerely,\nPrerit`,
          created_at: o.updated_at, file_url: null,
        });
      }
      if (reached >= 3) {
        documents.push({ id: `${id}-resume`, kind: 'resume_pdf', version: 1, status: 'passed', author_agent: 'resume', author_model: null, content_text: null, created_at: o.updated_at, file_url: null });
      }
      if (reached >= 4 && m.appId) {
        applications.push({
          id: m.appId, channel: o.apply_channel, status: o.apply_channel === 'email' ? 'submitted' : 'needs_prerit',
          mode: 'dry_run', submitted_at: o.apply_channel === 'email' ? m.appAt : null, created_at: m.appAt ?? o.updated_at,
        });
      }
    }
    return {
      ...o,
      summary: `${o.title} at ${o.company_name} (${o.city ?? 'location n/a'}). ${p.kind.replace('_', ' ')} · ${o.work_mode ?? 'unknown'} · pay: ${p.pay.raw}.${o.is_simulated ? ' Simulated listing (fictional organisation).' : ''}`,
      notes_unverified: m.legacy?.notes ?? null,
      applications,
      documents,
      timeline: this.events.filter((e) => e.opportunity_id === id && e.level !== 'debug').slice(-100),
      gates: reached >= 3 ? [{ gate: 'fact', passed: true }, { gate: 'eligibility', passed: true }, { gate: 'quality', passed: true }, { gate: 'scam', passed: true }] : [],
      eligibility_checks: reached >= 1 ? [{ method: 'rules+llm', verdict: o.eligibility_status, confidence: 0.86, quotes: ['"Open to current undergraduate students"'] }] : [],
      needs: [...this.needs.values()].filter((n) => n.opportunity_id === id),
    };
  }
}
