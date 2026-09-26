/** /o/:id — foundation placeholder showing the live summary; a page agent replaces this module. */
import { ArrowLeft, FileSearch, MapPin } from 'lucide-react';
import { Link, useParams } from 'react-router';
import { Countdown, EmptyState, GlassPanel, PayBadge, SimTag, StageChip } from '@/components';
import { flagEmoji } from '@/lib/format';
import { useOpp } from '@/lib/store';
import { KIND_LABEL } from '@/theme/tokens';

export default function Detail() {
  const { id } = useParams();
  const opp = useOpp(id);

  if (!opp) {
    return (
      <GlassPanel>
        <EmptyState icon={FileSearch} title="Opportunity not found" hint="It may have been purged by a sim reset." action={<Link className="text-sm text-cyan-300" to="/pipeline">Back to pipeline</Link>} />
      </GlassPanel>
    );
  }

  return (
    <div className="space-y-5">
      <Link to="/pipeline" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
        <ArrowLeft className="size-4" /> Pipeline
      </Link>
      <GlassPanel padding="lg" glow="#F5C451" accentTop>
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <StageChip stage={opp.stage} size="md" />
              <SimTag show={opp.is_simulated} />
              <span className="text-xs text-muted">{KIND_LABEL[opp.kind] ?? opp.kind}</span>
            </div>
            <h2 className="mt-3 font-display text-2xl font-semibold tracking-tight md:text-3xl">{opp.title}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
              <span className="text-ink/90">{opp.company_name}</span>
              <span className="inline-flex items-center gap-1">
                <MapPin className="size-3.5" /> {flagEmoji(opp.country_iso2)} {opp.city ?? '—'}
              </span>
              <Countdown deadline={opp.deadline_at} confidence={opp.deadline_confidence} />
            </div>
            {opp.stage_reason && <p className="mt-3 text-sm text-muted">{opp.stage_reason}</p>}
          </div>
          <PayBadge pay={opp.pay} size="lg" />
        </div>
      </GlassPanel>
    </div>
  );
}
