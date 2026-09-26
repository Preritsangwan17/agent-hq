/**
 * Profile & Facts: the personal fields Prerit confirms before go-live (each save marks the field confirmed and is
 * audited without its value), and the verified fact sheet agents are allowed to cite, with evidence links.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  BadgeCheck,
  BookOpenCheck,
  CircleDashed,
  ExternalLink,
  Eye,
  EyeOff,
  FileText,
  LoaderCircle,
  Plus,
  RotateCcw,
  Save,
  Trash2,
  UserRound,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Badge } from '@/components/Badge';
import { Button } from '@/components/Button';
import { EmptyState } from '@/components/EmptyState';
import { ApiError, api } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatRelative } from '@/lib/format';
import type { AvailabilityWindow, ProfileFact, ProfileField, SharePolicy } from '@/lib/types';
import { TextInput } from '@/pages/Agents/formKit';
import { Segmented } from '../controls';
import { Callout, Section } from '../parts';

const PROFILE = '#60A5FA';
const qkProfile = ['profile'] as const;

const SHARE_OPTIONS: { value: SharePolicy; label: string; title: string }[] = [
  { value: 'forms', label: 'Forms', title: 'May be filled into application forms' },
  { value: 'on_request', label: 'On request', title: 'Only when a posting explicitly asks' },
  { value: 'never', label: 'Never', title: 'Never used by agents' },
];

export function ProfileTab() {
  const q = useQuery({ queryKey: qkProfile, queryFn: api.profile });
  if (q.isLoading) {
    return (
      <div className="grid h-40 place-items-center text-muted">
        <LoaderCircle className="size-5 animate-spin" aria-label="Loading profile" />
      </div>
    );
  }
  if (q.isError || !q.data) {
    return <EmptyState icon={UserRound} title="Couldn't load the profile" hint={q.error instanceof Error ? q.error.message : undefined} />;
  }
  const { fields, facts, required_missing } = q.data;
  const required = fields.filter((f) => f.required_for_live);
  const done = required.length - required_missing.length;

  return (
    <div className="space-y-5">
      <Section
        kicker="Needed before go-live"
        title="Your details"
        icon={UserRound}
        color={PROFILE}
        right={
          <Badge color={required_missing.length ? '#FBBF24' : '#34D399'} size="md">
            {done}/{required.length} required confirmed
          </Badge>
        }
        description="Agents only use a value after you save it here. Until then, any question that needs it becomes a Needs Prerit item. The share setting limits where a value may appear; the phone number is never sent to any cloud model."
      >
        {fields.map((f) => (
          <FieldRow key={f.key} field={f} />
        ))}
      </Section>

      <FactsSection facts={facts} />
    </div>
  );
}

// ── fields ────────────────────────────────────────────────────────────

function asText(v: ProfileField['value']): string {
  return typeof v === 'string' ? v : '';
}

function FieldRow({ field }: { field: ProfileField }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<string>(asText(field.value));
  const [windows, setWindows] = useState<AvailabilityWindow[]>(Array.isArray(field.value) ? field.value : []);
  const [share, setShare] = useState<SharePolicy>(field.share_policy);
  useEffect(() => {
    setDraft(asText(field.value));
    setWindows(Array.isArray(field.value) ? field.value : []);
    setShare(field.share_policy);
  }, [field.value, field.share_policy]);

  const value = field.kind === 'windows' ? windows : draft;
  const dirty =
    share !== field.share_policy ||
    (field.kind === 'windows' ? JSON.stringify(windows) !== JSON.stringify(field.value ?? []) : draft !== asText(field.value));

  const m = useMutation({
    mutationFn: () => api.patchProfileField(field.key, field.kind === 'windows' ? windows : draft.trim() || null, share),
    onSuccess: () => qc.invalidateQueries({ queryKey: qkProfile }),
  });
  const err = m.error instanceof ApiError ? m.error.message : m.error ? String(m.error) : null;
  const id = `pf-${field.key}`;

  return (
    <div className="py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={id} className="text-[14px] font-medium text-ink">
          {field.label}
        </label>
        {field.required_for_live && (
          <Badge color="#8B95A7" size="xs">
            required
          </Badge>
        )}
        {field.confirmed ? (
          <Badge color="#34D399" size="xs" icon={BadgeCheck}>
            confirmed {field.updated_at ? formatRelative(field.updated_at) : ''}
          </Badge>
        ) : (
          <Badge color="#FBBF24" size="xs" icon={CircleDashed}>
            not confirmed
          </Badge>
        )}
        {share === 'never' && (
          <Badge color="#5B6577" size="xs" icon={EyeOff}>
            never shared
          </Badge>
        )}
      </div>
      {field.hint && <p className="mt-0.5 text-xs text-faint">{field.hint}</p>}

      <div className="mt-2.5 flex flex-col gap-2.5 xl:flex-row xl:items-start">
        <div className="min-w-0 flex-1">
          {field.kind === 'windows' ? (
            <WindowsEditor value={windows} onChange={setWindows} />
          ) : field.kind === 'choice' ? (
            <Segmented
              aria-label={field.label}
              value={draft || '—'}
              onChange={(v) => setDraft(v === '—' ? '' : v)}
              color={PROFILE}
              options={[{ value: '—', label: '—' }, ...field.choices.map((c) => ({ value: c, label: c[0].toUpperCase() + c.slice(1) }))]}
            />
          ) : (
            <TextInput
              id={id}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              type={field.kind === 'date' ? 'date' : 'text'}
              inputMode={field.kind === 'number' ? 'decimal' : undefined}
              placeholder={field.kind === 'number' ? '—' : 'Not set'}
              autoComplete="off"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && dirty) m.mutate();
              }}
            />
          )}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Segmented aria-label={`Where ${field.label} may be used`} value={share} onChange={setShare} options={SHARE_OPTIONS} color="#8B95A7" size="sm" />
          <Button size="sm" variant={dirty ? 'primary' : 'secondary'} icon={Save} loading={m.isPending} disabled={!dirty && field.confirmed} onClick={() => m.mutate()}>
            {field.confirmed || dirty ? 'Save' : 'Confirm'}
          </Button>
        </div>
      </div>
      {err && <p className="mt-1.5 text-xs text-red-300">{err}</p>}
      {!value && field.confirmed && <p className="mt-1.5 text-xs text-faint">Saving an empty value clears it.</p>}
    </div>
  );
}

function WindowsEditor({ value, onChange }: { value: AvailabilityWindow[]; onChange: (v: AvailabilityWindow[]) => void }) {
  const set = (i: number, patch: Partial<AvailabilityWindow>) => onChange(value.map((w, j) => (j === i ? { ...w, ...patch } : w)));
  return (
    <div className="space-y-2">
      {value.length === 0 && <p className="text-xs text-faint">No windows yet — add the periods you could work.</p>}
      {value.map((w, i) => (
        <div key={i} className="grid grid-cols-2 gap-2 rounded-xl border border-white/[.07] bg-white/[.02] p-2 md:grid-cols-[1fr_1fr_110px_auto_auto]">
          <TextInput type="date" aria-label="From" value={w.from} onChange={(e) => set(i, { from: e.target.value })} />
          <TextInput type="date" aria-label="To" value={w.to} onChange={(e) => set(i, { to: e.target.value })} />
          <TextInput
            aria-label="Hours per week"
            inputMode="numeric"
            value={String(w.hours_per_week)}
            onChange={(e) => set(i, { hours_per_week: Number(e.target.value) || 0 })}
            trailing={<span className="text-[11px] text-faint">h/wk</span>}
          />
          <Segmented
            aria-label="Work mode"
            size="sm"
            value={w.mode}
            onChange={(mode) => set(i, { mode })}
            color={PROFILE}
            options={[
              { value: 'any', label: 'Any' },
              { value: 'remote', label: 'Remote' },
              { value: 'onsite', label: 'On-site' },
            ]}
          />
          <Button size="sm" variant="ghost" icon={Trash2} aria-label="Remove window" onClick={() => onChange(value.filter((_, j) => j !== i))} />
        </div>
      ))}
      <Button
        size="sm"
        variant="secondary"
        icon={Plus}
        onClick={() => onChange([...value, { from: '2027-05-15', to: '2027-07-31', hours_per_week: 40, mode: 'any' }])}
      >
        Add window
      </Button>
    </div>
  );
}

// ── facts ─────────────────────────────────────────────────────────────

const CATEGORY_LABEL: Record<string, string> = {
  contact: 'Contact',
  citizenship: 'Citizenship',
  edu: 'Education & experience',
  preference: 'Preferences',
  project: 'Projects',
  skill: 'Skills',
  not_used: 'Not (yet) used — negated or aspirational wording only',
};

function FactsSection({ facts }: { facts: ProfileFact[] }) {
  const [showRetired, setShowRetired] = useState(false);
  const groups = useMemo(() => {
    const g = new Map<string, ProfileFact[]>();
    for (const f of facts) {
      if (f.status === 'retired' && !showRetired) continue;
      g.set(f.category, [...(g.get(f.category) ?? []), f]);
    }
    return [...g.entries()];
  }, [facts, showRetired]);
  const retired = facts.filter((f) => f.status === 'retired').length;

  return (
    <Section
      kicker="What agents may say"
      title="Verified facts"
      icon={BookOpenCheck}
      color="#34D399"
      rows={false}
      right={
        retired > 0 ? (
          <Button size="sm" variant="ghost" icon={showRetired ? EyeOff : Eye} onClick={() => setShowRetired((v) => !v)}>
            {showRetired ? 'Hide' : 'Show'} {retired} retired
          </Button>
        ) : undefined
      }
      description="Every sentence about you in a letter, form answer or email must cite one of these IDs; the fact gate blocks anything else. Evidence links point at the exact commit. Edit config/facts.yaml to add facts."
    >
      <div className="space-y-5">
        {groups.map(([cat, items]) => (
          <div key={cat}>
            <div className="mb-2 text-[11px] font-medium uppercase tracking-[0.12em] text-muted">{CATEGORY_LABEL[cat] ?? cat}</div>
            <ul className="space-y-1.5">
              {items.map((f) => (
                <FactRow key={f.id} fact={f} />
              ))}
            </ul>
          </div>
        ))}
      </div>
      <Callout icon={FileText} color="#FBBF24" title="Correction on record" className="mt-5">
        The book recommender keeps users with <b>more than 200 ratings</b> (the code uses <code>value_counts() &gt; 200</code>). “200+”
        and “at least 200” are blocked by the fact gate.
      </Callout>
    </Section>
  );
}

function FactRow({ fact }: { fact: ProfileFact }) {
  const qc = useQueryClient();
  const retire = fact.status !== 'retired';
  const m = useMutation({
    mutationFn: () => api.patchFact(fact.id, retire ? 'retired' : 'verified'),
    onSuccess: () => qc.invalidateQueries({ queryKey: qkProfile }),
  });
  return (
    <li className={cn('group flex items-start gap-3 rounded-xl border border-white/[.05] bg-white/[.02] px-3 py-2.5', !retire && 'opacity-55')}>
      <code className="mt-0.5 shrink-0 font-mono text-[10.5px] text-emerald-300/90">{fact.id}</code>
      <div className="min-w-0 flex-1">
        <p className="text-[13px] leading-relaxed text-ink/90">{fact.text}</p>
        {fact.evidence && (
          <p className="mt-0.5 truncate text-[11px] text-faint" title={fact.evidence}>
            Evidence: {fact.evidence}
          </p>
        )}
      </div>
      {fact.status === 'pending' && (
        <Badge color="#FBBF24" size="xs">
          pending
        </Badge>
      )}
      {fact.evidence_url && (
        <a
          href={fact.evidence_url}
          target="_blank"
          rel="noreferrer"
          className="grid size-7 shrink-0 place-items-center rounded-lg text-muted hover:bg-white/[.06] hover:text-ink"
          aria-label={`Open evidence for ${fact.id}`}
        >
          <ExternalLink className="size-3.5" />
        </a>
      )}
      <button
        type="button"
        onClick={() => m.mutate()}
        disabled={m.isPending}
        className="grid size-7 shrink-0 place-items-center rounded-lg text-muted opacity-60 transition-opacity hover:bg-white/[.06] hover:text-ink group-hover:opacity-100 focus-visible:opacity-100"
        aria-label={retire ? `Retire ${fact.id}` : `Restore ${fact.id}`}
        title={retire ? 'Retire (agents stop citing it)' : 'Restore'}
      >
        {retire ? <Trash2 className="size-3.5" /> : <RotateCcw className="size-3.5" />}
      </button>
    </li>
  );
}
