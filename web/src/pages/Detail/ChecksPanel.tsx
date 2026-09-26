/**
 * Why HQ believes what it believes about this role: gate results, eligibility (verdict, confidence, the quoted
 * requirement lines), scam signals, the fit breakdown, and the posting's verified quotes J1… the letter cites.
 */
import { BadgeCheck, CircleAlert, Gauge, Quote, ShieldAlert, ShieldCheck, Sparkles } from 'lucide-react';
import { Badge, GlassPanel, SectionHeader } from '@/components';
import { formatPercent } from '@/lib/format';
import type { EligibilityCheck, OppDetail, ScamCheck } from '@/lib/types';
import { withAlpha } from '@/theme/tokens';

const GATE_LABEL: Record<string, string> = {
  'fact.deterministic': 'Fact rules',
  'fact.local': 'Local fact check',
  'fact.signoff': 'Claude sign-off',
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
  const fit = Object.entries(opp.fit_breakdown ?? {}).filter(([, v]) => typeof v === 'number');
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

      <GlassPanel>
        <SectionHeader title="Fit" icon={Gauge} color="#F5C451" size="sm"
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
