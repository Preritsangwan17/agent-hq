import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router';
import { MailCheck, Plus, RefreshCw, Search, Send, ShieldCheck } from 'lucide-react';
import { Badge, Button, GlassPanel, SectionHeader } from '@/components';
import { emailModuleApi, type EmailMode } from '@/lib/emailModule';
import { formatDateTimeIST } from '@/lib/format';

const emptyForm = { company: '', role: '', contact_name: '', email: '', research: '', job_description: '', profile_fact: '' };
const input = 'w-full rounded-xl border border-white/15 bg-surface-1 px-3 py-2.5 text-sm text-ink outline-none focus:border-cyan-400/70';
const date = (value: string | null) => value ? formatDateTimeIST(value) : '—';

export default function EmailModulePage() {
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const opportunityParam = params.get('opportunity') ?? '';
  const [mode, setMode] = useState<EmailMode>('sandbox');
  const [selected, setSelected] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [importId, setImportId] = useState(opportunityParam);
  const [search, setSearch] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [replyBody, setReplyBody] = useState('Thank you for your application. We would like to schedule an interview.');
  const [edit, setEdit] = useState({ contact_name: '', research: '', job_description: '', profile_fact: '' });
  const [feedback, setFeedback] = useState('');
  const dashboard = useQuery({ queryKey: ['email-module', mode], queryFn: () => emailModuleApi.dashboard(mode) });
  const detail = useQuery({ queryKey: ['email-module-detail', mode, selected], queryFn: () => emailModuleApi.detail(selected!, mode), enabled: !!selected });
  const results = useQuery({ queryKey: ['email-module-search', mode, searchTerm], queryFn: () => emailModuleApi.search(searchTerm, mode), enabled: searchTerm.length > 0 });
  const refresh = async () => { await Promise.all([qc.invalidateQueries({ queryKey: ['email-module', mode] }), qc.invalidateQueries({ queryKey: ['email-module-detail', mode, selected] })]); };
  const action = useMutation({ mutationFn: async (fn: () => Promise<unknown>) => fn(), onSuccess: async () => { setFeedback('Saved.'); await refresh(); }, onError: (error: Error) => setFeedback(error.message) });
  const run = (fn: () => Promise<unknown>) => { setFeedback(''); action.mutate(fn); };
  const current = detail.data?.application;
  useEffect(() => { if (opportunityParam) setImportId(opportunityParam); }, [opportunityParam]);
  useEffect(() => {
    if (current) setEdit({ contact_name: current.contact_name, research: current.research,
      job_description: current.job_description, profile_fact: Object.values(current.profile)[0] ?? '' });
  }, [current?.id, current?.updated_at]);

  return <div className="min-w-0 space-y-5 pb-8">
    <SectionHeader kicker="Independent email workflow" title="Application Email" icon={MailCheck} color="#60A5FA" right={<Button icon={RefreshCw} loading={dashboard.isFetching} onClick={() => void refresh()}>Refresh</Button>} />
    <GlassPanel padding="md" glow="#60A5FA" accentTop>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="font-semibold text-ink">{mode === 'sandbox' ? 'Sandbox mailbox' : 'Connected Gmail'}</h2>
          <p className="mt-1 text-sm text-muted">{mode === 'sandbox' ? 'Test drafting, sending, replies and tracking with a local fake mailbox.' : dashboard.data?.connected ? 'Real Gmail is connected. Every message still needs your approval.' : 'Connect your Gmail account in Settings to read real mail.'}</p></div>
        <div className="flex gap-2"><Button size="sm" variant={mode === 'sandbox' ? 'primary' : 'secondary'} onClick={() => { setMode('sandbox'); setSelected(null); }}>Sandbox</Button><Button size="sm" variant={mode === 'live' ? 'primary' : 'secondary'} onClick={() => { setMode('live'); setSelected(null); }}>Gmail</Button></div>
      </div>
      {mode === 'live' && <p className="mt-3 text-xs text-amber-200">Live sending is {dashboard.data?.live_send_enabled ? 'enabled' : 'off'}. <Link className="underline" to="/settings?tab=gmail">Open Gmail settings</Link> to connect or review permissions.</p>}
      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">{Object.entries(dashboard.data?.counts ?? { applications: 0, waiting: 0, replies: 0, followups_due: 0 }).map(([key, value]) => <div key={key} className="rounded-xl border border-white/10 bg-white/[.03] p-3"><div className="text-2xl font-semibold text-ink">{value}</div><div className="mt-1 text-xs capitalize text-muted">{key.replaceAll('_', ' ')}</div></div>)}</div>
    </GlassPanel>
    {feedback && <p role="status" className="rounded-xl border border-white/15 bg-white/[.05] px-4 py-3 text-sm text-ink">{feedback}</p>}
    {dashboard.isError && <p role="alert" className="text-red-200">{dashboard.error.message}</p>}
    <GlassPanel padding="md">
      <SectionHeader title="Applications and contacts" size="sm" icon={ShieldCheck} right={<Button size="sm" icon={RefreshCw} loading={action.isPending} onClick={() => run(async () => { const result = await emailModuleApi.sync(mode); setFeedback(`Imported ${result.imported} messages.`); })}>Check mail</Button>} />
      <div className="mt-4 overflow-x-auto"><table className="min-w-[1100px] w-full text-left text-xs"><thead><tr className="border-b border-white/10 text-muted">{['Company', 'Role', 'Recruiter', 'Email', 'Status', 'Last sent', 'Reply', 'Next follow-up', 'Follow-ups', 'Interview / assessment links', 'Deadlines'].map(h => <th key={h} scope="col" className="whitespace-nowrap px-3 py-3 font-medium">{h}</th>)}</tr></thead><tbody>{dashboard.data?.applications.map(app => <tr key={app.id} className="border-b border-white/[.06] hover:bg-white/[.04]"><td className="px-3 py-3"><button className="font-medium text-cyan-300 underline-offset-2 hover:underline" onClick={() => setSelected(app.id)}>{app.company}</button></td><td className="px-3 py-3">{app.role}</td><td className="px-3 py-3">{app.contact_name || '—'}</td><td className="px-3 py-3">{app.email}</td><td className="px-3 py-3"><Badge color="#60A5FA" size="xs">{app.status}</Badge></td><td className="whitespace-nowrap px-3 py-3">{date(app.last_email_sent)}</td><td className="px-3 py-3">{app.reply_received ? 'Yes' : 'No'}</td><td className="whitespace-nowrap px-3 py-3">{date(app.next_followup_at)}</td><td className="px-3 py-3">{app.followup_count}</td><td className="px-3 py-3">{app.links.length ? app.links.map(url => <a key={url} className="block max-w-40 truncate text-cyan-300 underline" href={url} target="_blank" rel="noopener noreferrer">{url}</a>) : '—'}</td><td className="px-3 py-3">{app.deadlines.join(', ') || '—'}</td></tr>)}</tbody></table>{!dashboard.data?.applications.length && <p className="p-4 text-sm text-muted">No applications in this {mode} ledger yet.</p>}</div>
    </GlassPanel>
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
      <GlassPanel padding="md"><SectionHeader title="Add a contact" icon={Plus} size="sm" /><p className="mt-2 text-xs text-muted">Use a verified contact and write company research, the job description and one true profile fact for a specific draft.</p>
        <form className="mt-4 grid gap-3" onSubmit={e => { e.preventDefault(); run(async () => { const created = await emailModuleApi.create({ ...form, profile: form.profile_fact ? { verified: form.profile_fact } : {} }, mode); setSelected(created.id); setForm(emptyForm); }); }}>
          <div className="grid gap-3 sm:grid-cols-2"><label className="text-xs text-muted">Company<input className={input} required value={form.company} onChange={e => setForm({ ...form, company: e.target.value })} /></label><label className="text-xs text-muted">Role<input className={input} required value={form.role} onChange={e => setForm({ ...form, role: e.target.value })} /></label><label className="text-xs text-muted">Recruiter<input className={input} value={form.contact_name} onChange={e => setForm({ ...form, contact_name: e.target.value })} /></label><label className="text-xs text-muted">Email<input className={input} type="email" required value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} /></label></div>
          <label className="text-xs text-muted">Company research<textarea className={input} rows={2} value={form.research} onChange={e => setForm({ ...form, research: e.target.value })} /></label>
          <label className="text-xs text-muted">Job description<textarea className={input} rows={2} value={form.job_description} onChange={e => setForm({ ...form, job_description: e.target.value })} /></label>
          <label className="text-xs text-muted">Verified experience phrase<textarea className={input} rows={2} placeholder="a Python recommendation project that used collaborative filtering" value={form.profile_fact} onChange={e => setForm({ ...form, profile_fact: e.target.value })} /></label>
          <Button type="submit" variant="primary" disabled={action.isPending}>Add application</Button>
        </form>
        <div className="mt-5 border-t border-white/10 pt-4"><label className="text-xs text-muted">Import an Agent HQ opportunity ID<input className={input} value={importId} onChange={e => setImportId(e.target.value)} /></label><Button className="mt-2" size="sm" disabled={!importId || action.isPending} onClick={() => run(async () => { const created = await emailModuleApi.importOpportunity(importId, mode); setSelected(created.id); setImportId(''); })}>Import opportunity</Button></div>
      </GlassPanel>
      <GlassPanel padding="md"><SectionHeader title={current ? `${current.company} · ${current.role}` : 'Communication detail'} size="sm" icon={MailCheck} />
        {!selected && <p className="mt-4 text-sm text-muted">Choose a company to review its drafts, messages and next action.</p>}
        {selected && detail.isError && <p role="alert" className="mt-4 text-red-200">{detail.error.message}</p>}
        {current && <div className="mt-4 space-y-4">
          <div className="flex flex-wrap gap-2"><Badge color="#60A5FA">{current.status}</Badge><Badge color={current.reply_received ? '#34D399' : '#FBBF24'}>{current.reply_received ? 'Reply received' : 'Waiting for reply'}</Badge>{current.source_opportunity_id && <Link className="text-xs text-cyan-300 underline" to={`/o/${current.source_opportunity_id}`}>Open opportunity</Link>}</div>
          <form className="grid gap-2 rounded-xl border border-white/10 p-3" onSubmit={e => { e.preventDefault(); run(() => emailModuleApi.update(current.id, { contact_name: edit.contact_name, research: edit.research,
            job_description: edit.job_description, profile: edit.profile_fact ? { verified: edit.profile_fact } : {} }, mode)); }}>
            <h3 className="text-sm font-semibold text-ink">Personalization context</h3>
            <label className="text-xs text-muted">Recruiter name<input className={input} value={edit.contact_name} onChange={e => setEdit({ ...edit, contact_name: e.target.value })} /></label>
            <label className="text-xs text-muted">Company research<textarea className={input} rows={2} value={edit.research} onChange={e => setEdit({ ...edit, research: e.target.value })} /></label>
            <label className="text-xs text-muted">Job description<textarea className={input} rows={2} value={edit.job_description} onChange={e => setEdit({ ...edit, job_description: e.target.value })} /></label>
            <label className="text-xs text-muted">Verified experience phrase<textarea className={input} rows={2} value={edit.profile_fact} onChange={e => setEdit({ ...edit, profile_fact: e.target.value })} /></label>
            <Button type="submit" size="sm" disabled={action.isPending}>Save context</Button>
          </form>
          <p className="text-xs text-muted">Next follow-up: {date(current.next_followup_at)} · Follow-ups sent: {current.followup_count}/{dashboard.data?.policy.maximum_followups ?? 2}</p>
          <div className="flex flex-wrap gap-2"><Button size="sm" icon={Plus} disabled={action.isPending} onClick={() => run(() => emailModuleApi.draft(current.id, 'application', mode))}>Draft application</Button><Button size="sm" disabled={action.isPending || !current.next_followup_at || new Date(current.next_followup_at) > new Date()} onClick={() => run(() => emailModuleApi.draft(current.id, 'followup', mode))}>Draft follow-up</Button>{current.reply_received && <Button size="sm" disabled={action.isPending} onClick={() => run(() => emailModuleApi.draft(current.id, 'reply', mode))}>Draft reply</Button>}</div>
          {detail.data?.drafts.map(draft => <div key={draft.id} className="rounded-xl border border-white/10 bg-white/[.03] p-4"><div className="flex items-center justify-between gap-2"><strong className="text-sm text-ink">{draft.subject}</strong><Badge color={draft.status === 'sent' ? '#34D399' : draft.status === 'ambiguous' ? '#FBBF24' : '#60A5FA'} size="xs">{draft.status}</Badge></div><pre className="mt-3 whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-muted">{draft.body}</pre>{draft.error && <p className="mt-2 text-xs text-amber-200">{draft.error}</p>}<div className="mt-3 flex flex-wrap gap-2">{draft.status === 'draft' && <Button size="sm" onClick={() => run(() => emailModuleApi.approve(draft.id, mode))}>Approve exact text</Button>}{draft.status === 'approved' && <Button size="sm" variant="primary" icon={Send} onClick={() => run(() => emailModuleApi.send(draft.id, mode))}>Send approved email</Button>}{draft.status === 'ambiguous' && <Button size="sm" onClick={() => run(() => emailModuleApi.reconcile(draft.id, mode))}>Check Sent folder</Button>}</div></div>)}
          <div><h3 className="text-sm font-semibold text-ink">Email history</h3><div className="mt-2 space-y-2">{detail.data?.messages.map(message => <div key={message.gmail_id} className="rounded-lg border border-white/10 p-3"><div className="flex justify-between gap-2 text-xs text-muted"><span>{message.direction === 'sent' ? 'Sent to' : 'Received from'} {message.direction === 'sent' ? current.email : message.from_addr}</span><span>{date(message.received_at)}</span></div><div className="mt-1 text-sm font-medium text-ink">{message.subject}</div><p className="mt-1 line-clamp-4 whitespace-pre-wrap text-xs text-muted">{message.body}</p></div>)}{!detail.data?.messages.length && <p className="text-xs text-muted">No messages yet.</p>}</div></div>
          {mode === 'sandbox' && current.gmail_thread_id && <div className="border-t border-white/10 pt-3"><label className="text-xs text-muted">Simulate recruiter reply<textarea className={input} rows={3} value={replyBody} onChange={e => setReplyBody(e.target.value)} /></label><Button size="sm" className="mt-2" onClick={() => run(async () => { await emailModuleApi.simulateReply(current.id, `Re: Application for ${current.role}`, replyBody); await emailModuleApi.sync('sandbox'); })}>Simulate and detect reply</Button></div>}
        </div>}
      </GlassPanel>
    </div>
    <GlassPanel padding="md"><SectionHeader title="Search mailbox" size="sm" icon={Search} /><form className="mt-3 flex gap-2" onSubmit={e => { e.preventDefault(); setSearchTerm(search.trim() || 'application'); }}><input className={input} aria-label="Search Gmail" value={search} onChange={e => setSearch(e.target.value)} placeholder="company, recruiter, interview, application…" /><Button type="submit" icon={Search}>Search</Button></form>{results.isError && <p role="alert" className="mt-3 text-sm text-red-200">{results.error.message}</p>}{results.data && <div className="mt-3 space-y-2">{results.data.messages.length === 0 ? <p className="text-sm text-muted">No matching messages.</p> : results.data.messages.map(message => <div key={message.id} className="border-t border-white/10 py-2 text-sm"><strong className="text-ink">{message.subject}</strong><p className="text-xs text-muted">{message.from} · {date(message.date)}</p><p className="mt-1 text-xs text-muted">{message.snippet}</p></div>)}</div>}</GlassPanel>
  </div>;
}
