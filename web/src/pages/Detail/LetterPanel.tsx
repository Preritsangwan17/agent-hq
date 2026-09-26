/**
 * The outbound letter, sentence by sentence: each sentence is tinted by its worst fact-check verdict and opens a
 * popover-free inline inspector (citations → fact ids, job quotes J1…, and every layer's verdict with its model).
 * A version strip switches between drafts; lineage lists every model that wrote any version.
 */
import { FileText, GitBranch, ShieldCheck } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Badge, EmptyState, GlassPanel, SectionHeader } from '@/components';
import { cn } from '@/lib/cn';
import { formatRelative } from '@/lib/format';
import type { DocSentence, Document, FactCheckVerdict, OppDetail } from '@/lib/types';

const VERDICT_COLOR: Record<string, string> = {
  pass: '#34D399',
  supported: '#34D399',
  ok: '#34D399',
  fail: '#F87171',
  unsupported: '#F87171',
  contradicted: '#F87171',
  warn: '#FBBF24',
  unclear: '#FBBF24',
  partial: '#FBBF24',
  na: '#8B95A7',
};
const RANK: Record<string, number> = { fail: 3, unsupported: 3, contradicted: 3, warn: 2, unclear: 2, partial: 2, na: 0 };

function worst(checks: FactCheckVerdict[]): string | null {
  if (!checks.length) return null;
  return checks.reduce((w, c) => ((RANK[c.verdict] ?? 1) > (RANK[w] ?? 1) ? c.verdict : w), checks[0].verdict);
}

const LETTER_KINDS = new Set(['cover_letter', 'cold_email', 'research_statement']);

export function LetterPanel({ opp }: { opp: OppDetail }) {
  const letters = useMemo(
    () => opp.documents.filter((d) => LETTER_KINDS.has(d.kind)).sort((a, b) => b.version - a.version),
    [opp.documents],
  );
  const [pick, setPick] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const doc: Document | undefined = letters.find((d) => d.id === pick) ?? letters[0];
  const sentences: DocSentence[] = (doc && opp.document_sentences?.[doc.id]) || [];
  const quotes = Object.fromEntries((opp.job_quotes ?? []).map((q) => [q.id, q.text]));
  const docLevel = sentences.find((s) => s.idx === -1);
  const body = sentences.filter((s) => s.idx >= 0);
  const resume = opp.documents.filter((d) => d.kind === 'resume_pdf').at(-1);

  if (!doc) {
    return (
      <GlassPanel>
        <EmptyState icon={FileText} title="No letter yet" hint="The Writer drafts once the role is verified and scored." />
      </GlassPanel>
    );
  }

  return (
    <GlassPanel padding="lg">
      <SectionHeader
        title={doc.kind === 'cold_email' ? 'Cold email' : 'Cover letter'}
        kicker={`v${doc.version} · ${doc.status}`}
        icon={FileText}
        color="#A78BFA"
        right={
          <div className="flex flex-wrap justify-end gap-1.5">
            {letters.map((d) => (
              <button
                key={d.id}
                type="button"
                onClick={() => {
                  setPick(d.id);
                  setOpen(null);
                }}
                className={cn(
                  'h-7 rounded-lg border px-2 font-mono text-[11px] transition-colors',
                  d.id === doc.id ? 'border-violet-300/50 bg-violet-400/15 text-violet-100' : 'border-white/10 text-muted hover:text-ink',
                )}
                aria-pressed={d.id === doc.id}
              >
                v{d.version}
              </button>
            ))}
          </div>
        }
      />
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[11.5px] text-muted">
        <span>by {doc.author_model ?? doc.author_agent ?? 'unknown'}</span>
        <span>· {formatRelative(doc.created_at)}</span>
        {(doc.lineage?.length ?? 0) > 0 && (
          <span className="inline-flex items-center gap-1" title="Every model that wrote any version of this letter">
            <GitBranch className="size-3" aria-hidden /> lineage: {doc.lineage!.join(', ')}
          </span>
        )}
        {resume?.file_url && (
          <a className="ml-auto text-cyan-300 hover:underline" href={resume.file_url} target="_blank" rel="noreferrer">
            Résumé PDF ↗
          </a>
        )}
      </div>
      {doc.subject && (
        <div className="mt-4 rounded-lg border border-white/[.08] bg-black/20 px-3 py-2 text-sm">
          <span className="text-muted">Subject: </span>
          {doc.subject}
        </div>
      )}

      {body.length === 0 ? (
        <pre className="mt-4 font-sans text-[14px] leading-relaxed whitespace-pre-wrap text-ink/90">{doc.content_text}</pre>
      ) : (
        <div className="mt-4 space-y-3.5 text-[14.5px] leading-[1.75] text-ink/90">
          {paragraphs(doc.content_text ?? '', body).map((para, pi) => (
            <p key={pi} className={cn(para.sentences.length === 0 && 'whitespace-pre-line text-muted')}>
              {para.sentences.length === 0
                ? para.text
                : para.sentences.map((s) => {
                    const w = worst(s.checks);
                    const color = w ? (VERDICT_COLOR[w] ?? '#8B95A7') : null;
                    const isOpen = open === s.idx;
                    const toggle = () => setOpen(isOpen ? null : s.idx);
                    return (
                      <span key={s.id ?? s.idx}>
                        <span
                          role="button"
                          tabIndex={0}
                          onClick={toggle}
                          onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), toggle())}
                          className={cn(
                            'cursor-pointer rounded px-0.5 [box-decoration-break:clone] transition-colors',
                            isOpen ? 'bg-white/[.08]' : 'hover:bg-white/[.05]',
                          )}
                          style={color ? { textDecoration: `underline ${color}66`, textUnderlineOffset: 4, textDecorationThickness: 2 } : undefined}
                          aria-expanded={isOpen}
                        >
                          {s.text}
                        </span>{' '}
                        {isOpen && <SentenceInspector s={s} quotes={quotes} />}
                      </span>
                    );
                  })}
            </p>
          ))}
        </div>
      )}

      {docLevel && docLevel.checks.length > 0 && (
        <div className="mt-5 border-t border-white/[.06] pt-4">
          <div className="mb-2 flex items-center gap-1.5 text-[11px] font-medium tracking-[0.14em] text-muted uppercase">
            <ShieldCheck className="size-3.5" aria-hidden /> Document checks
          </div>
          <ul className="space-y-1.5">
            {docLevel.checks.map((c, i) => (
              <CheckRow key={i} c={c} />
            ))}
          </ul>
        </div>
      )}
    </GlassPanel>
  );
}

/** Split the stored letter into its paragraphs and hand each one the sentences it contains (in order); the
 * sign-off and contact line (added by HQ, not written by a model) come through as plain paragraphs. */
function paragraphs(text: string, sentences: DocSentence[]): { text: string; sentences: DocSentence[] }[] {
  const paras = text.split(/\n\s*\n/).map((t) => t.trim()).filter(Boolean);
  const norm = (x: string) => x.replace(/\s+/g, ' ');
  const out = paras.map((t) => ({ text: t, sentences: [] as DocSentence[] }));
  let p = 0;
  for (const s of sentences) {
    const needle = norm(s.text ?? '');
    let q = p;
    while (q < out.length && !norm(out[q].text).includes(needle)) q++;
    if (q < out.length) p = q;
    (out[p] ?? out[out.length - 1]).sentences.push(s);
  }
  return out.length ? out : [{ text, sentences }];
}

function SentenceInspector({ s, quotes }: { s: DocSentence; quotes: Record<string, string> }) {
  return (
    <span className="my-2 block rounded-xl border border-white/10 bg-[#0B111D]/80 p-3 text-[12.5px] leading-normal" role="note">
      <span className="flex flex-wrap items-center gap-1.5">
        <Badge size="xs" mono>
          {s.kind ?? 'claim'}
        </Badge>
        {s.fact_ids.map((f) => (
          <Badge key={f} size="xs" mono color="#22D3EE" title="Verified fact id">
            {f}
          </Badge>
        ))}
        {s.job_quote_ids.map((q) => (
          <Badge key={q} size="xs" mono color="#F5C451" title={quotes[q] ?? ''}>
            {q}
          </Badge>
        ))}
        {!s.fact_ids.length && !s.job_quote_ids.length && <span className="text-faint">no citations</span>}
      </span>
      {s.job_quote_ids.map((q) =>
        quotes[q] ? (
          <span key={q} className="mt-2 block border-l-2 border-amber-300/40 pl-2 text-muted italic">
            {q}: “{quotes[q]}”
          </span>
        ) : null,
      )}
      {s.checks.length > 0 ? (
        <span className="mt-2 block space-y-1">
          {s.checks.map((c, i) => (
            <CheckRow key={i} c={c} />
          ))}
        </span>
      ) : (
        <span className="mt-2 block text-faint">not checked yet</span>
      )}
    </span>
  );
}

function CheckRow({ c }: { c: FactCheckVerdict }) {
  const color = VERDICT_COLOR[c.verdict] ?? '#8B95A7';
  return (
    <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
      <span className="font-mono text-[10.5px] tracking-wider uppercase" style={{ color }}>
        {c.verdict}
      </span>
      <span className="text-muted">{c.layer}</span>
      {c.checker_model && <span className="font-mono text-[10.5px] text-faint">{c.checker_model}</span>}
      {c.rules.length > 0 && <span className="font-mono text-[10.5px] text-rose-200/80">{c.rules.join(', ')}</span>}
      {c.span && <span className="text-rose-200/90">“{c.span}”</span>}
      {c.explanation && <span className="w-full text-ink/70">{c.explanation}</span>}
    </span>
  );
}
