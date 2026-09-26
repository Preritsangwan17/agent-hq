/**
 * Top bar: page title (desktop) / logo (mobile), status cluster (SIM, mode, Grok budget, connection) and the
 * PAUSE ALL kill switch, which stays visible at every width. Also exports the paused banner + red vignette.
 */
import { AnimatePresence, motion } from 'motion/react';
import { OctagonPause } from 'lucide-react';
import { useLocation } from 'react-router';
import { cn } from '@/lib/cn';
import { formatClockIST, formatRelative } from '@/lib/format';
import { useIsMobile, useNow } from '@/lib/hooks';
import { useHQ, useIsPaused } from '@/lib/store';
import { KillSwitch } from './KillSwitch';
import { NotificationBell } from './NotificationBell';
import { LogoMark } from './Logo';
import { navFor, titleFor } from './nav';
import { BudgetGauge, ConnectionIndicator, ModeBadge, SimIndicator } from './StatusCluster';

export function Header() {
  const { pathname } = useLocation();
  const mobile = useIsMobile();
  const item = navFor(pathname);
  const title = titleFor(pathname);
  const Icon = item?.icon;

  return (
    <header className="sticky top-0 z-40 border-b border-white/[.06] bg-[#070B14]/70 backdrop-blur-xl">
      <div className="flex h-14 items-center gap-2 px-4 md:h-16 md:gap-4 md:px-6 lg:px-8">
        {mobile ? (
          <div className="flex min-w-0 items-center gap-2">
            <LogoMark size={28} className="shrink-0" />
            <span className="truncate font-display text-[15px] font-semibold tracking-tight">{item?.short ?? title}</span>
          </div>
        ) : (
          <div className="flex min-w-0 items-center gap-3">
            {Icon && (
              <span
                className="grid size-9 shrink-0 place-items-center rounded-xl border border-white/10 bg-white/[.04]"
                style={{ boxShadow: `0 0 24px -8px ${item.color}` }}
              >
                <Icon className="size-[18px]" style={{ color: item.color }} aria-hidden />
              </span>
            )}
            <div className="min-w-0 leading-tight">
              <div className="font-mono text-[9.5px] uppercase tracking-[0.2em] text-faint">Agent HQ</div>
              <div className="truncate font-display text-lg font-semibold tracking-tight">{title}</div>
            </div>
          </div>
        )}

        <div className="ml-auto flex items-center gap-1.5 md:gap-3">
          {!mobile && <SimIndicator />}
          <ModeBadge compact={mobile} />
          {!mobile && <span className="h-6 w-px bg-white/10" aria-hidden />}
          <BudgetGauge compact={mobile} />
          <ConnectionIndicator showLabel={!mobile} />
          <NotificationBell compact={mobile} />
          <KillSwitch compact={mobile} />
        </div>
      </div>
    </header>
  );
}

export function PausedBanner() {
  const paused = useIsPaused();
  const reason = useHQ((s) => s.pauseReason);
  const since = useHQ((s) => s.pausedAt);
  const tick = useNow(paused ? 15_000 : null);
  const now = Math.max(tick, Date.now());
  return (
    <AnimatePresence initial={false}>
      {paused && (
        <motion.div
          key="paused"
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.2 }}
          role="status"
          className="sticky top-14 z-30 md:top-16"
        >
          <div className="relative overflow-hidden border-b border-red-500/30 bg-[linear-gradient(90deg,rgba(239,68,68,0.22),rgba(239,68,68,0.10)_50%,rgba(239,68,68,0.22))] backdrop-blur-xl">
            <div className="flex items-center gap-3 px-4 py-2 text-sm md:px-6 lg:px-8">
              <OctagonPause className="size-4 shrink-0 text-red-300" aria-hidden />
              <span className="font-display font-semibold tracking-[0.08em] text-red-100">ALL AGENTS PAUSED</span>
              <span className={cn('hidden truncate text-red-200/80 sm:inline')}>
                {reason ? `· ${reason}` : ''}
                {since ? ` · since ${formatClockIST(since, false)} (${formatRelative(since, now)})` : ''}
              </span>
              <span className="ml-auto hidden text-xs text-red-200/70 md:inline">Nothing runs or sends until you hold RESUME.</span>
              <span className="ml-auto text-xs text-red-200/70 md:hidden">Hold RESUME to continue</span>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function PausedVignette() {
  const paused = useIsPaused();
  return (
    <AnimatePresence>
      {paused && (
        <motion.div
          key="vignette"
          className="hq-vignette"
          aria-hidden
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.5 }}
        />
      )}
    </AnimatePresence>
  );
}
