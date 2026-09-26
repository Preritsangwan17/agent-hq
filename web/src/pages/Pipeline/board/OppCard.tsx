/**
 * Kanban card: company, pay (the most prominent line after the company), title, fit ring, kind / work-mode chips,
 * SIM / LEGACY tag, deadline countdown, the working agent (pulsing) with its live "now" line, and Needs Prerit.
 * The motion wrapper carries `layoutId` so a card glides between columns when an `opp.stage` event arrives.
 */
import { HandHelping } from 'lucide-react';
import { motion } from 'motion/react';
import { memo } from 'react';
import { Link } from 'react-router';
import { AgentAvatar, Countdown, PayBadge, SimTag, StageChip } from '@/components';
import { cn } from '@/lib/cn';
import { flagEmoji } from '@/lib/format';
import { useAgent, useAgentLive } from '@/lib/store';
import type { OppSummary, Stage } from '@/lib/types';
import { STAGE_META, withAlpha } from '@/theme/tokens';
import { FILTER_META, FitRing, FROST, KindChip, LegacyTag, WorkModeChip, filterCategory } from './shared';

export type CardVariant = 'board' | 'filtered' | 'legacy' | 'rejected';

export interface StageFlash {
  to: Stage;
  at: number;
}

export interface OppCardProps {
  opp: OppSummary;
  variant?: CardVariant;
  /** recent stage change → one-shot glow ring in the new stage color */
  flash?: StageFlash | null;
  /** first time this card appears on the board → fade/scale in (otherwise the layout transition runs alone) */
  enter?: boolean;
  /** hover tooltips (off on touch layouts) */
  tooltips?: boolean;
  className?: string;
}

const NEEDS_COLOR = '#FB923C';
const SPRING = { type: 'spring', stiffness: 380, damping: 36, mass: 0.9 } as const;

export const OppCard = memo(function OppCard({ opp, variant = 'board', flash, enter, tooltips = true, className }: OppCardProps) {
  return (
    <motion.div
      layout="position"
      layoutId={`opp-${opp.id}`}
      initial={enter ? { opacity: 0, y: 10, scale: 0.97 } : false}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.96, transition: { duration: 0.15 } }}
      transition={SPRING}
      className={cn('relative', className)}
    >
      <CardBody opp={opp} variant={variant} flash={flash} tooltips={tooltips} />
    </motion.div>
  );
});

function CardBody({ opp, variant, flash, tooltips }: { opp: OppSummary; variant: CardVariant; flash?: StageFlash | null; tooltips: boolean }) {
  const agent = useAgent(opp.active_agent_id);
  const activeColor = opp.active_agent_id ? agent?.color ?? '#22D3EE' : null;
  const legacy = variant === 'legacy';
  const nonInr = (opp.pay?.currency ?? 'INR').toUpperCase() !== 'INR';
  const fcat = variant === 'filtered' ? filterCategory(opp) : null;
  const fmeta = fcat ? FILTER_META[fcat] : null;

  return (
    <Link
      to={`/o/${opp.id}`}
      className={cn(
        'group relative block rounded-xl border p-3 outline-none transition-[border-color,background-color,transform] duration-200',
        'shadow-[0_10px_28px_-18px_rgba(0,0,0,0.95)] hover:-translate-y-px focus-visible:ring-2 focus-visible:ring-cyan-300/60',
        legacy
          ? 'border-dashed bg-[linear-gradient(180deg,rgba(147,197,253,0.06),rgba(147,197,253,0.015))] hover:bg-[rgba(147,197,253,0.07)]'
          : 'border-white/[.08] bg-[linear-gradient(180deg,rgba(255,255,255,0.05),rgba(255,255,255,0.018))] hover:border-white/[.16] hover:bg-white/[.05]',
        variant === 'rejected' && 'opacity-70 hover:opacity-100',
      )}
      style={
        activeColor
          ? { borderColor: withAlpha(activeColor, 0.45) }
          : legacy
            ? { borderColor: withAlpha(FROST, 0.28) }
            : undefined
      }
      aria-label={`${opp.company_name} — ${opp.title}`}
    >
      {activeColor && (
        <span
          aria-hidden
          className="pointer-events-none absolute -inset-px animate-breathe rounded-xl"
          style={{ boxShadow: `0 0 0 1px ${withAlpha(activeColor, 0.55)}, 0 0 26px -8px ${activeColor}` }}
        />
      )}
      {flash && (
        <motion.span
          key={flash.at}
          aria-hidden
          className="pointer-events-none absolute -inset-px rounded-xl"
          initial={{ opacity: 1 }}
          animate={{ opacity: 0 }}
          transition={{ duration: 2.6, ease: 'easeOut' }}
          style={{
            boxShadow: `0 0 0 1.5px ${STAGE_META[flash.to]?.color ?? '#22D3EE'}, 0 0 30px -4px ${STAGE_META[flash.to]?.color ?? '#22D3EE'}`,
          }}
        />
      )}

      <div className="flex items-start gap-2.5">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-1.5">
            <span className="shrink-0 text-[13px] leading-none" aria-hidden>
              {flagEmoji(opp.country_iso2)}
            </span>
            <span className="truncate text-[13.5px] font-semibold tracking-tight text-ink">{opp.company_name}</span>
          </div>
          <PayBadge
            pay={opp.pay}
            size="sm"
            compact
            showOriginal={nonInr}
            tooltip={tooltips}
            className="mt-1.5"
          />
        </div>
        <FitRing score={opp.fit_score} size={32} stroke={3} />
      </div>

      <p className="mt-2 line-clamp-2 text-[12px] leading-snug text-muted" title={opp.title}>
        {opp.title}
      </p>

      {fmeta && (
        <div
          className="mt-2 flex items-start gap-1.5 rounded-md border px-2 py-1.5 text-[11px] leading-snug"
          style={{ color: fmeta.color, borderColor: withAlpha(fmeta.color, 0.22), backgroundColor: withAlpha(fmeta.color, 0.06) }}
        >
          <fmeta.icon className="mt-px size-3 shrink-0" aria-hidden />
          <span className="min-w-0">
            <span className="font-semibold">{fmeta.label}</span>
            {opp.stage_reason ? <span className="text-ink/70"> · {opp.stage_reason}</span> : null}
          </span>
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-1">
        <KindChip kind={opp.kind} />
        <WorkModeChip mode={opp.work_mode} />
        {legacy ? <LegacyTag /> : <SimTag show={opp.is_simulated} />}
        {legacy && opp.stage === 'skipped' && <StageChip stage="skipped" dot={false} className="!h-[18px] !text-[10.5px]" />}
      </div>

      <div className="mt-2.5 flex items-center gap-2 border-t border-white/[.06] pt-2">
        <Countdown deadline={opp.deadline_at} confidence={opp.deadline_confidence} compact className="shrink-0 text-[11px]" />
        {opp.city && <span className="min-w-0 truncate text-[11px] text-faint">{opp.city}</span>}
        <span className="ml-auto flex shrink-0 items-center gap-1.5">
          {opp.needs_prerit && (
            <span
              className="inline-flex h-5 items-center gap-1 rounded-full border px-1.5 text-[10.5px] font-semibold"
              style={{ color: NEEDS_COLOR, borderColor: withAlpha(NEEDS_COLOR, 0.4), backgroundColor: withAlpha(NEEDS_COLOR, 0.12) }}
              title="Needs Prerit — something here is waiting on you"
            >
              <HandHelping className="size-3" aria-hidden />
              You
            </span>
          )}
          {opp.active_agent_id && <AgentAvatar id={opp.active_agent_id} size={22} working />}
        </span>
      </div>

      {opp.active_agent_id && <LiveLine agentId={opp.active_agent_id} oppId={opp.id} color={activeColor ?? '#22D3EE'} />}
    </Link>
  );
}

/** The working agent's live "now" line + progress; subscribes on its own so the card doesn't re-render at 4 Hz. */
function LiveLine({ agentId, oppId, color }: { agentId: string; oppId: string; color: string }) {
  const live = useAgentLive(agentId);
  if (!live || (live.opportunity_id && live.opportunity_id !== oppId) || !live.now_line) return null;
  const p = live.progress == null ? null : Math.max(0, Math.min(1, live.progress));
  return (
    <div className="mt-2">
      <div className="truncate font-mono text-[10.5px] leading-tight" style={{ color: withAlpha(color, 0.9) }}>
        {live.now_line}
      </div>
      <div className="relative mt-1 h-[2px] overflow-hidden rounded-full" style={{ backgroundColor: withAlpha(color, 0.14) }}>
        {p == null ? (
          <div className="absolute inset-y-0 left-0 w-1/2 animate-shimmer" style={{ background: `linear-gradient(90deg, transparent, ${color}, transparent)` }} />
        ) : (
          <div
            className="absolute inset-0 origin-left rounded-full transition-transform duration-300 ease-out"
            style={{ transform: `scaleX(${p})`, backgroundColor: color, boxShadow: `0 0 8px ${color}` }}
          />
        )}
      </div>
    </div>
  );
}
