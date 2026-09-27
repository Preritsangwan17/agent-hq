/**
 * Settings › Gmail (CONTRACT_D §1): the Desktop OAuth client wizard (loopback only), read-only connection status,
 * inbox polling, macOS notifications and separate communication controls. Send permission is granted only in the go-live
 * checklist (Autonomy & Mode).
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Bell, CircleCheck, ExternalLink, FileJson, Link2, Mail, MailWarning, RefreshCw, Reply, Unplug } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Badge } from '@/components/Badge';
import { Button } from '@/components/Button';
import { ApiError, api, openInNewTab } from '@/lib/api';

import { formatRelative } from '@/lib/format';
import { useSettings } from '@/lib/store';
import type { GmailInfo } from '@/lib/types';
import { Field, TextInput } from '@/pages/Agents/formKit';
import { NumberField, SettingRow, Toggle } from '../controls';
import { Callout, Code, Section } from '../parts';
import { useSaver } from '../saver';

const GM = '#60A5FA';
const steps = (email: string) => [
  { title: 'Create a Google Cloud project and enable the Gmail API',
    note: `Sign in to Google Cloud as ${email}. Any project name works (e.g. “Agent HQ”).`,
    href: 'https://console.cloud.google.com/apis/library/gmail.googleapis.com' },
  { title: `OAuth consent screen: External, add ${email} as a test user`,
    note: 'Testing mode can expire refresh tokens after 7 days. If Google shows an unverified-app warning, check the project name and permissions before continuing. Wider public use may require Google verification.',
    href: 'https://console.cloud.google.com/apis/credentials/consent' },
  { title: 'Credentials › Create credentials › OAuth client ID › Desktop app, then Download JSON',
    note: 'Pick “Desktop app” (not “Web application”). The download is a client_secret_….json file.',
    href: 'https://console.cloud.google.com/apis/credentials' },
];

export function GmailTab() {
  const qc = useQueryClient();
  const s = useSettings();
  const { save } = useSaver();
  const q = useQuery({ queryKey: ['gmail'], queryFn: api.gmail, refetchInterval: (query) =>
    query.state.data?.oauth.status === 'pending' ? 2000 : 15_000 });
  const g = q.data;
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setErr(null);
    try {
      const res = await fn();
      if (res && typeof res === 'object' && 'connected' in (res as GmailInfo)) qc.setQueryData(['gmail'], res);
      await q.refetch();
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 403 ? 'This only works on the Mac itself (not from your phone).'
        : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  useEffect(() => {
    if (g?.oauth.status === 'done') void api.recheckGmail();
  }, [g?.oauth.status]);

  const connect = () => run('connect', () => openInNewTab(async () => (await api.connectGmail('readonly')).auth_url));

  const healthy = !!g?.state.healthy && !g?.account_mismatch;
  const ownerEmail = g?.owner_email ?? 'your Gmail';
  return (
    <div className="space-y-5">
      {g?.refusal && (
        <Callout icon={MailWarning} color="#F87171" title="The worker refused to start">
          {g.refusal.reason}
        </Callout>
      )}
      <Section kicker="Connection" title="Gmail" icon={Mail} color={GM} rows={false}
        right={<Badge color={g?.connected ? (healthy ? '#34D399' : '#FBBF24') : '#64748B'}>
          {g?.connected ? (healthy ? 'connected' : 'needs attention') : 'not connected'}</Badge>}
        description="HQ reads only what it needs: threads of your applications, replies to its own emails, mail from companies you applied to, ATS senders and job-alert senders. Everything else in the mailbox is never stored.">
        {g?.connected ? (
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-3">
              <Stat label="Account" value={g.state.email ?? '…'} />
              <Stat label="Last check" value={g.state.last_poll_at ? formatRelative(g.state.last_poll_at) : 'not yet'} />
              <Stat label="Permissions" value={g.scopes.join(', ') || '—'} />
            </div>
            {g.account_mismatch && (
              <Callout icon={MailWarning} color="#F87171" title={`Connected as ${g.account_mismatch}`}>
                HQ only reads and sends as <b>{g.owner_email}</b>. Disconnect, then connect again and pick {g.owner_email}{' '}
                on Google's account screen.
              </Callout>
            )}
            {g.state.error && <p className="text-[13px] text-amber-200">{g.state.error}</p>}
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" icon={RefreshCw} loading={busy === 'recheck'} onClick={() => run('recheck', api.recheckGmail)}>Check now</Button>
              <Button size="sm" variant="ghost" icon={Unplug} loading={busy === 'disconnect'} onClick={() => run('disconnect', api.disconnectGmail)}>Disconnect</Button>
            </div>
            {g.send_scope && g.forced_dry_run && (
              <Callout icon={MailWarning} color="#FBBF24">
                This grant can send mail while HQ is forced to dry run — the worker refuses to start. Finish going live, or
                disconnect and connect again read-only.
              </Callout>
            )}
          </div>
        ) : (
          <ol className="space-y-3">
            {steps(ownerEmail).map((st, i) => (
              <li key={st.title} className="flex gap-3">
                <StepDot n={i + 1} done={!!g?.client_configured} />
                <div className="min-w-0 text-[13.5px]">
                  <a href={st.href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-ink hover:text-cyan-200">
                    {st.title} <ExternalLink className="size-3.5 text-muted" />
                  </a>
                  {st.note && <p className="mt-0.5 text-[12.5px] text-muted">{st.note}</p>}
                </div>
              </li>
            ))}
            <li className="flex gap-3">
              <StepDot n={4} done={!!g?.client_configured} />
              <ClientForm configured={!!g?.client_configured} busy={busy === 'client'}
                onSave={(client) => run('client', () => api.saveGmailClient(client))} />
            </li>
            <li className="flex gap-3">
              <StepDot n={5} done={false} />
              <div className="min-w-0 space-y-2 text-[13.5px]">
                <div>Connect read-only — Google opens in a new tab with {ownerEmail} pre-selected; approve, then come back.</div>
                <Button variant="primary" size="sm" icon={Link2} disabled={!g?.client_configured} loading={busy === 'connect' || g?.oauth.status === 'pending'} onClick={connect}>
                  {g?.oauth.status === 'pending' ? 'Waiting for Google…' : `Connect ${ownerEmail} (read-only)`}
                </Button>
                {g?.oauth.status === 'error' && <p className="text-[12.5px] text-rose-300">{g.oauth.error}</p>}
              </div>
            </li>
          </ol>
        )}
        {err && <p className="mt-3 text-[13px] text-rose-300">{err}</p>}
      </Section>

      <Section kicker="Inbox" title="Watching for replies" icon={Bell} color={GM}>
        <SettingRow title="Check Gmail every" htmlFor="gmail-poll"
          description="Uses Gmail's history API (only changes since last time)."
          control={<NumberField id="gmail-poll" aria-label="Minutes between Gmail checks" value={Number(s.gmail_poll_minutes ?? 3)}
            onChange={(v) => save({ gmail_poll_minutes: v })} min={1} max={60} step={1} suffix="min" className="w-32" />} />
        <SettingRow icon={Bell} color="#FBBF24" title="macOS notifications" htmlFor="mac-notify"
          description="A banner for interview, offer, money and legal mail (and Gmail problems). Uses terminal-notifier if installed, otherwise osascript."
          control={<Toggle id="mac-notify" label="macOS notifications" checked={s.mac_notifications !== false} onChange={(v) => save({ mac_notifications: v })} color="#FBBF24" />} />
        <SettingRow icon={Mail} color="#60A5FA" title="Read job emails" htmlFor="read-job-emails"
          description="Monitor related company, recruiter, ATS and job-alert mail. Personal mail stays out of the saved Inbox."
          control={<Toggle id="read-job-emails" label="Read job emails" checked={s.read_job_emails !== false}
            onChange={(v) => save({ read_job_emails: v })} color="#60A5FA" />} />
        <SettingRow icon={Mail} color="#A78BFA" title="Automatically classify emails" htmlFor="classify-job-emails"
          description="Update stages and the company timeline using inbox rules and your active AI mode."
          control={<Toggle id="classify-job-emails" label="Classify job emails" checked={s.classify_job_emails !== false}
            onChange={(v) => save({ classify_job_emails: v })} color="#A78BFA" />} />
        <SettingRow icon={Reply} color="#22D3EE" title="Generate replies" htmlFor="generate-email-replies"
          description="Prepare professional drafts for safe information requests. You can edit each draft before sending."
          control={<Toggle id="generate-email-replies" label="Generate replies" checked={s.generate_email_replies !== false}
            onChange={(v) => save({ generate_email_replies: v })} color="#22D3EE" />} />
        <SettingRow icon={Reply} color="#34D399" title="Automatically send routine replies" htmlFor="auto-routine-replies"
          description="Only verified-company, low-risk replies may send automatically after 14 days LIVE, with model agreement and all existing gates. High-impact threads stay locked."
          control={<Toggle id="auto-routine-replies" label="Automatically send routine replies"
            checked={!!s.auto_send_routine_replies || !!s.auto_reply_enabled}
            onChange={(v) => save({ auto_send_routine_replies: v, auto_reply_enabled: false })} color="#34D399" />} />
        <SettingRow icon={Bell} color="#F5C451" title="Ask Before Sending" htmlFor="ask-before-sending"
          description="Keep this on to approve every AI-prepared reply. High-impact communication always needs your approval."
          control={<Toggle id="ask-before-sending" label="Ask Before Sending" checked={s.ask_before_sending !== false}
            onChange={(v) => save({ ask_before_sending: v })} color="#F5C451" />} />
        <SettingRow icon={RefreshCw} color="#FBBF24" title="Automatically follow up" htmlFor="auto-followup"
          description="Send one gated follow-up after 10 days only if no person replied. Turn off to pause existing scheduled follow-ups."
          control={<Toggle id="auto-followup" label="Automatically follow up" checked={s.auto_followup_enabled !== false}
            onChange={(v) => save({ auto_followup_enabled: v })} color="#FBBF24" />} />
      </Section>
    </div>
  );
}

function StepDot({ n, done }: { n: number; done: boolean }) {
  return done ? <CircleCheck className="mt-0.5 size-5 shrink-0 text-emerald-300" aria-label="done" />
    : <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full border border-white/20 font-mono text-[10.5px] text-muted">{n}</span>;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-xl border border-white/[.08] bg-white/[.03] px-3 py-2">
      <div className="text-[11px] tracking-[0.12em] text-muted uppercase">{label}</div>
      <div className="mt-0.5 truncate text-[13.5px] text-ink" title={value}>{value}</div>
    </div>
  );
}

type ClientInput = { client_id: string; client_secret: string } | { client_json: string };

function ClientForm({ configured, busy, onSave }: { configured: boolean; busy: boolean; onSave: (client: ClientInput) => void }) {
  const [mode, setMode] = useState<'file' | 'manual'>('file');
  const [id, setId] = useState('');
  const [secret, setSecret] = useState('');
  const [json, setJson] = useState('');
  const [fileName, setFileName] = useState<string | null>(null);
  const [fileErr, setFileErr] = useState<string | null>(null);

  const readFile = async (file: File | undefined) => {
    setFileErr(null);
    if (!file) return;
    if (file.size > 20_000) {
      setFileErr('That file is too big to be a Google client file.');
      return;
    }
    setFileName(file.name);
    setJson(await file.text());
  };

  return (
    <div className="w-full min-w-0 space-y-2">
      <div className="text-[13.5px]">
        Give HQ the Desktop client{configured && <span className="text-emerald-300"> (saved — add it again to replace)</span>}. It
        goes to <Code>.env</Code> only.
      </div>
      <div className="inline-flex rounded-lg border border-white/10 bg-white/[.03] p-0.5 text-[12.5px]" role="tablist">
        {(['file', 'manual'] as const).map((m) => (
          <button key={m} type="button" role="tab" aria-selected={mode === m} onClick={() => setMode(m)}
            className={`rounded-md px-2.5 py-1 transition-colors ${mode === m ? 'bg-white/[.09] text-ink' : 'text-muted hover:text-ink'}`}>
            {m === 'file' ? 'Downloaded JSON file' : 'Client ID + secret'}
          </button>
        ))}
      </div>
      {mode === 'file' ? (
        <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); onSave({ client_json: json }); }}>
          <label className="flex cursor-pointer items-center gap-2 rounded-xl border border-dashed border-white/15 bg-white/[.02] px-3 py-2.5 text-[13px] text-muted hover:border-cyan-300/40 hover:text-ink">
            <FileJson className="size-4 shrink-0 text-cyan-300" aria-hidden />
            <span className="min-w-0 truncate">{fileName ?? 'Choose client_secret_….json'}</span>
            <input type="file" accept="application/json,.json" className="sr-only" onChange={(e) => void readFile(e.target.files?.[0])} />
          </label>
          <textarea
            aria-label="Or paste the file's contents"
            value={json}
            onChange={(e) => { setJson(e.target.value); setFileName(null); }}
            placeholder='…or paste its contents: {"installed":{"client_id":"…","client_secret":"…"}}'
            rows={3}
            spellCheck={false}
            className="w-full resize-y rounded-xl border border-white/10 bg-black/20 px-3 py-2 font-mono text-[12px] text-ink placeholder:text-faint focus:border-cyan-300/40 focus:outline-none"
          />
          {fileErr && <p className="text-[12.5px] text-rose-300">{fileErr}</p>}
          <Button type="submit" size="sm" disabled={json.trim().length < 20} loading={busy}>Save client</Button>
        </form>
      ) : (
        <form className="grid gap-2 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); onSave({ client_id: id, client_secret: secret }); }}>
          <Field label="Client ID" htmlFor="gm-id"><TextInput id="gm-id" mono value={id} onChange={(e) => setId(e.target.value.trim())} placeholder="…apps.googleusercontent.com" /></Field>
          <Field label="Client secret" htmlFor="gm-secret"><TextInput id="gm-secret" mono type="password" value={secret} onChange={(e) => setSecret(e.target.value.trim())} /></Field>
          <div className="sm:col-span-2"><Button type="submit" size="sm" disabled={!id || !secret} loading={busy}>Save client</Button></div>
        </form>
      )}
    </div>
  );
}
