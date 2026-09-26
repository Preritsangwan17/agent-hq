/**
 * Kanban card. Line 1 company (+ SIM tag, "needs you", pulsing working-agent avatar), line 2 pay (gold, the most
 * prominent element), fit ring, title, then deadline countdown + kind / work-mode chips + flag.
 * The card glides between columns with a shared motion `layoutId` when `opp.stage` changes; a working agent tints
 * the border with its accent and shows its live "now" line + progress in a strip (isolated component, so live
 * ticks never re-measure the card layout).
 */
import { motion } from 'motion/react';
import { ArrowRightLeft, Building2, HandHelping, House, Snowflake } from 'lucide-react';
import { memo, type ReactNode } from 'react';
import { Link } from 'react-router';
import { AgentAvatar, Countdown, PayBadge, ProgressBar, SimTag, Tooltip } from '@/components';
import { cn } from '@/lib/cn';
import { flagEmoji } from '@/lib/format';
import { useAgent, useAgentLive } from '@/lib/store';
import type { OppSummary, WorkMode } from '@/lib/types';
import { STAGE_META, withAlpha } from '@/theme/tokens';
import { FitRing } from './FitRing';

export const KIND_SHORT: Record<string, string> = {
  internship: 'Internship',
  research_internship: 'Research',
  job: 'Job',
  part_time: 'Part-time',
  contract: 'Contract',
  freelance: 'Freelance',
  fellowship: 'Fellowship',
  program: 'Program',
};

export const WORK_MODE_META: Record<WorkMode, { label: string; icon: typeof House }> = {
  remote: { label: 'Remote', icon: House },
  onsite: { label: 'On-site', icon: Building2 },
  hybrid: { label: 'Hybrid', icon: ArrowRightLeft },
  unknown: { label: 'Mode ?', icon: Building2 },
};

export function Chip({ children, icon: Icon, color, title }: { children: ReactNode; icon?: typeof House; color?: string; title?: string }) {
  return (
    <span
      title={title}
      className="inline-flex h-[18px] shrink-0 items-center gap-1 rounded-md border border-white/[.08] bg-white/[.03] px-1.5 text-[10.5px] font-medium whitespace-nowrap text-muted"
      style={color ? { color, borderColor: withAlpha(color, 0.3), backgroundColor: withAlpha(color, 0.08) } : undefined}
    >
      {Icon && <Icon className="size-3" aria-hidden />}
      {children}
    </span>
  );
}

export function NeedsPill({ compact }: { compact?: boolean }) {
  return (
    <Tooltip content="Needs you — open Needs Prerit">
      <span className="inline-flex h-[18px] shrink-0 items-center gap-1 rounded-md border border-orange-400/40 bg-orange-400/[.12] px-1.5 text-[10px] font-semibold text-orange-300 shadow-[0_0_12px_-4px_rgba(251,146,60,0.8)]">
        <HandHelping className="size-3" aria-hidden />
        {!compact && 'You'}
      </span>
    </Tooltip>
  );
}

export interface OppCardProps {
  opp: OppSummary;
  /** timestamp of the last stage change seen live (plays a one-shot glow) */
  flashKey?: number;
  /** first appearance while the board is open (entrance animation) */
  isNew?: boolean;
  className?: string;
}

export const OppCard = memo(function OppCard({ opp, flashKey, isNew, className }: OppCardProps) {
  const agent = useAgent(opp.active_agent_id);
  const frozen = opp.stage === 'frozen' || opp.stage === 'skipped';
  const stageColor = STAGE_META[opp.stage]?.color ?? '#8B95A7';
  const accent = agent?.color ?? null;
  const mode = opp.work_mode ? WORK_MODE_META[opp.work_mode] : null;

  return (
    <motion.div
      layoutId={`opp-${opp.id}`}
      layout="position"
      initial={isNew ? { opacity: 0, scale: 0.96, y: -6 } : false}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ layout: { type: 'spring', stiffness: 320, damping: 34 }, default: { duration: 0.28, ease: 'easeOut' } }}
      className={cn('relative', className)}
    >
      <Link
        to={`/o/${opp.id}`}
        className={cn(
          'group relative block overflow-hidden rounded-xl border p-3 transition-[border-color,background-color,transform] duration-200 hover:-translate-y-px focus-visible:outline-offset-0',
          frozen
            ? 'border-dashed border-sky-200/20 bg-sky-200/[.025] hover:border-sky-200/35'
            : 'border-white/[.08] bg-[#0E1524]/70 hover:border-white/20 hover:bg-[#111A2C]/80',
        )}
        style={
          accent
            ? {
                borderColor: withAlpha(accent, 0.42),
                boxShadow: `0 0 0 1px ${withAlpha(accent, 0.12)}, 0 10px 30px -18px ${withAlpha(accent, 0.9)}`,
              }
            : undefined
        }
      >
        {/* stage hairline on the left edge */}
        <span
          aria-hidden
          className="pointer-events-none absolute inset-y-3 left-0 w-[2px] rounded-r-full"
          style={{ backgroundColor: withAlpha(stageColor, frozen ? 0.4 : 0.7), boxShadow: `0 0 8px ${withAlpha(stageColor, 0.6)}` }}
        />
        {flashKey != null && (
          <motion.span
            key={flashKey}
            aria-hidden
            className="pointer-events-none absolute inset-0 rounded-xl"
            style={{ boxShadow: `inset 0 0 0 1px ${withAlpha(stageColor, 0.8)}, inset 0 0 28px -6px ${withAlpha(stageColor, 0.6)}` }}
            initial={{ opacity: 1 }}
            animate={{ opacity: 0 }}
            transition={{ duration: 2.2, ease: 'easeOut' }}
          />
        )}

        <div className="flex min-w-0 items-center gap-1.5">
          {frozen && <Snowflake className="size-3.5 shrink-0 text-sky-200/70" aria-label="Frozen legacy item" />}
          <span className="min-w-0 truncate text-[13px] font-semibold leading-5 text-ink">{opp.company_name}</span>
          <SimTag show={opp.is_simulated} className="shrink-0" />
          <span className="ml-auto flex shrink-0 items-center gap-1.5 pl-1">
            {opp.needs_prerit && <NeedsPill />}
            {opp.active_agent_id && (
              <AgentAvatar id={opp.active_agent_id} size={22} working title={`${agent?.name ?? opp.active_agent_id} is working on this`} />
            )}
          </span>
        </div>

        <div className="mt-1.5 flex items-start justify-between gap-2">
          <PayBadge pay={opp.pay} size="md" compact showOriginal={false} className="min-w-0 flex-1" />
          <FitRing score={opp.fit_score} size={34} className="mt-0.5" />
        </div>

        <p className="mt-2 line-clamp-2 text-[12px] leading-[1.35] text-muted" title={opp.title}>
          {opp.title}
        </p>

        <div className="mt-2.5 flex min-w-0 items-center gap-1.5">
          <Countdown deadline={opp.deadline_at} confidence={opp.deadline_confidence} compact className="shrink-0 text-[11px]" />
          <Chip>{KIND_SHORT[opp.kind] ?? opp.kind}</Chip>
          {mode && opp.work_mode !== 'unknown' && <Chip icon={mode.icon}>{mode.label}</Chip>}
          {opp.stage === 'skipped' && <Chip color="#94A3B8">Skipped</Chip>}
          <Tooltip content={[opp.city, opp.country_iso2].filter(Boolean).join(' · ') || 'Location unknown'} triggerClassName="ml-auto shrink-0">
            <span className="text-[13px] leading-none" aria-label={opp.city ?? 'location'}>
              {flagEmoji(opp.country_iso2)}
            </span>
          </Tooltip>
        </div>

        {opp.active_agent_id && !frozen && <LiveStrip agentId={opp.active_agent_id} oppId={opp.id} color={accent ?? stageColor} />}
      </Link>
    </motion.div>
  );
});

function LiveStrip({ agentId, oppId, color }: { agentId: string; oppId: string; color: string }) {
  const live = useAgentLive(agentId);
  const mine = live && (live.opportunity_id == null || live.opportunity_id === oppId);
  const line = mine ? live?.now_line : null;
  return (
    <div className="-mx-3 -mb-3 mt-2.5 border-t px-3 pb-2 pt-1.5" style={{ borderColor: withAlpha(color, 0.18), backgroundColor: withAlpha(color, 0.05) }}>
      <div className="truncate font-mono text-[10.5px] leading-4" style={{ color: withAlpha(color, 0.95) }}>
        {line ?? 'Working…'}
      </div>
      <ProgressBar className="mt-1" value={mine ? live?.progress ?? null : null} color={color} height={2} />
    </div>
  );
}
