import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Building2, CalendarDays, CheckCircle2, Circle, ExternalLink, History, Mail, ShieldCheck, ShieldAlert } from 'lucide-react';
import { Link } from 'react-router';
import { Badge, Button, EmptyState, GlassPanel, SectionHeader } from '@/components';
import { api } from '@/lib/api';
import { formatDateTimeIST } from '@/lib/format';
import type { CareerDossier } from '@/lib/types';

const FIELD_LABELS: Record<string, string> = {
  interview_date: 'Interview date', interview_time: 'Interview time', interview_link: 'Interview link',
  assessment_deadline: 'Assessment deadline', assessment_link: 'Assessment link',
  salary_or_stipend: 'Salary / stipend', location: 'Reporting location', work_mode: 'Work mode',
  reporting_location: 'Reporting location', employee_portal: 'Employee / intern portal',
  onboarding_link: 'Onboarding link', orientation_link: 'Orientation link',
  start_date: 'Start date', joining_date: 'Joining date', reporting_time: 'Reporting time',
  reporting_manager: 'Reporting manager', offer_deadline: 'Offer deadline', documents_required: 'Documents required',
  background_verification: 'Background verification', hr_contact: 'HR contact', orientation: 'Orientation',
  equipment: 'Laptop / equipment', travel_or_accommodation: 'Travel / accommodation',
};

function Source({ dossier, messageId }: { dossier: CareerDossier; messageId: string }) {
  const m = dossier.messages.find((x) => x.id === messageId);
  return m ? <Link to={`/inbox?thread=${encodeURIComponent(m.thread_id)}`} className="text-cyan-300 hover:underline">Source email →</Link>
    : <span className="text-faint">Source email unavailable</span>;
}

function Fact({ label, value }: { label: string; value?: string | null }) {
  return <div className="min-w-0 rounded-xl border border-white/[.07] bg-white/[.025] px-3 py-2">
    <dt className="text-[11px] uppercase tracking-wider text-faint">{label}</dt>
    <dd className="mt-1 break-words text-[13px] text-ink">{value || 'Not provided'}</dd>
  </div>;
}

export function CareerPanel({ opportunityId }: { opportunityId: string }) {
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState('');
  const [progressError, setProgressError] = useState<string | null>(null);
  const [checklistError, setChecklistError] = useState<string | null>(null);
  const [progressBusy, setProgressBusy] = useState(false);
  const q = useQuery({ queryKey: ['career', opportunityId], queryFn: () => api.careerDossier(opportunityId), refetchInterval: 30_000 });
  const d = q.data;
  if (!d) return <GlassPanel><EmptyState icon={Building2} title={q.isError ? 'Company details unavailable' : 'Loading company details…'} /></GlassPanel>;
  const suspicious = d.verification === 'Potentially Suspicious';
  const color = suspicious ? '#F87171' : d.verification === 'Verified Company' ? '#34D399' : '#FBBF24';
  const lastInbound = [...d.messages].reverse().find((m) => m.direction === 'inbound');
  const progressAction = d.communication_stage === 'Offer' ? 'accepted'
    : d.onboarding_mode && d.communication_stage !== 'Joined' ? 'joined' : null;
  const progressPhrase = progressAction === 'accepted' ? 'I ACCEPTED' : 'I JOINED';
  return <div className="space-y-4">
    {d.selected && <GlassPanel padding="lg" glow="#34D399" accentTop>
      <div className="text-[11px] font-bold tracking-[0.18em] text-emerald-300 uppercase">Selected / Offer received</div>
      <h3 className="mt-1 font-display text-xl font-semibold">{d.company.name} · {d.company.title}</h3>
      <p className="mt-2 text-[13px] text-muted">
        {d.onboarding_mode ? 'Joining / Onboarding Mode is active.' : 'Review the offer and its source email before making a decision.'}
      </p>
      {d.communication_stage === 'Accepted' && !d.acceptance_company_confirmed &&
        <p className="mt-2 text-[12px] text-amber-200">Acceptance is recorded by you. Company confirmation has not been detected in email.</p>}
      {progressAction && d.verification !== 'Potentially Suspicious' && <div className="mt-4 rounded-xl border border-white/10 bg-white/[.03] p-3">
        <p className="text-[12.5px] text-muted">Already {progressAction === 'accepted' ? 'accepted the offer outside HQ' : 'completed your first day'}?
          Record it here for tracking. This does not send an email or claim company confirmation.</p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input value={confirm} onChange={(e) => setConfirm(e.target.value)} aria-label={`Type ${progressPhrase}`}
            placeholder={progressPhrase} className="h-9 rounded-lg border border-white/10 bg-black/25 px-3 font-mono text-[12px] text-ink" />
          <Button size="sm" variant="secondary" disabled={confirm !== progressPhrase} loading={progressBusy}
            onClick={async () => { setProgressBusy(true); setProgressError(null);
              try { await api.recordCareerProgress(opportunityId, progressAction, confirm); setConfirm('');
                await qc.invalidateQueries({ queryKey: ['career', opportunityId] }); }
              catch (e) { setProgressError(e instanceof Error ? e.message : String(e)); }
              finally { setProgressBusy(false); } }}>
            Record {progressAction === 'accepted' ? 'acceptance' : 'joined'}
          </Button>
        </div>
        {progressError && <p className="mt-2 text-[12px] text-red-300">{progressError}</p>}
      </div>}
    </GlassPanel>}

    <GlassPanel>
      <SectionHeader title="Company and communication" icon={Building2} color="#60A5FA" size="sm"
        right={<Badge color={color} icon={suspicious ? ShieldAlert : ShieldCheck}>{d.verification}</Badge>} />
      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <Fact label="Company" value={d.company.name} /><Fact label="Role" value={d.company.title} />
        <Fact label="Job type" value={d.company.kind} /><Fact label="Location" value={d.company.location || d.company.city} />
        <Fact label="Country" value={d.company.country} /><Fact label="Work mode" value={d.company.work_mode} />
        <Fact label="Published pay" value={d.company.pay} /><Fact label="Application source" value={d.company.application_source} />
        <Fact label="Application date" value={d.application?.submitted_at ? formatDateTimeIST(d.application.submitted_at) : null} />
        <Fact label="Recruiter" value={d.recruiter.name} /><Fact label="Recruiter email" value={d.recruiter.email} />
        <Fact label="Current stage" value={d.communication_stage} />
        <Fact label="Last company communication" value={d.last_company_communication ? formatDateTimeIST(d.last_company_communication) : null} />
        <Fact label="Next action from email" value={d.next_expected_action} />
      </div>
      <div className="mt-3 flex flex-wrap gap-3 text-[12px] text-cyan-300">
        {d.company.website?.startsWith('https://') && <a href={d.company.website} target="_blank" rel="noopener noreferrer">Recorded company domain <ExternalLink className="inline size-3" /></a>}
        {d.company.posting_url?.startsWith('https://') && <a href={d.company.posting_url} target="_blank" rel="noopener noreferrer">Job posting <ExternalLink className="inline size-3" /></a>}
      </div>
      {d.company.description && <p className="mt-3 whitespace-pre-wrap text-[13px] text-muted">{d.company.description}</p>}
      {d.company.notes && <p className="mt-2 text-[12px] text-amber-200">Notes (unverified): {d.company.notes}</p>}
      <div className={`mt-4 rounded-xl border px-3 py-2.5 text-[12.5px] ${suspicious ? 'border-red-400/30 bg-red-400/[.08]' : 'border-white/10 bg-white/[.03]'}`}>
        <div className="font-medium text-ink">Why this verification result</div>
        <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted">
          {d.verification_reasons.length ? d.verification_reasons.map((r, i) => <li key={i}>{r}</li>)
            : <li>No company email has been assessed yet.</li>}
        </ul>
        {suspicious && <p className="mt-2 text-red-200">Automatic replies are blocked. Review the sender and links independently.</p>}
      </div>
      {!!d.verification_sources.length && <div className="mt-3 text-[12px] text-muted">
        Public and email sources: {d.verification_sources.map((s, i) => <span key={`${s.url}-${i}`} className="mr-2 inline-block">
          {s.checked && s.url.startsWith('https://')
            ? <a href={s.url} target="_blank" rel="noopener noreferrer" className="break-all text-cyan-300 hover:underline">{s.url}</a>
            : <span className="break-all">{s.url}</span>}
          <span className="ml-1 text-faint">{s.checked ? 'posting checked' : 'unverified link'}</span>
        </span>)}
      </div>}
    </GlassPanel>

    {(d.selected || Object.keys(d.offer_details).length > 0) && <GlassPanel>
      <SectionHeader title={d.selected ? 'Offer and joining details' : 'Important dates and details'} icon={CalendarDays} color="#34D399" size="sm" />
      <p className="mt-2 text-[12px] text-muted">Each detail below comes from a source email. A verified sender does not independently verify a link or offer term. Check the original before acting.</p>
      <dl className="mt-3 grid gap-2 sm:grid-cols-2">
        {Object.entries(d.offer_details).map(([key, fact]) => <div key={key} className="rounded-xl border border-white/[.08] bg-white/[.025] p-3">
          <dt className="text-[11px] uppercase tracking-wider text-faint">{FIELD_LABELS[key] ?? key.replace(/_/g, ' ')}</dt>
          <dd className="mt-1 whitespace-pre-wrap break-words text-[13px] text-ink">{fact.value}</dd>
          <div className="mt-2 flex items-center gap-2 text-[11px]"><Badge size="xs" color={fact.official ? '#34D399' : '#FBBF24'}>
            {fact.official ? 'Verified source' : 'Needs review'}</Badge><Source dossier={d} messageId={fact.source_message_id} /></div>
          {!!fact.conflicts?.length && <div className="mt-3 rounded-lg border border-amber-300/30 bg-amber-300/[.08] p-2 text-[12px] text-amber-100">
            <div className="font-semibold">Conflicting company email details — verify before acting</div>
            <div className="mt-1">Earlier: {fact.value} · <Source dossier={d} messageId={fact.source_message_id} /></div>
            {fact.conflicts.map((other, i) => <div key={`${other.source_message_id}-${i}`} className="mt-1 break-words">
              Later: {other.value} · <Source dossier={d} messageId={other.source_message_id} />
            </div>)}
          </div>}
        </div>)}
        {!Object.keys(d.offer_details).length && <p className="text-[13px] text-muted">The email did not provide labeled joining details. Open the original message for the complete offer.</p>}
      </dl>
    </GlassPanel>}

    {d.checklist.length > 0 && <GlassPanel>
      <SectionHeader title="What I need to do next" icon={CheckCircle2} color="#F5C451" size="sm" />
      <p className="mt-2 text-[12px] text-muted">Tasks appear only when the source email mentions them. Marking one done records your progress.</p>
      {checklistError && <p role="alert" className="mt-2 text-[12px] text-red-300">{checklistError}</p>}
      <ul className="mt-3 space-y-2">
        {d.checklist.map((item) => <li key={item.id} className="flex gap-3 rounded-xl border border-white/[.07] bg-white/[.025] p-3">
          <button type="button" aria-label={`${item.status === 'done' ? 'Mark pending' : 'Mark done'}: ${item.title}`}
            className="mt-0.5 shrink-0 text-cyan-300 disabled:opacity-40" disabled={q.isFetching}
            onClick={async () => { setChecklistError(null);
              try { await api.updateCareerItem(opportunityId, item.id, item.status === 'done' ? 'pending' : 'done');
                await qc.invalidateQueries({ queryKey: ['career', opportunityId] }); }
              catch (e) { setChecklistError(e instanceof Error ? e.message : String(e)); } }}>
            {item.status === 'done' ? <CheckCircle2 className="size-5" /> : <Circle className="size-5" />}
          </button>
          <div className="min-w-0 flex-1">
            <div className={`text-[13px] ${item.status === 'done' ? 'text-muted line-through' : 'text-ink'}`}>{item.title}</div>
            {item.due_text && <div className="text-[12px] text-amber-200">Deadline in email: {item.due_text}</div>}
            <div className="mt-1 text-[11px]"><Source dossier={d} messageId={item.source_message_id} /></div>
          </div>
        </li>)}
      </ul>
    </GlassPanel>}

    <div className="grid gap-4 xl:grid-cols-2">
      <GlassPanel>
        <SectionHeader title="Official communication timeline" icon={History} color="#A78BFA" size="sm" />
        <ol className="mt-3 space-y-3">
          {d.timeline.map((event) => <li key={event.id} className="border-l border-violet-300/30 pl-3 text-[12.5px]">
            <div className="font-medium text-ink">{event.stage}</div>
            <div className="text-muted">{formatDateTimeIST(event.occurred_at)} · {event.source.replace(/_/g, ' ')}</div>
            {event.model_id && <div className="text-faint">AI: {event.model_id}</div>}
            {event.detail && <div className="text-faint">{event.detail}</div>}
            {event.message_id && <div className="mt-0.5"><Source dossier={d} messageId={event.message_id} /></div>}
          </li>)}
          {!d.timeline.length && <li className="text-[13px] text-muted">No application communication recorded yet.</li>}
        </ol>
      </GlassPanel>
      <GlassPanel>
        <SectionHeader title="Email conversation" icon={Mail} color="#22D3EE" size="sm" />
        {lastInbound && <p className="mt-2 text-[12px] text-muted">Latest company message: {formatDateTimeIST(lastInbound.date || '')}</p>}
        <div className="mt-3 max-h-[42rem] space-y-3 overflow-y-auto">
          {d.messages.map((m) => <article key={m.id} className="rounded-xl border border-white/[.08] bg-white/[.025] p-3">
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted">
              <Badge size="xs" color={m.direction === 'outbound' ? '#22D3EE' : '#A78BFA'}>{m.direction === 'outbound' ? 'Sent' : 'Received'}</Badge>
              <span>{m.from_addr} → {m.to_addr}</span><span className="ml-auto">{m.date ? formatDateTimeIST(m.date) : 'Date unknown'}</span>
            </div>
            <div className="mt-1 text-[12.5px] font-medium text-ink">{m.subject}</div>
            <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words font-sans text-[12.5px] text-muted">{m.body}</pre>
            <Link to={`/inbox?thread=${encodeURIComponent(m.thread_id)}`} className="mt-2 inline-block text-[11px] text-cyan-300 hover:underline">Open thread →</Link>
          </article>)}
          {!d.messages.length && <p className="text-[13px] text-muted">No related company emails have arrived.</p>}
        </div>
      </GlassPanel>
    </div>
    <GlassPanel>
      <SectionHeader title="Activity log" icon={History} color="#94A3B8" size="sm" />
      <ul className="mt-3 max-h-80 space-y-1.5 overflow-y-auto text-[12px]">
        {d.activity.map((entry, index) => <li key={`${entry.action}-${entry.at}-${index}`} className="flex flex-wrap gap-x-2 border-b border-white/[.04] py-1.5">
          <span className="w-36 shrink-0 text-faint">{entry.at ? formatDateTimeIST(entry.at) : 'Date unknown'}</span>
          <span className="font-medium text-ink">{entry.action.replace(/_/g, ' ')}</span>
          <span className="text-muted">{entry.detail}</span>
          {entry.model_id && <span className="ml-auto font-mono text-[11px] text-faint">{entry.model_id}</span>}
        </li>)}
        {!d.activity.length && <li className="text-muted">No communication activity yet.</li>}
      </ul>
    </GlassPanel>
  </div>;
}
