/** Pipeline board model: column layout, filter predicate and sort comparators (pure functions). */
import type { OppSummary, Stage } from '@/lib/types';
import { STAGE_META } from '@/theme/tokens';
import { isLegacy } from './shared';

export type SimFilter = 'all' | 'sim' | 'real';
export type SortKey = 'pay' | 'deadline' | 'fit' | 'recent';

export interface PipelineFilters {
  q: string;
  sim: SimFilter;
  /** minimum ₹/month (0 = any) */
  minPay: number;
  sort: SortKey;
}

export const DEFAULT_FILTERS: PipelineFilters = { q: '', sim: 'all', minPay: 0, sort: 'pay' };

export const MIN_PAY_OPTIONS: readonly { value: number; label: string }[] = [
  { value: 0, label: 'Any' },
  { value: 15000, label: '₹15K' },
  { value: 25000, label: '₹25K' },
  { value: 50000, label: '₹50K' },
  { value: 100000, label: '₹1L' },
];

export interface ColumnDef {
  id: string;
  label: string;
  color: string;
  stages: readonly Stage[];
}

const col = (stage: Stage): ColumnDef => ({ id: stage, label: STAGE_META[stage].label, color: STAGE_META[stage].color, stages: [stage] });

/** Main flow, left → right. Offer and Rejected share the last column (two sections). */
export const BOARD_COLUMNS: readonly ColumnDef[] = [
  col('found'),
  col('verified'),
  col('drafted'),
  col('checked'),
  col('applied'),
  col('replied'),
  col('interview'),
  { id: 'outcome', label: 'Offer / Rejected', color: STAGE_META.offer.color, stages: ['offer', 'rejected'] },
];

export const FILTERED_COLUMN: ColumnDef = col('filtered');

export function matchesFilters(o: OppSummary, f: PipelineFilters): boolean {
  if (f.sim === 'sim' && !o.is_simulated) return false;
  if (f.sim === 'real' && o.is_simulated) return false;
  if (f.minPay > 0) {
    const best = o.pay?.monthly_inr_max ?? o.pay?.monthly_inr_min ?? null;
    if (best == null || best < f.minPay) return false;
  }
  const q = f.q.trim().toLowerCase();
  if (q) {
    const hay = `${o.company_name} ${o.title} ${o.city ?? ''} ${o.country_iso2 ?? ''} ${o.kind} ${o.source_label ?? ''}`.toLowerCase();
    if (!q.split(/\s+/).every((t) => hay.includes(t))) return false;
  }
  return true;
}

/** [tier, value]: listed monthly pay first (by mid), then hourly (hours vary), then unknown, then unpaid / fee. */
function payRank(o: OppSummary): [number, number] {
  const p = o.pay;
  if (!p || p.status === 'unpaid' || p.status === 'fee_required') return [3, 0];
  const monthly = p.monthly_inr_mid ?? p.monthly_inr_min ?? p.benefits?.allowance_inr ?? null;
  if (monthly != null) return [0, monthly];
  const hourly = p.hourly_inr_max ?? p.hourly_inr_min;
  if (hourly != null) return [1, hourly];
  return [2, 0];
}

function deadlineRank(o: OppSummary, now: number): [number, number] {
  if (!o.deadline_at || o.deadline_confidence === 'rolling') return [1, 0];
  const t = Date.parse(o.deadline_at);
  if (!Number.isFinite(t)) return [1, 0];
  return t < now ? [2, -t] : [0, t];
}

const byRecent = (a: OppSummary, b: OppSummary) => (a.updated_at < b.updated_at ? 1 : a.updated_at > b.updated_at ? -1 : 0);

export function comparator(sort: SortKey, now = Date.now()): (a: OppSummary, b: OppSummary) => number {
  switch (sort) {
    case 'pay':
      return (a, b) => {
        const [ta, va] = payRank(a);
        const [tb, vb] = payRank(b);
        return ta - tb || vb - va || byRecent(a, b);
      };
    case 'deadline':
      return (a, b) => {
        const [ta, va] = deadlineRank(a, now);
        const [tb, vb] = deadlineRank(b, now);
        return ta - tb || va - vb || byRecent(a, b);
      };
    case 'fit':
      return (a, b) => (b.fit_score ?? -1) - (a.fit_score ?? -1) || byRecent(a, b);
    default:
      return byRecent;
  }
}

export interface BoardModel {
  columns: Record<string, OppSummary[]>;
  filtered: OppSummary[];
  legacy: OppSummary[];
  /** items matching the filters (board + filtered + legacy) */
  shown: number;
  /** all items before filtering */
  total: number;
}

/** Split opportunities into board columns, the Filtered column and the legacy lane, filtered and sorted. */
export function buildBoard(opps: readonly OppSummary[], f: PipelineFilters): BoardModel {
  const cmp = comparator(f.sort);
  const columns: Record<string, OppSummary[]> = {};
  for (const c of BOARD_COLUMNS) columns[c.id] = [];
  const stageToCol = new Map<Stage, string>();
  for (const c of BOARD_COLUMNS) for (const s of c.stages) stageToCol.set(s, c.id);
  const filtered: OppSummary[] = [];
  const legacy: OppSummary[] = [];
  let shown = 0;
  for (const o of opps) {
    if (!matchesFilters(o, f)) continue;
    shown++;
    if (isLegacy(o) && (o.stage === 'frozen' || o.stage === 'skipped')) legacy.push(o);
    else if (o.stage === 'filtered' || o.stage === 'skipped') filtered.push(o);
    else if (o.stage === 'frozen') legacy.push(o);
    else columns[stageToCol.get(o.stage) ?? 'found']?.push(o);
  }
  for (const k in columns) columns[k].sort(cmp);
  filtered.sort(cmp);
  legacy.sort(cmp);
  return { columns, filtered, legacy, shown, total: opps.length };
}

/** Median of the monthly ₹ figures in a column (for the column header). */
export function medianMonthly(items: readonly OppSummary[]): number | null {
  const vals = items
    .map((o) => o.pay?.monthly_inr_mid ?? o.pay?.monthly_inr_min ?? null)
    .filter((v): v is number => v != null)
    .sort((a, b) => a - b);
  if (!vals.length) return null;
  const m = Math.floor(vals.length / 2);
  return vals.length % 2 ? vals[m] : (vals[m - 1] + vals[m]) / 2;
}
