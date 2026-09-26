/**
 * Opportunity display helpers shared by the Pipeline and Detail pages: fit-score ring, kind / work-mode chips,
 * legacy tag, and the "why was this filtered" classification (scam / ineligible / expired).
 * Kept page-local (not in src/components) per the page-agent rules; candidates for promotion to the shared kit.
 */
import {
  Building2,
  CalendarX2,
  CircleSlash,
  Laptop,
  type LucideIcon,
  MapPinned,
  ShieldAlert,
  Shuffle,
  Snowflake,
} from 'lucide-react';
import { cn } from '@/lib/cn';
import type { OppSummary, WorkMode } from '@/lib/types';
import { KIND_LABEL, colors, withAlpha } from '@/theme/tokens';

// ── fit score ─────────────────────────────────────────────────────────

export function fitColor(score: number | null | undefined): string {
  if (score == null) return colors.faint;
  if (score >= 80) return '#34D399';
  if (score >= 65) return '#2DD4BF';
  if (score >= 50) return '#FBBF24';
  return '#8B95A7';
}

export function fitLabel(score: number | null | undefined): string {
  if (score == null) return 'Not scored yet';
  if (score >= 80) return 'Strong fit';
  if (score >= 65) return 'Good fit';
  if (score >= 50) return 'Partial fit';
  return 'Weak fit';
}

export interface FitRingProps {
  score: number | null | undefined;
  size?: number;
  stroke?: number;
  className?: string;
  /** font size of the number (default size × 0.36) */
  fontSize?: number;
}

/** Circular 0–100 gauge. Static SVG (no stroke animation — only transform/opacity animate in this app). */
export function FitRing({ score, size = 30, stroke = 3, className, fontSize }: FitRingProps) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = score == null ? 0 : Math.max(0, Math.min(100, score));
  const color = fitColor(score);
  return (
    <span
      className={cn('relative inline-grid shrink-0 place-items-center', className)}
      style={{ width: size, height: size }}
      role="img"
      aria-label={score == null ? 'Fit not scored yet' : `Fit score ${Math.round(v)} of 100`}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="absolute inset-0 -rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth={stroke} />
        {score == null ? (
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={colors.faint} strokeWidth={stroke * 0.6} strokeDasharray="2 3" />
        ) : (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={c}
            strokeDashoffset={c * (1 - v / 100)}
            style={{ filter: `drop-shadow(0 0 ${Math.max(2, size * 0.08)}px ${withAlpha(color, 0.7)})` }}
          />
        )}
      </svg>
      <span
        className="relative font-display font-semibold tabular leading-none"
        style={{ fontSize: fontSize ?? Math.round(size * 0.36), color: score == null ? colors.faint : colors.ink }}
      >
        {score == null ? '–' : Math.round(v)}
      </span>
    </span>
  );
}

// ── kind / work mode ──────────────────────────────────────────────────

export const WORK_MODE_META: Readonly<Record<WorkMode, { label: string; icon: LucideIcon; color: string }>> = {
  remote: { label: 'Remote', icon: Laptop, color: '#5EEAD4' },
  hybrid: { label: 'Hybrid', icon: Shuffle, color: '#93C5FD' },
  onsite: { label: 'On-site', icon: Building2, color: '#A5B4FC' },
  unknown: { label: 'Mode n/a', icon: MapPinned, color: '#8B95A7' },
};

export function kindLabel(kind: string | null | undefined): string {
  if (!kind) return 'Role';
  return KIND_LABEL[kind] ?? kind.replace(/_/g, ' ');
}

const chipBase = 'inline-flex h-[18px] shrink-0 items-center gap-1 whitespace-nowrap rounded-[5px] border px-1.5 text-[10.5px] font-medium';

export function KindChip({ kind, className }: { kind: string | null | undefined; className?: string }) {
  return <span className={cn(chipBase, 'border-white/10 bg-white/[.04] text-ink/75', className)}>{kindLabel(kind)}</span>;
}

export function WorkModeChip({ mode, className }: { mode: WorkMode | null | undefined; className?: string }) {
  const m = WORK_MODE_META[mode ?? 'unknown'] ?? WORK_MODE_META.unknown;
  const Icon = m.icon;
  return (
    <span
      className={cn(chipBase, className)}
      style={{ color: m.color, borderColor: withAlpha(m.color, 0.22), backgroundColor: withAlpha(m.color, 0.06) }}
    >
      <Icon className="size-3" aria-hidden />
      {m.label}
    </span>
  );
}

export const FROST = '#93C5FD';

/** "LEGACY" tag for rows imported from the old shortlist (historical, never sent by Agent HQ). */
export function LegacyTag({ className, label = 'LEGACY' }: { className?: string; label?: string }) {
  return (
    <span
      className={cn(
        'inline-flex h-[18px] shrink-0 items-center gap-1 rounded-[5px] border px-1.5 font-mono text-[9.5px] font-semibold tracking-[0.14em]',
        className,
      )}
      style={{ color: FROST, borderColor: withAlpha(FROST, 0.35), backgroundColor: withAlpha(FROST, 0.07) }}
      title="Imported from the legacy shortlist — historical, not sent by Agent HQ"
    >
      <Snowflake className="size-2.5" aria-hidden />
      {label}
    </span>
  );
}

export function isLegacy(o: Pick<OppSummary, 'is_simulated' | 'stage' | 'source_label'>): boolean {
  if (o.is_simulated) return false;
  return o.stage === 'frozen' || o.stage === 'skipped' || (o.source_label ?? '').toLowerCase().startsWith('legacy');
}

// ── filtered reasons ──────────────────────────────────────────────────

export type FilterCategory = 'scam' | 'ineligible' | 'expired' | 'other';

export const FILTER_META: Readonly<Record<FilterCategory, { label: string; icon: LucideIcon; color: string }>> = {
  scam: { label: 'Scam', icon: ShieldAlert, color: '#FB923C' },
  ineligible: { label: 'Ineligible', icon: CircleSlash, color: '#FBBF24' },
  expired: { label: 'Expired', icon: CalendarX2, color: '#94A3B8' },
  other: { label: 'Other', icon: CircleSlash, color: '#8B95A7' },
};

export function filterCategory(o: OppSummary): FilterCategory {
  const reason = (o.stage_reason ?? '').toLowerCase();
  if (o.scam_status === 'scam' || o.scam_status === 'suspicious' || /scam|mill|fee/.test(reason)) return 'scam';
  if (o.eligibility_status === 'ineligible' || reason.includes('ineligible')) return 'ineligible';
  if (/deadline|expired|closed/.test(reason)) return 'expired';
  if (o.deadline_at && Date.parse(o.deadline_at) < Date.now()) return 'expired';
  return 'other';
}
