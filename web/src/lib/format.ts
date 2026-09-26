/**
 * Formatting helpers: INR with Indian digit grouping (₹25,000 · ₹1.2L · ₹3.4Cr), original-currency amounts,
 * pay periods, and Asia/Kolkata time display (all timestamps on the wire are UTC ISO strings).
 */

export const IST = 'Asia/Kolkata';

const inrFull = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
const inrFrac = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 });

/** ₹25,000 (Indian grouping). Values under 100 keep up to 2 decimals (hourly rates). */
export function formatINR(n: number | null | undefined, opts: { symbol?: boolean } = {}): string {
  if (n == null || !Number.isFinite(n)) return '—';
  const sym = opts.symbol === false ? '' : '₹';
  const abs = Math.abs(n);
  const body = abs < 100 && abs % 1 !== 0 ? inrFrac.format(abs) : inrFull.format(Math.round(abs));
  return `${n < 0 ? '−' : ''}${sym}${body}`;
}

function trimNum(x: number, digits: number): string {
  return x.toFixed(digits).replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1');
}

/** Compact INR: ₹1.2L for lakhs, ₹3.4Cr for crores, ₹25K for thousands (≥ 10,000), else full. */
export function formatINRCompact(n: number | null | undefined, opts: { symbol?: boolean } = {}): string {
  if (n == null || !Number.isFinite(n)) return '—';
  const sym = opts.symbol === false ? '' : '₹';
  const abs = Math.abs(n);
  const sign = n < 0 ? '−' : '';
  if (abs >= 1e7) return `${sign}${sym}${trimNum(abs / 1e7, abs >= 1e8 ? 0 : 1)}Cr`;
  if (abs >= 1e5) return `${sign}${sym}${trimNum(abs / 1e5, abs >= 1e6 ? 0 : 1)}L`;
  if (abs >= 1e4) return `${sign}${sym}${trimNum(abs / 1e3, 0)}K`;
  return formatINR(n, opts);
}

/** ₹25,000–40,000 (shared symbol). Falls back to a single value when min === max or one side is missing. */
export function formatINRRange(
  min: number | null | undefined,
  max: number | null | undefined,
  opts: { compact?: boolean } = {},
): string {
  const f = opts.compact ? formatINRCompact : formatINR;
  if (min == null && max == null) return '—';
  if (min == null || max == null || Math.round(min) === Math.round(max)) return f((min ?? max) as number);
  return `${f(min)}–${f(max, { symbol: false })}`;
}

const CURRENCY_SYMBOL: Record<string, string> = {
  INR: '₹', USD: '$', EUR: '€', GBP: '£', JPY: '¥', CNY: 'CN¥', TWD: 'NT$', SGD: 'S$', CAD: 'C$', AUD: 'A$',
  HKD: 'HK$', KRW: '₩', CHF: 'CHF ', AED: 'AED ',
};

/** Amount in its original currency, e.g. NT$15,000 · $13.25 · CHF 4,500 · €1,800. */
export function formatMoney(amount: number | null | undefined, currency: string | null | undefined): string {
  if (amount == null || !Number.isFinite(amount)) return '—';
  const cur = (currency || '').toUpperCase();
  if (cur === 'INR') return formatINR(amount);
  const sym = CURRENCY_SYMBOL[cur] ?? (cur ? `${cur} ` : '');
  const digits = amount % 1 === 0 ? 0 : 2;
  const body = new Intl.NumberFormat('en-US', { minimumFractionDigits: digits, maximumFractionDigits: 2 }).format(amount);
  return `${sym}${body}`;
}

export function formatMoneyRange(
  min: number | null | undefined,
  max: number | null | undefined,
  currency: string | null | undefined,
): string {
  if (min == null && max == null) return '—';
  if (min == null || max == null || min === max) return formatMoney(min ?? max, currency);
  const right = formatMoney(max, currency).replace(/^[^\d]+/, '');
  return `${formatMoney(min, currency)}–${right}`;
}

const PERIOD_SHORT: Record<string, string> = {
  hour: '/hr', day: '/day', week: '/wk', month: '/mo', year: '/yr', lump: ' total', unknown: '',
};
const PERIOD_LONG: Record<string, string> = {
  hour: 'per hour', day: 'per day', week: 'per week', month: 'per month', year: 'per year', lump: 'lump sum',
  unknown: '',
};

export function periodShort(p: string | null | undefined): string {
  return (p && PERIOD_SHORT[p]) ?? '';
}
export function periodLong(p: string | null | undefined): string {
  return (p && PERIOD_LONG[p]) ?? '';
}

export function formatRatio(r: number | null | undefined): string {
  if (r == null || !Number.isFinite(r)) return '—';
  return `${r >= 10 ? r.toFixed(0) : r.toFixed(1)}×`;
}

export function formatNumber(n: number | null | undefined, digits = 0): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return new Intl.NumberFormat('en-IN', { maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(n);
}

/** 12.4k · 1.2M tokens style (Western compact, used for tokens/counts). */
export function formatCompact(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(n);
}

export function formatUSD(n: number | null | undefined, digits = 2): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return `$${n.toFixed(digits)}`;
}

export function formatPercent(x: number | null | undefined, digits = 0): string {
  if (x == null || !Number.isFinite(x)) return '—';
  return `${(x * 100).toFixed(digits)}%`;
}

// ── time (display in IST) ─────────────────────────────────────────────

export function toDate(iso: string | number | Date | null | undefined): Date | null {
  if (iso == null) return null;
  const d = iso instanceof Date ? iso : new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

const fmtCache = new Map<string, Intl.DateTimeFormat>();
function dtf(opts: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = JSON.stringify(opts);
  let f = fmtCache.get(key);
  if (!f) {
    f = new Intl.DateTimeFormat('en-IN', { timeZone: IST, ...opts });
    fmtCache.set(key, f);
  }
  return f;
}

/** "26 Sep, 7:15 pm" in IST. */
export function formatDateTimeIST(iso: string | null | undefined): string {
  const d = toDate(iso);
  if (!d) return '—';
  return dtf({ day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true }).format(d);
}

/** "26 Sep 2026" in IST. */
export function formatDateIST(iso: string | null | undefined, withYear = true): string {
  const d = toDate(iso);
  if (!d) return '—';
  return dtf({ day: 'numeric', month: 'short', ...(withYear ? { year: 'numeric' } : {}) }).format(d);
}

/** "19:15:04" in IST (24h) — used by log/terminal views. */
export function formatClockIST(iso: string | null | undefined, seconds = true): string {
  const d = toDate(iso);
  if (!d) return '--:--';
  return dtf({ hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}), hour12: false }).format(d);
}

/** "just now", "5m ago", "3h ago", "2d ago" / "in 4h". */
export function formatRelative(iso: string | null | undefined, now: number = Date.now()): string {
  const d = toDate(iso);
  if (!d) return '—';
  const diff = d.getTime() - now;
  const abs = Math.abs(diff);
  const future = diff > 0;
  const s = Math.round(abs / 1000);
  if (s < 10) return future ? 'in a moment' : 'just now';
  let out: string;
  if (s < 60) out = `${s}s`;
  else if (s < 3600) out = `${Math.floor(s / 60)}m`;
  else if (s < 86400) out = `${Math.floor(s / 3600)}h`;
  else if (s < 86400 * 45) out = `${Math.floor(s / 86400)}d`;
  else out = `${Math.floor(s / (86400 * 30))}mo`;
  return future ? `in ${out}` : `${out} ago`;
}

/** Duration in ms → "3d 4h", "5h 12m", "12m 05s", "42s". */
export function formatDuration(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${String(sec).padStart(2, '0')}s`;
  return `${sec}s`;
}

/** Country code → flag emoji (IN → 🇮🇳). */
export function flagEmoji(iso2: string | null | undefined): string {
  if (!iso2 || iso2.length !== 2) return '🌐';
  const base = 0x1f1e6;
  const up = iso2.toUpperCase();
  return String.fromCodePoint(base + up.charCodeAt(0) - 65, base + up.charCodeAt(1) - 65);
}

export function titleCase(s: string | null | undefined): string {
  if (!s) return '';
  return s.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
