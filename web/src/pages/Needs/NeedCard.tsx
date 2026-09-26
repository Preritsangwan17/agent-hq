/**
 * One Needs-Prerit item: kind tile, title, est. minutes, due countdown, markdown-ish instructions, answers with
 * copy buttons, files, "Open link", and Done / Snooze / Dismiss. Interview, offer, legal and money kinds get the
 * notify-only alert treatment (gold for offer/money, red for interview/legal).
 */
import { AnimatePresence, motion } from 'motion/react';
import {
  AlarmClock,
  ArrowUpRight,
  BellOff,
  Check,
  ChevronDown,
  Clock,
  ExternalLink,
  FileText,
  Hourglass,
  ShieldAlert,
  X,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { SimTag, Tooltip } from '@/components';
import { api } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatDateTimeIST, formatDuration, formatRelative, toDate } from '@/lib/format';
import { useNow } from '@/lib/hooks';
import { useOpp } from '@/lib/store';
import type { Need } from '@/lib/types';
import { colors, withAlpha } from '@/theme/tokens';
import { CopyButton } from '../Agents/formKit';
import { ALERT_RED, GOLD, kindMeta } from './kinds';
import { Markdownish } from './markdown';

export type NeedAction =
  | { status: 'done'; choice?: string }
  | { status: 'dismissed' }
  | { status: 'snoozed'; hours: number };

interface DecisionOption {
  value: string;
  label: string;
}

function decisionOptions(need: Need): DecisionOption[] {
  const raw = need.payload?.options;
  if (need.kind !== 'decision' || !Array.isArray(raw)) return [];
  return raw.filter((o): o is DecisionOption => !!o && typeof o === 'object' && 'value' in o && 'label' in o);
}

export interface NeedCardProps {
  need: Need;
  onAction: (need: Need, action: NeedAction) => void;
  busy?: boolean;
}

export function NeedCard({ need, onAction, busy }: NeedCardProps) {
  const meta = kindMeta(need.kind);
  const opp = useOpp(need.opportunity_id);
  const Icon = meta.icon;
  const alert = meta.alert;
  const accent = alert === 'gold' ? GOLD : alert === 'red' ? ALERT_RED : meta.color;
  const snoozed = need.status === 'snoozed';
  const options = decisionOptions(need);
  const flagged = need.answers.filter((a) => a.status === 'needs_prerit' || a.status === 'never');

  return (
    <article
      className={cn(
        'glass relative min-w-0 overflow-hidden rounded-2xl',
        alert && 'border-transparent',
      )}
      style={
        {
          '--glow': withAlpha(accent, alert ? 0.5 : 0.22),
          ...(alert
            ? {
                borderColor: withAlpha(accent, 0.45),
                background: `linear-gradient(180deg, ${withAlpha(accent, 0.1)}, rgba(255,255,255,0.03) 38%)`,
              }
            : {}),
        } as React.CSSProperties
      }
      aria-label={`${meta.label}: ${need.title}`}
    >
      <span
        aria-hidden
        className="pointer-events-none absolute inset-x-6 top-0 h-px"
        style={{ background: `linear-gradient(90deg, transparent, ${withAlpha(accent, 0.85)}, transparent)` }}
      />

      {alert && (
        <div
          className="flex items-center gap-2 border-b px-4 py-2 text-[12.5px] font-medium md:px-5"
          style={{ borderColor: withAlpha(accent, 0.25), backgroundColor: withAlpha(accent, 0.1), color: accent }}
        >
          <ShieldAlert className="size-4 shrink-0" aria-hidden />
          <span className="min-w-0">Agents never act on this — it&apos;s yours.</span>
          <span className="ml-auto hidden font-mono text-[10px] tracking-[0.16em] uppercase opacity-80 sm:inline">
            notify-only · outbound locked
          </span>
        </div>
      )}

      <div className="p-4 md:p-5">
        <header className="flex items-start gap-3.5">
          <span
            className="relative grid size-11 shrink-0 place-items-center rounded-xl border"
            style={{
              borderColor: withAlpha(accent, 0.4),
              background: `radial-gradient(circle at 50% 30%, ${withAlpha(accent, 0.28)}, ${withAlpha(accent, 0.05)} 72%)`,
              boxShadow: `0 0 26px -8px ${withAlpha(accent, 0.8)}`,
            }}
          >
            <Icon className="size-5" style={{ color: accent }} aria-hidden />
            {alert && !snoozed && (
              <span className="absolute -inset-px animate-pulse-ring rounded-xl border" style={{ borderColor: withAlpha(accent, 0.6) }} aria-hidden />
            )}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px]">
              <span className="font-mono font-semibold tracking-[0.14em] uppercase" style={{ color: accent }}>
                {meta.label}
              </span>
              {need.est_minutes != null && (
                <span className="inline-flex items-center gap-1 text-muted tabular">
                  <Clock className="size-3" aria-hidden />≈ {formatMinutes(need.est_minutes)}
                </span>
              )}
              <DueChip due={need.due_at} snoozed={snoozed} />
              {opp?.is_simulated && <SimTag />}
            </div>
            <h3 className="mt-1 font-display text-[16.5px] leading-snug font-semibold tracking-tight text-ink md:text-lg">
              {need.title}
            </h3>
            {opp && (
              <Link
                to={`/o/${opp.id}`}
                className="mt-0.5 inline-flex max-w-full items-center gap-1 truncate text-[13px] text-muted transition-colors hover:text-ink"
              >
                <span className="truncate">
                  {opp.company_name} · {opp.title}
                </span>
                <ArrowUpRight className="size-3.5 shrink-0" aria-hidden />
              </Link>
            )}
          </div>
        </header>

        {need.instructions_md && (
          <Markdownish source={need.instructions_md} className="mt-3.5 text-[13.5px] leading-relaxed text-ink/80" />
        )}

        {meta.note && (
          <p className="mt-3 inline-flex items-center gap-1.5 text-xs text-muted">
            <ShieldAlert className="size-3.5" style={{ color: meta.color }} aria-hidden />
            {meta.note}
          </p>
        )}

        {need.answers.length > 0 && (
          <div className="mt-4 overflow-hidden rounded-xl border border-white/[.08] bg-black/20">
            <div className="flex items-center justify-between border-b border-white/[.06] px-3 py-1.5">
              <span className="text-[10.5px] font-medium tracking-[0.14em] text-muted uppercase">Answers</span>
              {need.answers.some((a) => a.copy) && (
                <span className="text-[10.5px] text-faint">tap to copy · paste into the form</span>
              )}
            </div>
            <ul className="divide-y divide-white/[.05]">
              {need.answers.map((a, i) => {
                const flag = a.status === 'needs_prerit' || a.status === 'never';
                return (
                <li
                  key={`${a.label}-${i}`}
                  className={cn('flex items-center gap-3 px-3 py-2', flag && 'bg-amber-400/[.06]')}
                >
                  <div className="min-w-0 flex-1">
                    <div className={cn('text-[11px]', flag ? 'text-amber-300' : 'text-muted')}>
                      {a.label}
                      {a.required && <span className="text-faint"> · required</span>}
                    </div>
                    <div
                      className={cn(
                        'mt-0.5 text-[13.5px] break-words whitespace-pre-line',
                        flag ? 'text-amber-200/90 italic' : a.copy === false ? 'text-faint italic' : 'text-ink',
                        a.label === 'Cover letter' && 'line-clamp-4',
                      )}
                    >
                      {a.value}
                    </div>
                    {flag && a.note && <div className="mt-0.5 text-[11.5px] text-amber-200/70">{a.note}</div>}
                  </div>
                  {a.copy && <CopyButton value={a.value} what={a.label} iconOnly />}
                </li>
                );
              })}
            </ul>
            {flagged.length > 0 && (
              <div className="flex items-center gap-1.5 border-t border-amber-300/20 bg-amber-400/[.07] px-3 py-1.5 text-[11.5px] text-amber-200">
                <ShieldAlert className="size-3.5 shrink-0" aria-hidden />
                {flagged.length} field{flagged.length === 1 ? '' : 's'} left for you — HQ only fills values you confirmed.
              </div>
            )}
          </div>
        )}

        {need.files.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {need.files.map((f, i) => (
              <Tooltip key={f.path} content={<span className="font-mono text-[11px]">{f.path}</span>} maxWidth={420}>
                <span className="inline-flex h-8 max-w-full items-center gap-1.5 rounded-lg border border-white/10 bg-white/[.04] pr-1 pl-2.5 text-xs text-ink">
                  <FileText className="size-3.5 shrink-0 text-muted" aria-hidden />
                  <a
                    href={api.needFileUrl(need.id, i)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="truncate underline-offset-2 hover:underline"
                  >
                    {f.name}
                  </a>
                  <CopyButton value={f.path} what={`path of ${f.name}`} iconOnly className="size-6 !h-6 !w-6 border-transparent bg-transparent" />
                </span>
              </Tooltip>
            ))}
          </div>
        )}

        <footer className="mt-4 flex flex-wrap items-center gap-2 border-t border-white/[.06] pt-4">
          {need.direct_url && (
            <a
              href={need.direct_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex h-9 w-full items-center justify-center gap-1.5 rounded-xl border px-3.5 text-[13px] font-medium transition-colors sm:w-auto"
              style={{ borderColor: withAlpha(accent, 0.4), backgroundColor: withAlpha(accent, 0.1), color: accent }}
            >
              Open link <ExternalLink className="size-3.5" aria-hidden />
            </a>
          )}
          <div className="flex w-full items-center gap-2 sm:ml-auto sm:w-auto">
            <button
              type="button"
              disabled={busy}
              onClick={() => onAction(need, { status: 'dismissed' })}
              aria-label="Dismiss"
              className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-xl px-2.5 text-[13px] font-medium text-muted transition-colors hover:bg-white/[.06] hover:text-ink disabled:opacity-50 sm:px-3"
            >
              <X className="size-4 sm:size-3.5" aria-hidden /> <span className="hidden sm:inline">Dismiss</span>
            </button>
            <SnoozeMenu disabled={busy} onPick={(hours) => onAction(need, { status: 'snoozed', hours })} />
            {options.length > 0 ? (
              options.map((o) => {
                const drop = o.value === 'drop';
                return (
                  <button
                    key={o.value}
                    type="button"
                    disabled={busy}
                    onClick={() => onAction(need, { status: 'done', choice: o.value })}
                    className={cn(
                      'inline-flex h-9 min-w-0 flex-1 items-center justify-center gap-1.5 rounded-xl border px-3.5 text-[13px] font-semibold whitespace-nowrap transition-[background-color,transform] duration-150 active:scale-[0.98] disabled:opacity-50 sm:flex-none',
                      drop
                        ? 'border-rose-300/30 bg-rose-400/10 text-rose-200 hover:bg-rose-400/20'
                        : 'border-emerald-300/50 bg-emerald-400/90 text-[#03140d] shadow-[0_0_22px_-8px_rgba(52,211,153,0.9)] hover:bg-emerald-300',
                    )}
                  >
                    {drop ? <X className="size-4 shrink-0" aria-hidden /> : <Check className="size-4 shrink-0" aria-hidden />}
                    {o.label}
                  </button>
                );
              })
            ) : (
            <button
              type="button"
              disabled={busy}
              onClick={() => onAction(need, { status: 'done' })}
              className="inline-flex h-9 min-w-0 flex-1 items-center justify-center gap-1.5 rounded-xl border border-emerald-300/50 bg-emerald-400/90 px-3.5 text-[13px] font-semibold whitespace-nowrap text-[#03140d] shadow-[0_0_22px_-8px_rgba(52,211,153,0.9)] transition-[background-color,transform] duration-150 hover:bg-emerald-300 active:scale-[0.98] disabled:opacity-50 sm:flex-none"
            >
              <Check className="size-4 shrink-0" aria-hidden /> {meta.done}
            </button>
            )}
          </div>
        </footer>
      </div>
    </article>
  );
}

function formatMinutes(m: number): string {
  if (m < 1) return `${Math.max(1, Math.round(m * 60))} s`;
  if (m < 60) return `${Math.round(m)} min`;
  return `${(m / 60).toFixed(m % 60 ? 1 : 0)} h`;
}

function DueChip({ due, snoozed }: { due: string | null; snoozed: boolean }) {
  const d = toDate(due);
  const left0 = d ? d.getTime() - Date.now() : null;
  const now = useNow(left0 != null && Math.abs(left0) < 3600_000 ? 1000 : 30_000);
  if (!d) return <span className="text-faint">no due date</span>;
  const left = d.getTime() - now;
  const past = left <= 0;
  const color = snoozed ? colors.muted : past ? '#F87171' : left < 24 * 3600_000 ? colors.warn : left < 72 * 3600_000 ? colors.ink : colors.muted;
  const text = snoozed
    ? `back ${formatRelative(due, now)}`
    : past
      ? `overdue ${formatDuration(-left)}`
      : `due in ${formatDuration(left)}`;
  return (
    <Tooltip content={`${snoozed ? 'Snoozed until' : 'Due'} ${formatDateTimeIST(due)} IST`}>
      <span className="inline-flex items-center gap-1 font-medium tabular" style={{ color }}>
        {snoozed ? <BellOff className="size-3" aria-hidden /> : <Hourglass className="size-3" aria-hidden />}
        {text}
      </span>
    </Tooltip>
  );
}

const SNOOZE_OPTIONS = [
  { hours: 1, label: '1 hour' },
  { hours: 4, label: '4 hours' },
  { hours: 24, label: 'Tomorrow' },
  { hours: 72, label: '3 days' },
] as const;

function SnoozeMenu({ onPick, disabled }: { onPick: (hours: number) => void; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('pointerdown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-white/10 bg-white/[.04] px-3 text-[13px] font-medium text-ink transition-colors hover:border-white/20 hover:bg-white/[.08] disabled:opacity-50"
      >
        <AlarmClock className="size-3.5 text-muted" aria-hidden /> Snooze
        <ChevronDown className={cn('size-3.5 text-muted transition-transform', open && 'rotate-180')} aria-hidden />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            role="menu"
            initial={{ opacity: 0, y: 6, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4, scale: 0.98 }}
            transition={{ duration: 0.14 }}
            className="absolute right-0 bottom-full z-30 mb-2 w-40 origin-bottom-right overflow-hidden rounded-xl border border-white/10 bg-[#0B111D]/95 p-1 shadow-[0_18px_40px_-12px_rgba(0,0,0,0.85)] backdrop-blur-xl"
          >
            {SNOOZE_OPTIONS.map((o) => (
              <button
                key={o.hours}
                type="button"
                role="menuitem"
                onClick={() => {
                  setOpen(false);
                  onPick(o.hours);
                }}
                className="flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left text-[13px] text-ink transition-colors hover:bg-white/[.07]"
              >
                {o.label}
                <span className="font-mono text-[10.5px] text-faint">{o.hours}h</span>
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
