/**
 * Sources: where the Scout looks. ATS job-board APIs (public read APIs), programme pages (off until Prerit reads
 * their terms) and paste-a-link for anything else, including manual-lane sites HQ never opens. Shows the breaker
 * state per source and the last requests in the fetch log (method counts prove nothing but GETs left the Mac).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Ban, ClipboardPaste, ExternalLink, Globe, Radar, ScrollText, ShieldCheck } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { Badge } from '@/components/Badge';
import { Button } from '@/components/Button';
import { ApiError, api } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatRelative } from '@/lib/format';
import type { Source } from '@/lib/types';
import { Field, TextInput } from '@/pages/Agents/formKit';
import { Toggle } from '../controls';
import { Callout, Code, Section } from '../parts';

const SRC = '#22D3EE';
const KIND_LABEL: Record<string, string> = { greenhouse: 'Greenhouse', lever: 'Lever', ashby: 'Ashby', program_page: 'Programme pages' };

export function SourcesTab() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['sources'], queryFn: api.sources });
  const [filter, setFilter] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Parameters<typeof api.patchSource>[1] }) => api.patchSource(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sources'] }),
    onError: (e) => setErr(e instanceof ApiError ? e.message : String(e)),
  });
  const groups = useMemo(() => {
    const m = new Map<string, Source[]>();
    for (const s of q.data?.items ?? []) {
      if (filter && !`${s.name} ${s.id}`.toLowerCase().includes(filter.toLowerCase())) continue;
      m.set(s.kind, [...(m.get(s.kind) ?? []), s]);
    }
    return [...m.entries()];
  }, [q.data, filter]);
  const enabled = (q.data?.items ?? []).filter((s) => s.enabled).length;

  return (
    <div className="space-y-5">
      <PasteLink />

      <Section
        kicker="Discovery"
        title="Sources"
        icon={Radar}
        color={SRC}
        rows={false}
        right={<Badge color={SRC}>{enabled} on</Badge>}
        description="Job-board APIs are public read APIs published for exactly this use. Programme pages start off: open the terms, mark them allowed, then switch the source on. robots.txt is always honoured, and a source that fails 5 times in a row pauses itself for 6 hours."
      >
        <TextInput placeholder="Filter sources…" value={filter} onChange={(e) => setFilter(e.target.value)} className="mb-3" />
        {err && <Callout icon={Ban} color="#F87171" className="mb-3">{err}</Callout>}
        <div className="space-y-4">
          {groups.map(([kind, items]) => (
            <div key={kind}>
              <div className="mb-1.5 text-[11px] font-medium tracking-[0.14em] text-muted uppercase">{KIND_LABEL[kind] ?? kind}</div>
              <ul className="divide-y divide-white/[.05] overflow-hidden rounded-xl border border-white/[.08]">
                {items.map((s) => (
                  <SourceRow key={s.id} s={s} busy={patch.isPending} onPatch={(body) => { setErr(null); patch.mutate({ id: s.id, body }); }} />
                ))}
              </ul>
            </div>
          ))}
          {q.isLoading && <p className="text-sm text-muted">Loading…</p>}
        </div>
      </Section>

      <Section kicker="Never automated" title="Manual-lane sites" icon={Ban} color="#FBBF24" rows={false}
        description="HQ never fetches, logs into or submits on these domains — paste their postings above and you get a pre-filled pack instead.">
        <div className="flex flex-wrap gap-1.5">
          {(q.data?.manual_lane ?? []).map((d) => (
            <Badge key={d} mono color="#FBBF24">{d}</Badge>
          ))}
        </div>
      </Section>

      <FetchLog />
    </div>
  );
}

function SourceRow({ s, onPatch, busy }: { s: Source; onPatch: (b: { enabled?: boolean; tos_status?: Source['tos_status'] }) => void; busy: boolean }) {
  const tripped = s.disabled_until && new Date(s.disabled_until).getTime() > Date.now();
  const tosColor = s.tos_status === 'allowed' ? '#34D399' : s.tos_status === 'unreviewed' ? '#FBBF24' : '#F87171';
  return (
    <li className="flex flex-wrap items-center gap-3 px-3 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2 text-[13.5px] text-ink">
          <span className="truncate">{s.name}</span>
          <Badge size="xs" color={tosColor} title={s.tos_reviewed_at ? `reviewed ${formatRelative(s.tos_reviewed_at)}` : 'terms not reviewed'}>
            ToS {s.tos_status}
          </Badge>
          {tripped && <Badge size="xs" color="#F87171">paused after errors</Badge>}
          {s.opportunities > 0 && <Badge size="xs" color={SRC}>{s.opportunities} found</Badge>}
        </div>
        <div className="mt-0.5 flex flex-wrap gap-x-3 text-[11.5px] text-faint">
          <span>every {Math.round(s.poll_interval_min / 60)} h</span>
          <span>{s.last_polled_at ? `polled ${formatRelative(s.last_polled_at)}` : 'never polled'}</span>
          {s.consecutive_errors > 0 && <span className="text-rose-300/80">{s.consecutive_errors} errors</span>}
          {s.tos_url && (
            <a href={s.tos_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 text-cyan-300/80 hover:underline">
              terms <ExternalLink className="size-3" />
            </a>
          )}
        </div>
      </div>
      {s.tos_status !== 'allowed' && (
        <Button size="sm" variant="secondary" icon={ShieldCheck} disabled={busy} onClick={() => onPatch({ tos_status: 'allowed' })}>
          I read the terms
        </Button>
      )}
      <Toggle checked={s.enabled} disabled={busy || s.tos_status !== 'allowed'} onChange={(v) => onPatch({ enabled: v })} label={`Enable ${s.name}`} color={SRC} />
    </li>
  );
}

function PasteLink() {
  const nav = useNavigate();
  const [url, setUrl] = useState('');
  const [text, setText] = useState('');
  const [company, setCompany] = useState('');
  const [title, setTitle] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const add = useMutation({
    mutationFn: () => api.addManual({ url, text: text || undefined, company: company || undefined, title: title || undefined }),
    onSuccess: (o) => nav(`/o/${o.id}`),
    onError: (e) => setErr(e instanceof ApiError ? e.message : String(e)),
  });
  return (
    <Section kicker="Anything else" title="Paste a link" icon={ClipboardPaste} color="#F5C451" rows={false}
      description="Found a role somewhere HQ doesn't watch? Paste the link. For LinkedIn, Internshala, Naukri, Wellfound and other manual-lane sites HQ never opens the page — paste the posting text as well.">
      <form
        className="grid gap-3 md:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          setErr(null);
          add.mutate();
        }}
      >
        <Field label="Link" htmlFor="pl-url" className="md:col-span-2">
          <TextInput id="pl-url" type="url" required placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} />
        </Field>
        <Field label="Company (optional)" htmlFor="pl-co">
          <TextInput id="pl-co" value={company} onChange={(e) => setCompany(e.target.value)} />
        </Field>
        <Field label="Role title (optional)" htmlFor="pl-title">
          <TextInput id="pl-title" value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field label="Posting text (required for manual-lane sites)" htmlFor="pl-text" className="md:col-span-2">
          <textarea
            id="pl-text"
            rows={5}
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="w-full rounded-xl border border-white/10 bg-white/[.04] px-3 py-2 text-[13.5px] text-ink placeholder:text-faint focus:border-cyan-300/50 focus:outline-none"
            placeholder="Paste the full job description…"
          />
        </Field>
        <div className="flex items-center gap-3 md:col-span-2">
          <Button type="submit" icon={ClipboardPaste} loading={add.isPending} disabled={!url}>
            Add to pipeline
          </Button>
          {err && <span className="text-[13px] text-rose-300">{err}</span>}
        </div>
      </form>
    </Section>
  );
}

function FetchLog() {
  const q = useQuery({ queryKey: ['fetch-log'], queryFn: () => api.fetchLog({ limit: 40 }), refetchInterval: 30_000 });
  const methods = Object.entries(q.data?.methods ?? {});
  return (
    <Section kicker="Every request" title="Fetch log" icon={ScrollText} color="#94A3B8" rows={false}
      right={
        <div className="flex gap-1.5">
          {methods.map(([m, n]) => (
            <Badge key={m} mono color={m === 'GET' || m === 'HEAD' ? '#34D399' : '#F87171'}>{m} {n}</Badge>
          ))}
        </div>
      }
      description={<>Every outbound request the Scout and Verifier make (and every one refused). Only GETs ever leave this Mac in dry run; see <Code>fetch_log</Code>.</>}>
      <ul className="max-h-80 divide-y divide-white/[.04] overflow-auto rounded-xl border border-white/[.08] font-mono text-[11.5px]">
        {(q.data?.items ?? []).map((r) => (
          <li key={r.id} className="flex items-center gap-2 px-3 py-1.5">
            <span className={cn('w-10 shrink-0', r.blocked_reason ? 'text-rose-300' : 'text-emerald-300')}>{r.method}</span>
            <span className="w-9 shrink-0 text-muted">{r.blocked_reason ? '—' : r.status ?? '…'}</span>
            <Globe className="size-3 shrink-0 text-faint" aria-hidden />
            <span className="min-w-0 flex-1 truncate text-ink/80" title={r.url}>{r.url}</span>
            {r.blocked_reason && <span className="shrink-0 text-rose-300/80">{r.blocked_reason}</span>}
            {r.from_cache ? <span className="shrink-0 text-faint">cache</span> : null}
            <span className="shrink-0 text-faint">{formatRelative(r.ts)}</span>
          </li>
        ))}
        {!q.data?.items.length && <li className="px-3 py-2 text-faint">No requests yet.</li>}
      </ul>
    </Section>
  );
}
