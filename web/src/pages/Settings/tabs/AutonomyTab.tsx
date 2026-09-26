/** Autonomy & Mode: mode ladder, the go-live checklist, autonomy (auto / approve-first), freeze outbound, kill switch. */
import {
  Check,
  FlaskConical,
  LockKeyhole,
  MonitorSmartphone,
  OctagonPause,
  Play,
  Rocket,
  Send,
  ShieldCheck,
  Snowflake,
  UserCheck,
  Zap,
  type LucideIcon,
} from 'lucide-react';
import { motion } from 'motion/react';
import { useState } from 'react';
import { Badge } from '@/components/Badge';
import { GlassPanel } from '@/components/GlassPanel';
import { HoldButton } from '@/components/HoldButton';
import { SectionHeader } from '@/components/SectionHeader';
import { cn } from '@/lib/cn';
import { formatClockIST, formatRelative } from '@/lib/format';
import { useNow } from '@/lib/hooks';
import { pauseAll, resumeAll, useAgentsList, useHQ, useSettings } from '@/lib/store';
import type { Autonomy, Mode } from '@/lib/types';
import { MODE_META, colors, withAlpha } from '@/theme/tokens';
import { SettingRow, Toggle } from '../controls';
import { Callout, Section } from '../parts';
import { useSaver } from '../saver';
import { GoLiveSection } from './GoLiveSection';

export function AutonomyTab() {
  const s = useSettings();
  const { save, setFreeze } = useSaver();
  return (
    <div className="space-y-5">
      <ModePanel mode={s.mode} />

      <GoLiveSection />

      <Section
        kicker="Approvals"
        title="Autonomy"
        icon={UserCheck}
        color="#A78BFA"
        rows={false}
        description="Whether agents submit on their own once every gate passes, or wait for your tap. Interviews, offers, money and legal threads are always yours either way."
      >
        <AutonomyChoice value={s.autonomy} onChange={(v) => save({ autonomy: v })} />
      </Section>

      <Section kicker="Outbound" title="Sending" icon={Send} color="#93C5FD">
        <SettingRow
          icon={Snowflake}
          color="#93C5FD"
          title="Freeze outbound"
          phase="live"
          htmlFor="freeze-outbound"
          description="Holds every send and submit (email, ATS, replies, follow-ups) while agents keep discovering, drafting and checking. Picked up by the worker within half a second."
          control={
            <Toggle
              id="freeze-outbound"
              checked={!!s.freeze_outbound}
              onChange={(v) => void setFreeze(v)}
              color="#93C5FD"
              size="lg"
            />
          }
        />
      </Section>

      <KillSwitchPanel />
    </div>
  );
}

// ── mode ──────────────────────────────────────────────────────────────

const LADDER: { mode: Mode; icon: LucideIcon; note: string }[] = [
  { mode: 'dry_run', icon: FlaskConical, note: 'Mock mailer and mock ATS only' },
  { mode: 'self_test', icon: MonitorSmartphone, note: 'Real sends, only to your own address' },
  { mode: 'live', icon: Rocket, note: 'Gated applications sent for real' },
];

function ModePanel({ mode }: { mode: Mode }) {
  const meta = MODE_META[mode] ?? MODE_META.dry_run;
  const idx = Math.max(0, LADDER.findIndex((l) => l.mode === mode));
  return (
    <GlassPanel padding="lg" glow={meta.color} accentTop className="overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute -right-24 -top-24 size-72 rounded-full opacity-60"
        style={{ background: `radial-gradient(circle, ${withAlpha(meta.color, 0.16)}, transparent 70%)` }}
      />
      <div className="relative flex flex-col gap-6 xl:flex-row xl:items-center xl:justify-between">
        <div className="min-w-0">
          <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted">Current mode · changes only via the checklist</div>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <span
              className="inline-flex items-center gap-2.5 rounded-2xl border px-4 py-2 font-display text-2xl font-bold tracking-[0.08em] md:text-3xl"
              style={{
                color: meta.color,
                borderColor: withAlpha(meta.color, 0.45),
                backgroundColor: withAlpha(meta.color, 0.08),
                boxShadow: `0 0 40px -10px ${withAlpha(meta.color, 0.7)}, inset 0 0 18px ${withAlpha(meta.color, 0.12)}`,
              }}
            >
              <ShieldCheck className="size-6 md:size-7" aria-hidden />
              {meta.label}
            </span>
            <Badge color="#8B95A7" icon={LockKeyhole} size="md">
              Loopback-only · typed GO LIVE
            </Badge>
          </div>
          <p className="mt-3 max-w-xl text-sm leading-relaxed text-ink/85">{meta.hint}</p>
        </div>

        <ol className="grid min-w-0 grid-cols-3 gap-2 xl:w-[460px]" aria-label="Mode ladder">
          {LADDER.map((l, i) => {
            const m = MODE_META[l.mode];
            const current = i === idx;
            const Icon = l.icon;
            return (
              <li
                key={l.mode}
                className={cn('relative min-w-0 rounded-xl border p-2.5 sm:p-3', current ? '' : 'border-white/[.07] bg-white/[.02]')}
                style={current ? { borderColor: withAlpha(m.color, 0.5), backgroundColor: withAlpha(m.color, 0.08) } : undefined}
              >
                <div className="flex items-center justify-between gap-1">
                  <Icon className="size-4 shrink-0" style={{ color: current ? m.color : colors.faint }} aria-hidden />
                  {current ? (
                    <span className="size-2 rounded-full" style={{ backgroundColor: m.color, boxShadow: `0 0 8px ${m.color}` }} />
                  ) : (
                    <LockKeyhole className="size-3 text-faint" aria-hidden />
                  )}
                </div>
                <div
                  className="mt-2 truncate font-mono text-[10.5px] font-semibold tracking-wider sm:text-[11px]"
                  style={{ color: current ? m.color : colors.muted }}
                >
                  {m.label}
                </div>
                <div className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-faint">{current ? 'Now' : i < idx ? 'Done' : 'Checklist'} · {l.note}</div>
              </li>
            );
          })}
        </ol>
      </div>

      {mode !== 'live' && (
        <Callout icon={LockKeyhole} color="#FBBF24" title="Going live is loopback-only" className="relative mt-5">
          Switching to SELF-TEST or LIVE needs an <b>.env</b> edit, a restart and a typed confirmation from this Mac (127.0.0.1). It is
          never available from the phone or the LAN, and it only unlocks after the checklist below: profile fields confirmed, golden
          fact tests green, at least 5 reviewed dry-run applications, caps set and the Gmail send-scope consent.
        </Callout>
      )}
    </GlassPanel>
  );
}

// ── autonomy ──────────────────────────────────────────────────────────

const AUTONOMY: { value: Autonomy; title: string; icon: LucideIcon; color: string; body: string; badge?: string }[] = [
  {
    value: 'auto',
    title: 'Auto',
    icon: Zap,
    color: '#22D3EE',
    body: 'Agents submit as soon as all four gates pass — eligibility, pay vs living cost, fact-check and quality. You get every alert.',
  },
  {
    value: 'approve_first',
    title: 'Approve first',
    icon: UserCheck,
    color: '#A78BFA',
    body: 'Every application waits in Needs Prerit for a one-tap approval before anything is sent. Drafting and checks keep running.',
    badge: 'Recommended for the first 10 live',
  },
];

function AutonomyChoice({ value, onChange }: { value: Autonomy; onChange: (v: Autonomy) => void }) {
  return (
    <div role="radiogroup" aria-label="Autonomy" className="grid gap-3 md:grid-cols-2">
      {AUTONOMY.map((o) => {
        const on = o.value === value;
        const Icon = o.icon;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(o.value)}
            className={cn(
              'relative flex min-w-0 gap-3 rounded-2xl border p-4 text-left transition-colors',
              on ? '' : 'border-white/[.08] bg-white/[.02] hover:border-white/15 hover:bg-white/[.04]',
            )}
            style={on ? { borderColor: 'transparent' } : undefined}
          >
            {on && (
              <motion.span
                layoutId="autonomy-ring"
                aria-hidden
                className="absolute inset-0 rounded-2xl border"
                style={{ borderColor: withAlpha(o.color, 0.55), backgroundColor: withAlpha(o.color, 0.08), boxShadow: `0 0 36px -14px ${o.color}` }}
                transition={{ type: 'spring', stiffness: 420, damping: 36 }}
              />
            )}
            <span
              className="relative grid size-10 shrink-0 place-items-center rounded-xl border border-white/10 bg-white/[.03]"
              style={{ boxShadow: on ? `0 0 20px -6px ${o.color}` : undefined }}
            >
              <Icon className="size-5" style={{ color: on ? o.color : colors.muted }} aria-hidden />
            </span>
            <span className="relative min-w-0 flex-1">
              <span className="flex flex-wrap items-center gap-2">
                <span className="font-display text-[15px] font-semibold text-ink">{o.title}</span>
                {o.badge && (
                  <Badge color={o.color} size="xs">
                    {o.badge}
                  </Badge>
                )}
              </span>
              <span className="mt-1 block text-[13px] leading-relaxed text-muted">{o.body}</span>
            </span>
            <span
              aria-hidden
              className={cn('relative grid size-5 shrink-0 place-items-center rounded-full border transition-opacity', on ? 'opacity-100' : 'opacity-40')}
              style={{ borderColor: on ? o.color : 'rgba(255,255,255,0.25)', backgroundColor: on ? o.color : 'transparent' }}
            >
              {on && <Check className="size-3 text-[#070B14]" strokeWidth={3} />}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// ── kill switch ───────────────────────────────────────────────────────

function KillSwitchPanel() {
  const paused = useHQ((s) => !!s.settings.global_pause);
  const pausedAt = useHQ((s) => s.pausedAt);
  const reason = useHQ((s) => s.pauseReason);
  const agents = useAgentsList();
  const now = useNow(paused ? 15_000 : null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const working = agents.filter((a) => a.status === 'working').length;
  const enabled = agents.filter((a) => a.enabled).length;

  return (
    <GlassPanel padding="lg" glow={colors.danger} glowStrength={paused ? 0.5 : 0.3} className="overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-70"
        style={{ background: 'radial-gradient(120% 90% at 100% 0%, rgba(239,68,68,0.12), transparent 55%)' }}
      />
      <div className="relative flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0">
          <SectionHeader kicker="Emergency stop" title="Kill switch" icon={OctagonPause} color={colors.danger} />
          <p className="mt-2 max-w-lg text-[13px] leading-relaxed text-muted">
            Stops every agent within about 2 seconds. Running tasks are cancelled cooperatively and requeued; nothing is sent while
            paused. Resuming needs a 1.2 s hold so it can't happen by accident.
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
            {paused ? (
              <Badge color={colors.danger} size="md" icon={OctagonPause}>
                Paused{pausedAt ? ` since ${formatClockIST(pausedAt, false)} IST (${formatRelative(pausedAt, Math.max(now, Date.now()))})` : ''}
              </Badge>
            ) : (
              <Badge color={colors.ok} size="md">
                Running · {working} working of {enabled} enabled
              </Badge>
            )}
            {paused && reason && <span className="text-muted">Reason: {reason}</span>}
          </div>
          {error && <div className="mt-2 text-xs text-red-300">{error}</div>}
        </div>

        <div className="shrink-0">
          {paused ? (
            <HoldButton
              onConfirm={async () => {
                setError(null);
                try {
                  await resumeAll();
                } catch (e) {
                  setError(e instanceof Error ? e.message : 'Resume failed');
                }
              }}
              color={colors.ok}
              holdMs={1200}
              aria-label="Hold to resume all agents"
              holdingLabel={
                <>
                  <Play className="size-5" aria-hidden /> Keep holding…
                </>
              }
              className="h-16 w-full px-8 font-display text-base tracking-[0.08em] md:w-auto"
            >
              <Play className="size-5" aria-hidden />
              HOLD TO RESUME
            </HoldButton>
          ) : (
            <button
              type="button"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setError(null);
                try {
                  await pauseAll('Kill switch (Settings)');
                } catch (e) {
                  setError(e instanceof Error ? e.message : 'Pause failed');
                } finally {
                  setBusy(false);
                }
              }}
              aria-label="Pause all agents"
              className="group relative inline-flex h-16 w-full select-none items-center justify-center gap-3 overflow-hidden rounded-2xl border border-red-400/50 bg-danger px-8 font-display text-base font-bold tracking-[0.1em] text-white shadow-[0_0_0_1px_rgba(239,68,68,0.35),0_12px_44px_-8px_rgba(239,68,68,0.8)] transition-transform duration-150 hover:scale-[1.02] active:scale-[0.98] disabled:opacity-70 md:w-auto"
            >
              <span aria-hidden className="absolute inset-0 bg-[radial-gradient(120%_120%_at_50%_0%,rgba(255,255,255,0.3),transparent_55%)]" />
              <OctagonPause className="relative size-6" aria-hidden />
              <span className="relative">PAUSE ALL AGENTS</span>
            </button>
          )}
        </div>
      </div>
    </GlassPanel>
  );
}
