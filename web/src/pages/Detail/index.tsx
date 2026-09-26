/** /o/:id — everything HQ knows about one opportunity: header, gates, the letter with per-sentence fact checks,
 * the checks behind every verdict, its applications and Needs items, and the full timeline with runs/escalations. */
import { ArrowLeft, CheckCheck, ExternalLink, FileSearch, History, Inbox, MapPin, Send, Workflow } from 'lucide-react';
import { useState } from 'react';
import { Link, useParams } from 'react-router';
import { Badge, Button, Countdown, EmptyState, GlassPanel, PayBadge, SectionHeader, SimTag, StageChip } from '@/components';
import { api } from '@/lib/api';
import { cn } from '@/lib/cn';
import { flagEmoji, formatDateTimeIST, formatRelative, formatUSD } from '@/lib/format';
import { useOpportunityDetail } from '@/lib/queries';
import { useOpp } from '@/lib/store';
import type { OppDetail } from '@/lib/types';
import { KIND_LABEL, agentColor } from '@/theme/tokens';
import { FitRing } from '../Pipeline/FitRing';
import { ChecksPanel, GatesStrip } from './ChecksPanel';
import { LetterPanel } from './LetterPanel';

type Tab = 'letter' | 'checks' | 'timeline';

export default function Detail() {
  const { id } = useParams();
  const live = useOpp(id);
  const q = useOpportunityDetail(id);
  const [tab, setTab] = useState<Tab>('letter');
  const d = q.data;
  const opp = d ? { ...d, ...(live ?? {}) } : live;

  if (!opp) {
    return (
      <GlassPanel>
        <EmptyState
          icon={FileSearch}
          title={q.isLoading ? 'Loading…' : 'Opportunity not found'}
          hint={q.isLoading ? undefined : 'It may have been purged by a sim reset.'}
          action={<Link className="text-sm text-cyan-300" to="/pipeline">Back to pipeline</Link>}
        />
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
          <div className="flex min-w-0 gap-4">
            <FitRing score={opp.fit_score} size={56} caption className="hidden shrink-0 sm:block" />
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <StageChip stage={opp.stage} size="md" />
                <SimTag show={opp.is_simulated} />
                <span className="text-xs text-muted">{KIND_LABEL[opp.kind] ?? opp.kind}</span>
                {d?.automation === 'manual_lane' && <Badge color="#FBBF24" size="xs">manual lane</Badge>}
              </div>
              <h2 className="mt-3 font-display text-2xl font-semibold tracking-tight md:text-3xl">{opp.title}</h2>
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
                <span className="text-ink/90">{opp.company_name}</span>
                <span className="inline-flex items-center gap-1">
                  <MapPin className="size-3.5" /> {flagEmoji(opp.country_iso2)} {opp.city ?? d?.location_raw ?? '—'}
                  {opp.work_mode ? ` · ${opp.work_mode}` : ''}
                </span>
                <Countdown deadline={opp.deadline_at} confidence={opp.deadline_confidence} />
                {opp.url && (
                  <a href={opp.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-cyan-300 hover:underline">
                    Posting <ExternalLink className="size-3.5" />
                  </a>
                )}
              </div>
              {opp.stage_reason && <p className="mt-3 text-sm text-muted">{opp.stage_reason}</p>}
            </div>
          </div>
          <PayBadge pay={opp.pay} size="lg" />
        </div>
        {d && d.gates.length > 0 && (
          <div className="mt-5 border-t border-white/[.06] pt-4">
            <GatesStrip opp={d} />
          </div>
        )}
      </GlassPanel>

      {d && <Applications opp={d} />}

      <div role="tablist" aria-label="Detail sections" className="flex gap-1 rounded-xl border border-white/[.08] bg-white/[.03] p-1 sm:w-fit">
        {(['letter', 'checks', 'timeline'] as const).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={cn(
              'h-8 flex-1 rounded-lg px-4 text-[13px] font-medium capitalize transition-colors sm:flex-none',
              tab === t ? 'bg-white/[.1] text-ink' : 'text-muted hover:text-ink',
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {!d ? (
        <GlassPanel>
          <EmptyState icon={FileSearch} title={q.isError ? 'Could not load details' : 'Loading details…'} />
        </GlassPanel>
      ) : tab === 'letter' ? (
        <LetterPanel opp={d} />
      ) : tab === 'checks' ? (
        <ChecksPanel opp={d} />
      ) : (
        <Timeline opp={d} />
      )}
    </div>
  );
}

function ReviewButton({ appId, reviewed }: { appId: string; reviewed: boolean }) {
  const [done, setDone] = useState(reviewed);
  const [n, setN] = useState<number | null>(null);
  if (done) return <Badge color="#34D399" size="xs">reviewed{n != null ? ` · ${n}/5` : ''}</Badge>;
  return (
    <Button size="sm" variant="secondary" icon={CheckCheck} onClick={async () => {
      const r = await api.reviewApplication(appId);
      setN(r.reviewed);
      setDone(true);
    }}>
      Mark dry run reviewed
    </Button>
  );
}

function Applications({ opp }: { opp: OppDetail }) {
  const openNeeds = opp.needs.filter((n) => n.status === 'open' || n.status === 'snoozed');
  if (!opp.applications.length && !openNeeds.length) return null;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {opp.applications.map((a) => (
        <GlassPanel key={a.id}>
          <SectionHeader title="Application" icon={Send} color="#F472B6" size="sm" right={<Badge color="#F472B6">{a.status.replace(/_/g, ' ')}</Badge>} />
          <dl className="mt-3 grid grid-cols-[7rem_1fr] gap-y-1.5 text-[13px]">
            <dt className="text-muted">Channel</dt>
            <dd>{a.channel}{a.doc_kind ? ` · ${a.doc_kind.replace('_', ' ')}` : ''}</dd>
            <dt className="text-muted">Mode</dt>
            <dd className="font-mono text-[12px]">{a.mode}</dd>
            {a.submitted_at && (
              <>
                <dt className="text-muted">Submitted</dt>
                <dd>{formatDateTimeIST(a.submitted_at)} IST</dd>
              </>
            )}
            {a.submission_ref && (
              <>
                <dt className="text-muted">Reference</dt>
                <dd className="truncate font-mono text-[12px]">{a.submission_ref}</dd>
              </>
            )}
          </dl>
          {a.mode === 'dry_run' && a.status === 'submitted' && !opp.is_simulated && (
            <div className="mt-3 flex items-center gap-2 border-t border-white/[.06] pt-3 text-[12px] text-muted">
              <ReviewButton appId={a.id} reviewed={!!a.reviewed_at} />
              <span>Counts toward the go-live checklist (5 needed).</span>
            </div>
          )}
        </GlassPanel>
      ))}
      {openNeeds.length > 0 && (
        <GlassPanel>
          <SectionHeader title="Waiting on you" icon={Inbox} color="#F5C451" size="sm" right={<Link to="/needs" className="text-[12px] text-cyan-300">Open Needs →</Link>} />
          <ul className="mt-3 space-y-1.5 text-[13px]">
            {openNeeds.map((n) => (
              <li key={n.id} className="flex items-center gap-2">
                <Badge size="xs" color="#F5C451">{n.kind.replace('_', ' ')}</Badge>
                <span className="truncate">{n.title}</span>
              </li>
            ))}
          </ul>
        </GlassPanel>
      )}
    </div>
  );
}

function Timeline({ opp }: { opp: OppDetail }) {
  const runs = opp.runs ?? [];
  return (
    <div className="grid gap-4 xl:grid-cols-[1.2fr_1fr]">
      <GlassPanel>
        <SectionHeader title="Timeline" icon={History} color="#22D3EE" size="sm" />
        <ol className="mt-3 space-y-2.5">
          {[...opp.timeline].reverse().map((e) => (
            <li key={e.id} className="grid grid-cols-[4.5rem_1fr] gap-3 text-[13px]">
              <time className="pt-px text-[11.5px] text-faint tabular" title={formatDateTimeIST(e.ts)}>{formatRelative(e.ts)}</time>
              <div className="min-w-0">
                {e.agent_id && (
                  <span className="mr-1.5 font-mono text-[11px]" style={{ color: agentColor(e.agent_id) }}>{e.agent_id}</span>
                )}
                <span className={cn(e.level === 'error' ? 'text-rose-300' : e.level === 'warn' ? 'text-amber-200' : 'text-ink/85')}>{e.message}</span>
              </div>
            </li>
          ))}
          {!opp.timeline.length && <li className="text-sm text-faint">Nothing yet.</li>}
        </ol>
      </GlassPanel>
      <GlassPanel>
        <SectionHeader title="Runs" kicker="models, escalations, cost" icon={Workflow} color="#A78BFA" size="sm" />
        <ul className="mt-3 divide-y divide-white/[.05] text-[12.5px]">
          {runs.map((r) => (
            <li key={r.id} className="py-2">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[11px]" style={{ color: agentColor(r.agent_id) }}>{r.capability}</span>
                {r.parent_run_id && <Badge size="xs" color="#94A3B8" title="attempt inside a task (escalation ladder)">attempt</Badge>}
                <span className={cn('ml-auto text-[11px]', r.status === 'succeeded' ? 'text-emerald-300' : r.status === 'failed' ? 'text-rose-300' : 'text-muted')}>
                  {r.status}
                </span>
              </div>
              <div className="mt-0.5 flex flex-wrap gap-x-3 text-[11.5px] text-faint">
                <span className="font-mono">{r.model_id ?? '—'}</span>
                {r.duration_ms != null && <span>{(r.duration_ms / 1000).toFixed(1)} s</span>}
                {r.cost_usd ? <span>{formatUSD(r.cost_usd, 3)}</span> : null}
                <span>{formatRelative(r.started_at)}</span>
              </div>
              {r.error && <div className="mt-0.5 truncate text-[11.5px] text-rose-200/80" title={r.error}>{r.error}</div>}
            </li>
          ))}
          {!runs.length && <li className="py-2 text-sm text-faint">No runs yet.</li>}
        </ul>
      </GlassPanel>
    </div>
  );
}
