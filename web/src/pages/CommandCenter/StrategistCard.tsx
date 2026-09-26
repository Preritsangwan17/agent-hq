/** The Strategist's latest daily report (07:30 IST): summary, auto-applied low-risk actions and open proposals. */
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, CheckCircle2, Compass, Lightbulb } from 'lucide-react';
import { Link } from 'react-router';
import { Badge, EmptyState, GlassPanel, SectionHeader } from '@/components';
import { api } from '@/lib/api';
import { formatDateIST, formatDateTimeIST } from '@/lib/format';
import { Markdownish } from '@/pages/Needs/markdown';

const STRAT = '#E879F9';

export function StrategistCard() {
  const q = useQuery({ queryKey: ['strategy', 'latest'], queryFn: api.strategyLatest, refetchInterval: 5 * 60_000 });
  const report = q.data?.report;
  return (
    <GlassPanel padding="lg" glow={STRAT} glowStrength={0.25}>
      <SectionHeader
        kicker={report ? `Report · ${formatDateIST(report.created_at)}` : 'Daily report'}
        title="Strategist"
        icon={Compass}
        color={STRAT}
        right={
          report ? (
            <Link to="/analytics" className="inline-flex items-center gap-1 text-xs font-medium text-cyan-300 hover:text-cyan-200">
              Analytics <ArrowRight className="size-3.5" aria-hidden />
            </Link>
          ) : undefined
        }
      />
      {!report ? (
        <EmptyState
          compact
          color={STRAT}
          title="No report yet"
          hint={q.data ? `The first review runs ${formatDateTimeIST(q.data.next_run_at)} IST.` : 'Reviews run every morning at 07:30 IST.'}
        />
      ) : (
        <div className="mt-3 space-y-3">
          <div className="line-clamp-6 text-[13px] leading-relaxed text-ink/85">
            <Markdownish source={report.report_md ?? ''} />
          </div>
          {report.applied_actions.length > 0 && (
            <ul className="space-y-1">
              {report.applied_actions.slice(0, 3).map((a, i) => (
                <li key={i} className="flex items-start gap-2 text-[12px] text-muted">
                  <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-emerald-300" aria-hidden />
                  <span className="min-w-0">
                    <span className="font-mono text-ink/85">{a.type}</span> {a.rationale}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {report.proposed_actions.length > 0 && (
            <Badge color={STRAT} icon={Lightbulb} size="md">
              {report.proposed_actions.length} proposal{report.proposed_actions.length === 1 ? '' : 's'} waiting for you
            </Badge>
          )}
        </div>
      )}
    </GlassPanel>
  );
}
