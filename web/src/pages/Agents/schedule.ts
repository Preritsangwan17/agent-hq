/** Schedule helpers shared by the Agents page (cards, editor, wizard) and Settings → Schedules. */
import type { AgentSchedule } from '@/lib/types';

/** Mirrors hq/agents/schema.py SCHEDULABLE (used when /api/agents/meta doesn't say `schedulable`). */
export const SCHEDULABLE_FALLBACK: readonly string[] = [
  'discover.ats',
  'discover.program_page',
  'discover.feed',
  'discover.email_alerts',
  'inbox.poll',
  'strategy.daily_review',
];

const CRON_FIELD = /^(\*|\d+|\d+-\d+|\*\/\d+|\d+(-\d+)?\/\d+)(,(\d+|\d+-\d+))*$/;

/** Light client-side 5-field cron check (the backend validates with croniter). */
export function isValidCron(expr: string): boolean {
  const parts = expr.trim().split(/\s+/);
  return parts.length === 5 && parts.every((p) => CRON_FIELD.test(p));
}

const pad = (n: number) => String(n).padStart(2, '0');

/** Human text for common cron shapes; falls back to the expression. */
export function describeCron(expr: string | undefined): string {
  if (!expr) return 'Cron (not set)';
  const p = expr.trim().split(/\s+/);
  if (p.length !== 5) return expr;
  const [m, h, dom, mon, dow] = p;
  const num = (x: string) => /^\d+$/.test(x);
  if (num(m) && num(h) && dom === '*' && mon === '*' && dow === '*') return `Daily at ${pad(+h)}:${pad(+m)}`;
  if (num(m) && num(h) && dom === '*' && mon === '*' && dow === '1-5') return `Weekdays at ${pad(+h)}:${pad(+m)}`;
  if (/^\*\/\d+$/.test(m) && h === '*' && dom === '*' && mon === '*' && dow === '*') return `Every ${m.slice(2)} min`;
  if (num(m) && h === '*' && dom === '*' && mon === '*' && dow === '*') return `Hourly at :${pad(+m)}`;
  if (num(m) && /^\*\/\d+$/.test(h) && dom === '*' && mon === '*' && dow === '*') return `Every ${h.slice(2)} h at :${pad(+m)}`;
  return expr;
}

export function formatMinutes(min: number | undefined): string {
  if (!min || min <= 0) return '—';
  if (min < 1) return `${Math.round(min * 60)} s`;
  if (min < 60) return `${+min.toFixed(1)} min`;
  if (min % 60 === 0) return `${min / 60} h`;
  return `${Math.floor(min / 60)} h ${Math.round(min % 60)} min`;
}

export function describeSchedule(s: AgentSchedule | null | undefined): string {
  if (!s || s.mode === 'on_demand') return 'On demand';
  if (s.mode === 'interval') return `Every ${formatMinutes(s.minutes)}`;
  return describeCron(s.cron);
}
