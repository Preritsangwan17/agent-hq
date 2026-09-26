/**
 * Settings › Gmail (CONTRACT_D §1): the Desktop OAuth client wizard (loopback only), read-only connection status,
 * inbox polling, macOS notifications and the auto-reply switch. Send permission is granted only in the go-live
 * checklist (Autonomy & Mode).
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Bell, CircleCheck, ExternalLink, Link2, Mail, MailWarning, RefreshCw, Reply, Unplug } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Badge } from '@/components/Badge';
import { Button } from '@/components/Button';
import { ApiError, api } from '@/lib/api';

import { formatRelative } from '@/lib/format';
import { useSettings } from '@/lib/store';
import type { GmailInfo } from '@/lib/types';
import { Field, TextInput } from '@/pages/Agents/formKit';
import { NumberField, SettingRow, Toggle } from '../controls';
import { Callout, Code, Section } from '../parts';
import { useSaver } from '../saver';

const GM = '#60A5FA';
const STEPS = [
  { title: 'Create a Google Cloud project and enable the Gmail API',
    href: 'https://console.cloud.google.com/apis/library/gmail.googleapis.com' },
  { title: 'OAuth consent screen: External, add yourself as a test user, then Publish app (“In production”)',
    note: 'Testing mode expires the refresh token after 7 days. Google shows an “unverified app” warning for a single-user app — that is expected; continue as yourself.',
    href: 'https://console.cloud.google.com/apis/credentials/consent' },
  { title: 'Credentials › Create credentials › OAuth client ID › Desktop app',
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

  const connect = () => run('connect', async () => {
    const r = await api.connectGmail('readonly');
    window.open(r.auth_url, '_blank', 'noopener');
  });

  const healthy = !!g?.state.healthy;
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
            {STEPS.map((st, i) => (
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
                onSave={(id, secret) => run('client', () => api.saveGmailClient(id, secret))} />
            </li>
            <li className="flex gap-3">
              <StepDot n={5} done={false} />
              <div className="min-w-0 space-y-2 text-[13.5px]">
                <div>Connect read-only — Google opens in a new tab; approve, then come back.</div>
                <Button variant="primary" size="sm" icon={Link2} disabled={!g?.client_configured} loading={busy === 'connect' || g?.oauth.status === 'pending'} onClick={connect}>
                  {g?.oauth.status === 'pending' ? 'Waiting for Google…' : 'Connect Gmail (read-only)'}
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
        <SettingRow icon={Reply} color="#22D3EE" title="Auto-reply to simple info requests" htmlFor="auto-reply"
          description="Only résumé / GitHub / LinkedIn / repository requests, only when the rules and the model agree with ≥ 90 % confidence and every gate passes — and never before 14 days in LIVE. Otherwise HQ drafts and asks you."
          control={<Toggle id="auto-reply" label="Auto-reply" checked={!!s.auto_reply_enabled} onChange={(v) => save({ auto_reply_enabled: v })} color="#22D3EE" />} />
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

function ClientForm({ configured, busy, onSave }: { configured: boolean; busy: boolean; onSave: (id: string, secret: string) => void }) {
  const [id, setId] = useState('');
  const [secret, setSecret] = useState('');
  return (
    <form className="grid w-full min-w-0 gap-2 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); onSave(id, secret); }}>
      <div className="text-[13.5px] sm:col-span-2">
        Paste the client ID and secret{configured && <span className="text-emerald-300"> (saved — paste again to replace)</span>}. They go
        to <Code>.env</Code> only.
      </div>
      <Field label="Client ID" htmlFor="gm-id"><TextInput id="gm-id" mono value={id} onChange={(e) => setId(e.target.value.trim())} placeholder="…apps.googleusercontent.com" /></Field>
      <Field label="Client secret" htmlFor="gm-secret"><TextInput id="gm-secret" mono type="password" value={secret} onChange={(e) => setSecret(e.target.value.trim())} /></Field>
      <div className="sm:col-span-2"><Button type="submit" size="sm" disabled={!id || !secret} loading={busy}>Save client</Button></div>
    </form>
  );
}

