/**
 * PAUSE ALL kill switch. Pausing is one click (instant, optimistic). Resuming requires a 1.2 s hold
 * (POST /api/control/resume-all {confirm:"RESUME"}). Always visible, including on mobile.
 */
import { OctagonPause, Play } from 'lucide-react';
import { useState } from 'react';
import { HoldButton } from '@/components/HoldButton';
import { Tooltip } from '@/components/Tooltip';
import { cn } from '@/lib/cn';
import { pauseAll, resumeAll, useIsPaused } from '@/lib/store';
import { colors } from '@/theme/tokens';

export function KillSwitch({ compact }: { compact?: boolean }) {
  const paused = useIsPaused();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (paused) {
    return (
      <Tooltip content={error ?? 'Hold for 1.2 s to resume all agents'} side="bottom">
        <HoldButton
          onConfirm={async () => {
            setError(null);
            try {
              await resumeAll();
            } catch (e) {
              setError(e instanceof Error ? e.message : 'Resume failed');
            }
          }}
          holdMs={1200}
          color={colors.ok}
          aria-label="Hold to resume all agents"
          holdingLabel={
            <>
              <Play className="size-4" aria-hidden /> {compact ? 'Hold…' : 'Keep holding…'}
            </>
          }
          className={cn(compact ? 'h-9 px-3 text-xs' : 'h-11 px-5 text-sm', 'font-display tracking-wide')}
        >
          <Play className="size-4" aria-hidden />
          {compact ? 'RESUME' : 'HOLD TO RESUME'}
        </HoldButton>
      </Tooltip>
    );
  }

  return (
    <Tooltip content={error ?? 'Stops every agent within ~2 s. Running tasks are cancelled and requeued.'} side="bottom">
      <button
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            await pauseAll('Kill switch (UI)');
          } catch (e) {
            setError(e instanceof Error ? e.message : 'Pause failed');
          } finally {
            setBusy(false);
          }
        }}
        className={cn(
          'group relative inline-flex select-none items-center justify-center gap-2 overflow-hidden rounded-xl border border-red-400/50 bg-danger font-display font-bold tracking-[0.08em] text-white',
          'shadow-[0_0_0_1px_rgba(239,68,68,0.35),0_8px_30px_-6px_rgba(239,68,68,0.75)] transition-transform duration-150 hover:scale-[1.03] active:scale-[0.97] disabled:opacity-70',
          compact ? 'h-9 px-3 text-xs' : 'h-11 px-5 text-sm',
        )}
        aria-label="Pause all agents"
      >
        <span
          aria-hidden
          className="absolute inset-0 bg-[radial-gradient(120%_120%_at_50%_0%,rgba(255,255,255,0.28),transparent_55%)] opacity-80"
        />
        <OctagonPause className={cn('relative', compact ? 'size-4' : 'size-[18px]')} aria-hidden />
        <span className="relative">{compact ? 'PAUSE' : 'PAUSE ALL'}</span>
      </button>
    </Tooltip>
  );
}
