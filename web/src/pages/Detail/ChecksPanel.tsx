/**
 * Why HQ believes what it believes about this role: gate results, eligibility (verdict, confidence, the quoted
 * requirement lines), scam signals, the transparent match score (twelve explained factors against the career plan),
 * and the posting's verified quotes J1… the letter cites.
 */
import { BadgeCheck, CircleAlert, Gauge, Quote, Send, ShieldAlert, ShieldCheck, Sparkles, ThumbsDown, ThumbsUp } from 'lucide-react';
import { useState } from 'react';
import { Badge, Button, GlassPanel, SectionHeader } from '@/components';
import { api } from '@/lib/api';
import { formatPercent } from '@/lib/format';
import type { EligibilityCheck, MatchBreakdown, OppDetail, ScamCheck } from '@/lib/types';
import { withAlpha } from '@/theme/tokens';

const GATE_LABEL: Record<string, string> = {
  'fact.deterministic': 'Fact rules',
  'fact.local': 'Local fact check',
  'fact.signoff': 'Final sign-off',
  quality: 'Quality',
};

export function GatesStrip({ opp }: { opp: OppDetail }) {
  const latest = new Map<string, { passed: boolean; details: Record<string, unknown> }>();
  for (const g of opp.gates) latest.set(g.gate, g);
  if (!latest.size) return null;
  return (
    <div className="flex flex-wrap gap-2" aria-label="Gate results">
      {[...latest.entries()].map(([gate, g]) => {
        const c = g.passed ? '#34D399' : '#F87171';
        const note = typeof g.details?.note === 'string' ? g.details.note : typeof g.details?.reason === 'string' ? g.details.reason : '';
        return (
          <span
            key={gate}
            title={note}
            className="inline-flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-[12px] font-medium"
            style={{ borderColor: withAlpha(c, 0.4), backgroundColor: withAlpha(c, 0.1), color: c }}
          >
            {g.passed ? <BadgeCheck className="size-3.5" aria-hidden /> : <CircleAlert className="size-3.5" aria-hidden />}
            {GATE_LABEL[gate] ?? gate}
          </span>
        );
      })}
    </div>
  );
}

function quoteText(q: EligibilityCheck['quotes'][number]): { text: string; met?: boolean | null; req?: string } {
  return typeof q === 'string' ? { text: q } : { text: q.quote, met: q.met, req: q.requirement };
}

function signalText(s: ScamCheck['signals'][number]): string {
  if (typeof s === 'string') return s;
  return [s.label ?? s.id, s.detail, s.quote ? `“${s.quote}”` : null].filter(Boolean).join(' — ');
}

export function ChecksPanel({ opp }: { opp: OppDetail }) {
  const elig = opp.eligibility_checks.at(-1);
  const scam = opp.scam_checks?.at(-1);
  const fit = Object.entries(opp.fit_breakdown ?? {}).filter(([, v]) => typeof v === 'number') as [string, number][];
  const match = isMatch(opp.fit_breakdown) ? opp.fit_breakdown : null;
  const quotes = opp.job_quotes ?? [];
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <GlassPanel>
        <SectionHeader title="Eligibility" icon={ShieldCheck} color="#2DD4BF" size="sm"
          right={elig ? <Badge color={elig.verdict === 'eligible' ? '#34D399' : elig.verdict === 'ineligible' ? '#F87171' : '#FBBF24'}>
            {elig.verdict.replace('_', ' ')}{elig.confidence != null ? ` · ${formatPercent(elig.confidence)}` : ''}
          </Badge> : undefined} />
        {elig ? (
          <>
            <p className="mt-2 text-[12px] text-muted">
              {elig.method}{elig.model_id ? ` · ${elig.model_id}` : ''}
            </p>
            <ul className="mt-3 space-y-2">
              {elig.quotes.slice(0, 6).map((q, i) => {
                const t = quoteText(q);
                return (
                  <li key={i} className="border-l-2 pl-2.5 text-[13px] leading-snug"
                    style={{ borderColor: t.met === false ? '#F87171' : t.met ? '#34D399' : 'rgba(255,255,255,0.15)' }}>
                    <span className="text-ink/85 italic">“{t.text}”</span>
                    {t.req && <span className="ml-1.5 text-[11.5px] text-muted">({t.req})</span>}
                  </li>
                );
              })}
              {!elig.quotes.length && <li className="text-[13px] text-faint">No requirement lines quoted.</li>}
            </ul>
          </>
        ) : (
          <p className="mt-3 text-sm text-faint">Not checked yet.</p>
        )}
      </GlassPanel>

      <GlassPanel>
        <SectionHeader title="Scam & fee check" icon={ShieldAlert} color="#FB7185" size="sm"
          right={<Badge color={opp.scam_status === 'clean' ? '#34D399' : opp.scam_status === 'unchecked' ? undefined : '#F87171'}>{opp.scam_status}</Badge>} />
        {scam && scam.signals.length > 0 ? (
          <ul className="mt-3 space-y-1.5 text-[13px]">
            {scam.signals.map((s, i) => (
              <li key={i} className="text-rose-100/90">• {signalText(s)}</li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-sm text-muted">{scam ? 'No scam or fee signals.' : 'Not checked yet.'}</p>
        )}
      </GlassPanel>

      {match ? (
        <MatchPanel opp={opp} m={match} />
      ) : (
        <GlassPanel>
          <SectionHeader title="Match score" icon={Gauge} color="#F5C451" size="sm"
            right={opp.fit_score != null ? <Badge color="#F5C451" mono>{Math.round(opp.fit_score)}</Badge> : undefined} />
          {fit.length ? (
            <ul className="mt-3 space-y-2">
              {fit.map(([k, v]) => (
                <li key={k} className="grid grid-cols-[7.5rem_1fr_2.5rem] items-center gap-2 text-[12px]">
                  <span className="truncate text-muted">{k.replace(/_/g, ' ')}</span>
                  <span className="h-1.5 overflow-hidden rounded-full bg-white/[.06]">
                    <span className="block h-full rounded-full bg-amber-300/80" style={{ width: `${Math.max(0, Math.min(1, v)) * 100}%` }} />
                  </span>
                  <span className="text-right font-mono text-faint tabular">{v.toFixed(2)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-faint">Scored after verification.</p>
          )}
        </GlassPanel>
      )}

      <GlassPanel>
        <SectionHeader title="Posting quotes" kicker="what the letter may cite" icon={Quote} color="#FBBF24" size="sm" />
        {quotes.length ? (
          <ol className="mt-3 space-y-1.5 text-[13px]">
            {quotes.map((q) => (
              <li key={q.id} className="flex gap-2">
                <span className="w-7 shrink-0 font-mono text-[11px] text-amber-300">{q.id}</span>
                <span className="text-ink/85">{q.text}</span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="mt-3 flex items-center gap-1.5 text-sm text-faint">
            <Sparkles className="size-3.5" aria-hidden /> Extracted when the posting is parsed.
          </p>
        )}
      </GlassPanel>
    </div>
  );
}

function isMatch(b: OppDetail['fit_breakdown']): b is MatchBreakdown {
  return !!b && typeof b === 'object' && (b as MatchBreakdown).version === 2 && Array.isArray((b as MatchBreakdown).factors);
}

const VERDICT: Record<string, { label: string; color: string }> = {
  apply: { label: 'Apply', color: '#34D399' },
  consider: { label: 'Consider', color: '#FBBF24' },
  skip: { label: 'Skip', color: '#F87171' },
};

function scoreColor(v: number): string {
  return v >= 80 ? '#34D399' : v >= 55 ? '#FBBF24' : '#F87171';
}

/** The twelve factors behind the match score, each with its weight, points and the reason. */
function MatchPanel({ opp, m }: { opp: OppDetail; m: MatchBreakdown }) {
  const v = VERDICT[m.verdict] ?? VERDICT.consider;
  const [state, setState] = useState<'idle' | 'busy' | 'queued' | 'error'>('idle');
  const [err, setErr] = useState<string | null>(null);
  const canForce = m.verdict !== 'apply' && opp.stage === 'verified' && !m.simulated;
  const force = async () => {
    setState('busy');
    try {
      await api.applyAnyway(opp.id);
      setState('queued');
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setState('error');
    }
  };
  const region = [m.region?.label, m.region?.tier ? `priority ${m.region.tier}` : null].filter(Boolean).join(' · ');
  return (
    <GlassPanel className="lg:col-span-2" glow="#F5C451" glowStrength={0.18}>
      <SectionHeader
        title="Match score"
        icon={Gauge}
        color="#F5C451"
        size="sm"
        right={
          <span className="flex items-center gap-2">
            <Badge color={v.color}>{v.label}</Badge>
            <Badge color="#F5C451" mono>
              {m.total}/100
            </Badge>
          </span>
        }
      />
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[12px]">
        <Badge size="sm" color={m.track === 'core' ? '#A78BFA' : m.track === 'stepping_stone' ? '#60A5FA' : '#8B95A7'}>{m.track_label}</Badge>
        {region && <Badge size="sm" color="#2DD4BF">{region}</Badge>}
        {m.exception && <Badge size="sm" color="#FBBF24">{m.exception}</Badge>}
        {m.simulated && <Badge size="sm" color="#38BDF8">simulated</Badge>}
        <span className="text-muted">{m.verdict_why}</span>
      </div>
      {m.stepping_stone_why && <p className="mt-1.5 text-[12px] text-muted">Stepping stone: {m.stepping_stone_why}.</p>}
      {(m.highlights.length > 0 || m.concerns.length > 0) && (
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {m.highlights.length > 0 && (
            <ul className="space-y-1 text-[12.5px]">
              {m.highlights.map((h) => (
                <li key={h} className="flex gap-1.5 text-emerald-100/90">
                  <ThumbsUp className="mt-0.5 size-3.5 shrink-0 text-emerald-300" aria-hidden /> {h}
                </li>
              ))}
            </ul>
          )}
          {m.concerns.length > 0 && (
            <ul className="space-y-1 text-[12.5px]">
              {m.concerns.map((c) => (
                <li key={c} className="flex gap-1.5 text-rose-100/90">
                  <ThumbsDown className="mt-0.5 size-3.5 shrink-0 text-rose-300" aria-hidden /> {c}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-[12.5px]">
          <thead className="text-[10.5px] uppercase tracking-wider text-faint">
            <tr>
              <th className="py-1.5 font-medium">Factor</th>
              <th className="w-40 py-1.5 font-medium">Score</th>
              <th className="py-1.5 pl-3 text-right font-medium">Weight</th>
              <th className="py-1.5 pl-3 text-right font-medium">Points</th>
              <th className="py-1.5 pl-4 font-medium">Why</th>
            </tr>
          </thead>
          <tbody>
            {m.factors.map((f) => (
              <tr key={f.key} className="border-t border-white/[.05] align-top">
                <td className="py-2 pr-3 text-ink/90">{f.label}</td>
                <td className="py-2">
                  <span className="flex items-center gap-2">
                    <span className="h-1.5 w-24 overflow-hidden rounded-full bg-white/[.06]">
                      <span className="block h-full rounded-full" style={{ width: `${f.score}%`, backgroundColor: scoreColor(f.score) }} />
                    </span>
                    <span className="font-mono text-ink/85 tabular">{f.score}</span>
                  </span>
                </td>
                <td className="py-2 pl-3 text-right font-mono text-muted tabular">{Math.round(f.weight)}%</td>
                <td className="py-2 pl-3 text-right font-mono text-ink tabular">{f.points.toFixed(1)}</td>
                <td className="py-2 pl-4 text-muted">{f.why}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {(m.skills_matched.length > 0 || m.skill_gaps.length > 0) && (
        <p className="mt-3 text-[12px] text-muted">
          {m.skills_matched.length > 0 && <>Your skills it names: <span className="text-ink/85">{m.skills_matched.join(', ')}</span>. </>}
          {m.skill_gaps.length > 0 && <>Not used yet: <span className="text-ink/85">{m.skill_gaps.join(', ')}</span> (lowers the score, never blocks).</>}
        </p>
      )}
      {canForce && (
        <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-white/[.06] pt-3">
          <Button size="sm" icon={Send} loading={state === 'busy'} disabled={state === 'queued'} onClick={() => void force()}>
            {state === 'queued' ? 'Queued — drafting next' : 'Apply anyway'}
          </Button>
          <span className="text-xs text-muted">Parked below your draft threshold. Every safety gate still runs.</span>
          {err && <span className="text-xs text-red-300">{err}</span>}
        </div>
      )}
    </GlassPanel>
  );
}
