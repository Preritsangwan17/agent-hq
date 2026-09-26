/**
 * PayBadge — "how much they pay me", everywhere.
 *   • big gold ₹/month (min–max), original currency + period underneath
 *   • ratio bar vs living cost: green ≥ 1.5×, amber 1–1.5×, red < 1×
 *   • tooltip with provenance (raw text, FX rate/date, living-cost basis/confidence, ratio math)
 *   • funded programs: "Stay + food + travel + ₹X/mo"; hourly with unknown hours: "Hourly, hours vary";
 *     unknown / unpaid / fee-required states.
 */
import { Ban, CircleHelp, TriangleAlert } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';
import {
  formatDateIST,
  formatINR,
  formatINRCompact,
  formatINRRange,
  formatMoneyRange,
  formatRatio,
  periodLong,
  titleCase,
} from '@/lib/format';
import type { Pay } from '@/lib/types';
import { colors } from '@/theme/tokens';
import { Tooltip } from './Tooltip';

export interface PayBadgeProps {
  pay: Pay | null | undefined;
  size?: 'sm' | 'md' | 'lg';
  /** ₹1.2L / ₹45K style numbers */
  compact?: boolean;
  /** ratio bar vs living cost (default true) */
  showRatio?: boolean;
  /** original currency + period line (default true) */
  showOriginal?: boolean;
  /** provenance tooltip (default true) */
  tooltip?: boolean;
  align?: 'left' | 'right';
  className?: string;
}

type PayKind = 'monthly' | 'hourly' | 'funded' | 'unknown' | 'unpaid' | 'fee';

export function payKind(pay: Pay | null | undefined): PayKind {
  if (!pay) return 'unknown';
  if (pay.status === 'unpaid') return 'unpaid';
  if (pay.status === 'fee_required') return 'fee';
  const b = pay.benefits ?? {};
  if (b.housing || b.meals || b.travel) return 'funded';
  if (pay.status === 'variable' || (pay.hourly_inr_min != null && pay.monthly_inr_min == null)) return 'hourly';
  if (pay.monthly_inr_min != null) return 'monthly';
  return 'unknown';
}

export function ratioColor(r: number | null | undefined): string {
  if (r == null) return colors.muted;
  if (r >= 1.5) return colors.ratioGood;
  if (r >= 1) return colors.ratioOk;
  return colors.ratioLow;
}

/** Items covered by a funded program, e.g. "Stay + food + travel". */
export function coveredLabel(pay: Pay): string {
  const b = pay.benefits ?? {};
  const parts = [b.housing && 'Stay', b.meals && 'food', b.travel && 'travel'].filter(Boolean) as string[];
  if (!parts.length) return '';
  parts[0] = parts[0][0].toUpperCase() + parts[0].slice(1);
  return parts.join(' + ');
}

const SIZES = {
  sm: { main: 'text-[15px]', unit: 'text-[10.5px]', orig: 'text-[10.5px]', gap: 'gap-1', bar: 'h-1 w-16' },
  md: { main: 'text-xl', unit: 'text-xs', orig: 'text-[11px]', gap: 'gap-1.5', bar: 'h-1.5 w-24' },
  lg: { main: 'text-4xl md:text-5xl', unit: 'text-base', orig: 'text-sm', gap: 'gap-2.5', bar: 'h-2 w-44' },
} as const;

function original(pay: Pay): string | null {
  const per = periodLong(pay.period);
  if (pay.min == null && pay.max == null) return pay.raw;
  if ((pay.currency ?? '').toUpperCase() === 'INR' && pay.period === 'month') return 'INR · monthly, as listed';
  return `${formatMoneyRange(pay.min, pay.max, pay.currency)}${per ? ` ${per}` : ''}`;
}

export function PayBadge({
  pay,
  size = 'md',
  compact,
  showRatio = true,
  showOriginal = true,
  tooltip = true,
  align = 'left',
  className,
}: PayBadgeProps) {
  const kind = payKind(pay);
  const sz = SIZES[size];
  const inr = compact ? formatINRCompact : formatINR;
  const jr = align === 'right' ? 'justify-end' : '';
  let body: ReactNode;

  if (kind === 'unknown' || kind === 'unpaid' || kind === 'fee' || !pay) {
    const Icon = kind === 'unpaid' ? Ban : kind === 'fee' ? TriangleAlert : CircleHelp;
    const label = kind === 'unpaid' ? 'Unpaid' : kind === 'fee' ? 'Fee required' : 'Pay unknown';
    const color = kind === 'fee' ? colors.warn : colors.muted;
    body = (
      <>
        <div className={cn('flex items-center gap-1.5 font-display font-medium', jr, size === 'lg' ? 'text-2xl' : size === 'md' ? 'text-base' : 'text-[13px]')} style={{ color }}>
          <Icon className={size === 'lg' ? 'size-6' : 'size-3.5'} aria-hidden />
          {label}
        </div>
        {showOriginal && pay?.raw && <div className={cn('truncate text-faint', sz.orig)}>{pay.raw}</div>}
      </>
    );
  } else if (kind === 'hourly') {
    body = (
      <>
        <div className={cn('flex items-baseline gap-1 whitespace-nowrap', jr)}>
          <span className={cn('font-display font-semibold tracking-tight tabular text-money', sz.main)}>
            {formatINRRange(pay.hourly_inr_min, pay.hourly_inr_max, { compact })}
          </span>
          <span className={cn('text-muted', sz.unit)}>/hr</span>
        </div>
        <div className={cn('flex flex-wrap items-center gap-x-1.5 gap-y-1', jr, sz.orig)}>
          <span className="whitespace-nowrap rounded border border-amber-300/25 bg-amber-300/[.07] px-1 font-medium text-amber-200/90">
            Hourly, hours vary
          </span>
          {showOriginal && <span className="whitespace-nowrap text-faint">{original(pay)}</span>}
        </div>
      </>
    );
  } else if (kind === 'funded') {
    const allowance = pay.benefits.allowance_inr ?? pay.monthly_inr_min;
    const b = pay.benefits;
    const fullyCovered = !!(b.housing && b.meals);
    body = (
      <>
        <div className={cn('flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5', jr)}>
          <span className={cn('whitespace-nowrap font-display font-medium text-ink', size === 'lg' ? 'text-2xl' : size === 'md' ? 'text-base' : 'text-[13px]')}>
            {coveredLabel(pay)}
          </span>
          {allowance != null && (
            <span className="inline-flex items-baseline gap-1 whitespace-nowrap">
              <span className={cn('text-muted', sz.unit)}>+</span>
              <span className={cn('font-display font-semibold tracking-tight tabular text-money', size === 'lg' ? 'text-3xl' : size === 'md' ? 'text-lg' : 'text-[14px]')}>
                {inr(allowance)}
              </span>
              <span className={cn('text-muted', sz.unit)}>/mo</span>
            </span>
          )}
        </div>
        {showOriginal && <div className={cn('truncate text-faint', sz.orig)}>{original(pay)}</div>}
        {showRatio &&
          (fullyCovered ? (
            <div className={cn('font-medium', sz.orig)} style={{ color: colors.ratioGood }}>
              Living costs covered
            </div>
          ) : (
            <RatioBar ratio={pay.ratio} size={size} />
          ))}
      </>
    );
  } else {
    body = (
      <>
        <div className={cn('flex items-baseline gap-1 whitespace-nowrap', jr)}>
          <span
            className={cn('font-display font-semibold tracking-tight tabular text-money', sz.main)}
            style={size === 'lg' ? { filter: 'drop-shadow(0 0 22px rgba(245,196,81,0.25))' } : undefined}
          >
            {formatINRRange(pay.monthly_inr_min, pay.monthly_inr_max, { compact })}
          </span>
          <span className={cn('text-muted', sz.unit)}>/mo</span>
        </div>
        {showOriginal && <div className={cn('truncate text-faint', sz.orig)}>{original(pay)}</div>}
        {showRatio && <RatioBar ratio={pay.ratio} size={size} />}
      </>
    );
  }

  const withTip = tooltip && !!pay;
  const inner = (
    <div className={cn('flex min-w-0 flex-col', sz.gap, align === 'right' && 'items-end text-right', !withTip && className)}>
      {body}
    </div>
  );
  if (!withTip) return inner;
  // `className` sizes the outermost element (the tooltip trigger) so flex/grid sizing works from the parent.
  return (
    <Tooltip content={<PayProvenance pay={pay} />} maxWidth={320} triggerClassName={cn('min-w-0', align === 'right' && 'justify-end', className)}>
      {inner}
    </Tooltip>
  );
}

function RatioBar({ ratio, size }: { ratio: number | null; size: 'sm' | 'md' | 'lg' }) {
  const sz = SIZES[size];
  if (ratio == null) {
    return <div className={cn('text-faint', sz.orig)}>Living cost not set</div>;
  }
  const c = ratioColor(ratio);
  const fill = Math.min(1, ratio / 2.5);
  return (
    <div className="flex items-center gap-2">
      <div className={cn('relative overflow-hidden rounded-full bg-white/[.07]', sz.bar)}>
        <div className="absolute inset-0 origin-left rounded-full" style={{ transform: `scaleX(${fill})`, backgroundColor: c, boxShadow: `0 0 8px ${c}` }} />
        <span className="absolute inset-y-0 left-[40%] w-px bg-white/30" aria-hidden />
        <span className="absolute inset-y-0 left-[60%] w-px bg-white/20" aria-hidden />
      </div>
      <span className={cn('font-medium tabular whitespace-nowrap', sz.orig)} style={{ color: c }}>
        {formatRatio(ratio)} <span className="font-normal text-faint">living cost</span>
      </span>
    </div>
  );
}

/** Provenance block (also usable standalone on the detail page). */
export function PayProvenance({ pay }: { pay: Pay }) {
  const rows: [string, ReactNode][] = [];
  rows.push(['Listed', pay.raw ?? '—']);
  if (pay.monthly_inr_min != null) {
    rows.push(['Monthly', `${formatINRRange(pay.monthly_inr_min, pay.monthly_inr_max)} (mid ${formatINR(pay.monthly_inr_mid)})`]);
  }
  if (pay.hourly_inr_min != null) rows.push(['Hourly', `${formatINRRange(pay.hourly_inr_min, pay.hourly_inr_max)} — hours not stated, never assumed`]);
  if (pay.currency && pay.currency.toUpperCase() !== 'INR' && pay.fx_rate) {
    rows.push(['FX', `1 ${pay.currency} = ₹${pay.fx_rate.toLocaleString('en-IN', { maximumFractionDigits: 4 })}${pay.fx_date ? ` · ${formatDateIST(pay.fx_date)}` : ''}`]);
  }
  const b = pay.benefits ?? {};
  if (b.housing || b.meals || b.travel || b.allowance_inr) {
    rows.push([
      'Covered',
      [b.housing && 'housing', b.meals && 'meals', b.travel && 'travel', b.allowance_inr != null && `allowance ${formatINR(b.allowance_inr)}/mo`]
        .filter(Boolean)
        .join(' · '),
    ]);
  }
  if (pay.living_cost_monthly_inr != null) {
    rows.push(['Living cost', `${formatINR(pay.living_cost_monthly_inr)}/mo`]);
    if (pay.living_cost_basis) rows.push(['Basis', pay.living_cost_basis]);
    if (pay.living_cost_confidence) rows.push(['Confidence', titleCase(pay.living_cost_confidence)]);
  }
  if (pay.ratio != null && pay.monthly_inr_min != null && pay.living_cost_monthly_inr != null) {
    rows.push([
      'Ratio',
      <span key="r" style={{ color: ratioColor(pay.ratio) }}>
        {formatRatio(pay.ratio)} = {formatINR(pay.monthly_inr_min)} ÷ {formatINR(pay.living_cost_monthly_inr)}
      </span>,
    ]);
  }
  return (
    <div className="space-y-1">
      <div className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.16em] text-muted">Pay provenance</div>
      {rows.map(([k, v]) => (
        <div key={k} className="grid grid-cols-[76px_1fr] gap-2">
          <span className="text-faint">{k}</span>
          <span className="text-ink/90">{v}</span>
        </div>
      ))}
    </div>
  );
}
