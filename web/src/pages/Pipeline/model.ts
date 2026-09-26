/**
 * Pipeline view model: board columns, filter/sort logic, filtered-out reason classification and small pay helpers.
 * Pure functions only (no React) so the board, the stage strip and the detail page can share them.
 */
import {
  BadgeCheck,
  CalendarCheck,
  CalendarX,
  CircleHelp,
  MailOpen,
  PenLine,
  Radar,
  Send,
  ShieldAlert,
  ShieldCheck,
  Trophy,
  UserX,
  Wallet,
  type LucideIcon,
} from 'lucide-react';
import type { OppSummary, Pay, Stage } from '@/lib/types';
import { STAGE_META } from '@/theme/tokens';

// ── columns ───────────────────────────────────────────────────────────

export type ColumnId = Exclude<Stage, 'offer' | 'rejected' | 'filtered' | 'frozen' | 'skipped'> | 'outcome';

export interface ColumnDef {
  id: ColumnId;
  label: string;
  color: string;
  icon: LucideIcon;
  /** agent that usually moves cards out of this column */
  agent: string | null;
  /** empty-state hint */
  hint: string;
  stages: Stage[];
}

export const COLUMNS: readonly ColumnDef[] = [
  { id: 'found', label: 'Found', color: STAGE_META.found.color, icon: Radar, agent: 'scout', stages: ['found'], hint: 'Scout sweeps the boards every minute.' },
  { id: 'verified', label: 'Verified', color: STAGE_META.verified.color, icon: ShieldCheck, agent: 'verifier', stages: ['verified'], hint: 'Link, deadline, eligibility, pay and scam checks land here.' },
  { id: 'drafted', label: 'Drafted', color: STAGE_META.drafted.color, icon: PenLine, agent: 'writer', stages: ['drafted'], hint: 'Writer drafts only above the fit threshold.' },
  { id: 'checked', label: 'Checked', color: STAGE_META.checked.color, icon: BadgeCheck, agent: 'factchecker', stages: ['checked'], hint: 'Every sentence passes the fact gate and sign-off.' },
  { id: 'applied', label: 'Applied', color: STAGE_META.applied.color, icon: Send, agent: 'applicant', stages: ['applied'], hint: 'Dry run: mock mailbox and 2-minute manual packs.' },
  { id: 'replied', label: 'Replied', color: STAGE_META.replied.color, icon: MailOpen, agent: 'inbox', stages: ['replied'], hint: 'Inbox Watcher classifies every reply.' },
  { id: 'interview', label: 'Interview', color: STAGE_META.interview.color, icon: CalendarCheck, agent: 'inbox', stages: ['interview'], hint: 'Notify-only: interviews always come to you.' },
  { id: 'outcome', label: 'Offer / Rejected', color: STAGE_META.offer.color, icon: Trophy, agent: null, stages: ['offer', 'rejected'], hint: 'Outcomes are notify-only — nothing is accepted for you.' },
];

export function columnOf(stage: Stage): ColumnId | 'filtered' | 'frozen' {
  if (stage === 'offer' || stage === 'rejected') return 'outcome';
  if (stage === 'filtered') return 'filtered';
  if (stage === 'frozen' || stage === 'skipped') return 'frozen';
  return stage;
}

// ── filters & sort ────────────────────────────────────────────────────

export type SortKey = 'pay' | 'deadline' | 'fit' | 'recent';
export type SimFilter = 'all' | 'sim' | 'real';

export interface PipelineFilters {
  q: string;
  sim: SimFilter;
  /** minimum listed ₹/month (0 = any) */
  minPay: number;
  sort: SortKey;
}

export const DEFAULT_FILTERS: PipelineFilters = { q: '', sim: 'all', minPay: 0, sort: 'pay' };

export const MIN_PAY_PRESETS: readonly number[] = [0, 15000, 25000, 50000, 100000];

export const SORT_LABEL: Record<SortKey, string> = { pay: 'Pay', deadline: 'Deadline', fit: 'Fit', recent: 'Recent' };

/** Housing and meals are both covered (funded program): living cost is paid for regardless of the allowance. */
export function coversLiving(pay: Pay): boolean {
  return !!(pay.benefits?.housing && pay.benefits?.meals);
}

/** Comparable monthly ₹ figure (mid → min → max → allowance); null when unknown or hourly-only. */
export function monthlyValue(pay: Pay): number | null {
  return pay.monthly_inr_mid ?? pay.monthly_inr_min ?? pay.monthly_inr_max ?? pay.benefits?.allowance_inr ?? null;
}

/** Guaranteed monthly floor used by the "min ₹/month" filter. */
export function monthlyFloor(pay: Pay): number | null {
  return pay.monthly_inr_min ?? pay.monthly_inr_max ?? pay.benefits?.allowance_inr ?? null;
}

export function passesMinPay(o: OppSummary, min: number): boolean {
  if (!min) return true;
  if (coversLiving(o.pay)) return true;
  const v = monthlyFloor(o.pay);
  return v != null && v >= min;
}

export function matchesQuery(o: OppSummary, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  const hay = `${o.company_name} ${o.title} ${o.city ?? ''} ${o.country_iso2 ?? ''} ${o.kind} ${o.source_label ?? ''} ${o.pay.raw ?? ''}`.toLowerCase();
  return needle.split(/\s+/).every((w) => hay.includes(w));
}

export function applyFilters(opps: OppSummary[], f: PipelineFilters): OppSummary[] {
  return opps.filter(
    (o) =>
      (f.sim === 'all' || (f.sim === 'sim' ? o.is_simulated : !o.is_simulated)) &&
      passesMinPay(o, f.minPay) &&
      matchesQuery(o, f.q),
  );
}

function payRank(p: Pay): [number, number] {
  const m = monthlyValue(p);
  if (m != null) return [0, m];
  if (p.hourly_inr_max != null || p.hourly_inr_min != null) return [1, p.hourly_inr_max ?? p.hourly_inr_min ?? 0];
  return [2, 0];
}

function deadlineRank(o: OppSummary, now: number): [number, number] {
  const t = o.deadline_at ? Date.parse(o.deadline_at) : NaN;
  if (Number.isNaN(t) || o.deadline_confidence === 'rolling') return [1, 0];
  return t < now ? [2, -t] : [0, t];
}

export function sortOpps(opps: OppSummary[], key: SortKey, now = Date.now()): OppSummary[] {
  const out = opps.slice();
  const byRecent = (a: OppSummary, b: OppSummary) => (a.updated_at < b.updated_at ? 1 : a.updated_at > b.updated_at ? -1 : 0);
  switch (key) {
    case 'pay':
      out.sort((a, b) => {
        const [ga, va] = payRank(a.pay);
        const [gb, vb] = payRank(b.pay);
        return ga - gb || vb - va || byRecent(a, b);
      });
      break;
    case 'deadline':
      out.sort((a, b) => {
        const [ga, va] = deadlineRank(a, now);
        const [gb, vb] = deadlineRank(b, now);
        return ga - gb || va - vb || byRecent(a, b);
      });
      break;
    case 'fit':
      out.sort((a, b) => (b.fit_score ?? -1) - (a.fit_score ?? -1) || byRecent(a, b));
      break;
    default:
      out.sort(byRecent);
  }
  return out;
}

export function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = xs.slice().sort((a, b) => a - b);
  const mid = s.length >> 1;
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

export function medianMonthly(opps: OppSummary[]): number | null {
  return median(opps.map((o) => monthlyValue(o.pay)).filter((v): v is number => v != null));
}

// ── filtered-out reasons ──────────────────────────────────────────────

export type FilterReason = 'scam' | 'ineligible' | 'expired' | 'pay' | 'other';

export const FILTER_REASON_META: Record<FilterReason, { label: string; color: string; icon: LucideIcon }> = {
  scam: { label: 'Scam / mill', color: '#FB923C', icon: ShieldAlert },
  ineligible: { label: 'Ineligible', color: '#FBBF24', icon: UserX },
  expired: { label: 'Expired', color: '#94A3B8', icon: CalendarX },
  pay: { label: 'Pay', color: '#A8B3C7', icon: Wallet },
  other: { label: 'Other', color: '#64748B', icon: CircleHelp },
};

export function filterReason(o: OppSummary, now = Date.now()): FilterReason {
  const r = (o.stage_reason ?? '').toLowerCase();
  if (o.scam_status === 'scam' || o.scam_status === 'suspicious' || /scam|mill|registration fee/.test(r)) return 'scam';
  if (o.eligibility_status === 'ineligible' || /ineligib|eligib|graduates only|students only/.test(r)) return 'ineligible';
  if (/deadline|expired|closed|passed/.test(r)) return 'expired';
  if (o.deadline_at && o.deadline_confidence !== 'rolling' && Date.parse(o.deadline_at) < now) return 'expired';
  if (/pay|stipend|living cost|unpaid|fee/.test(r)) return 'pay';
  return 'other';
}

// ── fit ───────────────────────────────────────────────────────────────

export function fitColor(score: number | null | undefined): string {
  if (score == null) return '#5B6577';
  if (score >= 80) return '#34D399';
  if (score >= 65) return '#2DD4BF';
  if (score >= 50) return '#FBBF24';
  return '#8B95A7';
}
