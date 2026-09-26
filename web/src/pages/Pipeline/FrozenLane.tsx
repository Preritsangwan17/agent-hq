/**
 * "Frozen (legacy)" lane under the board: the imported legacy shortlist (stage frozen / skipped). These rows are
 * historical — Agent HQ never sent them — and stay frozen until Prerit confirms what was sent (Needs Prerit).
 */
import { ArrowRight, Snowflake } from 'lucide-react';
import { Link } from 'react-router';
import { GlassPanel } from '@/components';
import type { OppSummary } from '@/lib/types';
import type { CardState } from './Column';
import { OppCard } from './OppCard';

const ICE = '#93C5FD';

export function FrozenLane({ opps, state, needsOpen }: { opps: OppSummary[]; state: CardState; needsOpen: boolean }) {
  const frozen = opps.filter((o) => o.stage === 'frozen').length;
  const skipped = opps.length - frozen;
  return (
    <GlassPanel as="section" padding="none" glow={ICE} glowStrength={0.18} accentTop className="overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.35]"
        style={{
          backgroundImage:
            'repeating-linear-gradient(135deg, rgba(147,197,253,0.05) 0 1px, transparent 1px 14px)',
        }}
      />
      <header className="relative flex flex-wrap items-center gap-x-3 gap-y-2 px-4 pb-3 pt-4 md:px-5">
        <span className="grid size-8 shrink-0 place-items-center rounded-xl border border-sky-200/25 bg-sky-200/[.07] shadow-[0_0_20px_-6px_rgba(147,197,253,0.7)]">
          <Snowflake className="size-4 text-sky-200" aria-hidden />
        </span>
        <div className="min-w-[12rem] flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <h3 className="font-display text-[15px] font-semibold tracking-tight text-ink">Frozen · legacy shortlist</h3>
            <span className="font-display text-sm font-semibold tabular text-sky-200">{opps.length}</span>
            {skipped > 0 && <span className="text-[11px] text-faint">({frozen} frozen · {skipped} skipped)</span>}
          </div>
          <p className="text-[12px] text-muted">
            Historical — <span className="text-sky-100/90">not sent by Agent HQ</span>. Reapplying needs a fresh gated draft.
          </p>
        </div>
        {needsOpen && (
          <Link
            to="/needs"
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-orange-400/35 bg-orange-400/[.08] px-2.5 text-xs font-medium text-orange-200 transition-colors hover:bg-orange-400/[.14]"
          >
            Confirm what you sent <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        )}
      </header>
      {opps.length === 0 ? (
        <p className="relative px-5 pb-5 text-sm text-faint">No legacy items imported.</p>
      ) : (
        <div className="relative flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-4 scrollbar-none md:grid md:grid-cols-[repeat(auto-fill,minmax(250px,1fr))] md:overflow-visible md:px-5 md:pb-5">
          {opps.map((o) => (
            <div key={o.id} className="w-[78vw] max-w-[320px] shrink-0 snap-start md:w-auto md:max-w-none">
              <OppCard opp={o} flashKey={state.flashes[o.id]} isNew={state.isNew(o.id)} />
            </div>
          ))}
        </div>
      )}
    </GlassPanel>
  );
}
