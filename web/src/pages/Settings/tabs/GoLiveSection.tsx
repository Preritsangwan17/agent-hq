/**
 * Go-live checklist (CONTRACT_D §5) with live status per item. Loopback-only steps (the API answers 403 from the
 * phone): send-scope consent → live flags in .env → restart → self-test to your own address → typed GO LIVE.
 * Back to DRY RUN is always one click.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { CircleCheck, CircleDashed, FlaskConical, KeyRound, Rocket, ShieldCheck, TerminalSquare } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router';
import { Badge } from '@/components/Badge';
import { Button } from '@/components/Button';
import { ApiError, api, openInNewTab } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatDateTimeIST } from '@/lib/format';
import type { GoLiveItem, GoLiveState } from '@/lib/types';
import { Callout, Code, Section } from '../parts';
import { useSaver } from '../saver';
import { useSettings } from '@/lib/store';

const LINKS: Record<string, { to: string; label: string }> = {
  gmail: { to: '/settings?tab=gmail', label: 'Settings › Gmail' },
  profile: { to: '/settings?tab=profile', label: 'Settings › Profile' },
  reviewed: { to: '/pipeline', label: 'Review on the opportunity pages' },
  caps: { to: '/settings?tab=rules', label: 'Rules & Budget' },
};

export function GoLiveSection() {
  const qc = useQueryClient();
  const s = useSettings();
  const { save } = useSaver();
  const q = useQuery({ queryKey: ['golive'], queryFn: api.golive, refetchInterval: 10_000 });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [phrase, setPhrase] = useState('');
  const st = q.data;

  const run = async (key: string, fn: () => Promise<GoLiveState | unknown>) => {
    setBusy(key);
    setErr(null);
    try {
      const res = await fn();
      if (res && typeof res === 'object' && 'items' in (res as GoLiveState)) qc.setQueryData(['golive'], res);
      else void q.refetch();
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 403 ? 'Only from the Mac itself (not from your phone).' : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const grantSend = () => run('send', () => openInNewTab(async () => (await api.connectGmail('send')).auth_url));

  if (!st) return null;
  const live = st.mode === 'live';
  return (
    <Section
      kicker="Go-live"
      title={live ? 'LIVE' : 'Checklist to go live'}
      icon={Rocket}
      color={live ? '#34D399' : '#F5C451'}
      rows={false}
      right={<Badge color={live ? '#34D399' : '#22D3EE'} mono>{st.mode.replace('_', ' ').toUpperCase()}</Badge>}
      description={live
        ? `Live since ${formatDateTimeIST(st.live_since)} IST. Applications wait for your approval (approve-first) — switch to auto in Autonomy when you trust it.`
        : 'Every item must be green before HQ may ask Google for send permission; then the .env switch, a restart, a self-test to your own inbox and a typed GO LIVE. All of this works only on the Mac itself.'}
    >
      <ul className="divide-y divide-white/[.05] overflow-hidden rounded-xl border border-white/[.08]">
        {st.items.map((i) => (
          <ChecklistRow key={i.id} item={i} busy={busy}
            action={actionFor(i, st, { busy, run, grantSend, ackPolicy: () => save({ signoff_policy_ack: true }), acked: !!s.signoff_policy_ack })} />
        ))}
      </ul>

      {st.env_file_live && !st.items.find((i) => i.id === 'env')?.ok && (
        <Callout icon={TerminalSquare} color="#FBBF24" title="Restart HQ to load the live flags" className="mt-3">
          In Terminal: <Code>make down && make up</Code>. The worker refuses to start if anything is inconsistent.
        </Callout>
      )}
      {err && <p className="mt-3 text-[13px] text-rose-300">{err}</p>}

      {!live ? (
        <div className={cn('mt-4 flex flex-wrap items-center gap-3 rounded-xl border p-3', st.ready_for_live ? 'border-emerald-300/30 bg-emerald-400/[.06]' : 'border-white/[.08] bg-white/[.02]')}>
          <label htmlFor="golive-phrase" className="text-[13px] text-muted">Type <b className="font-mono text-ink">{st.confirm_phrase}</b></label>
          <input id="golive-phrase" value={phrase} onChange={(e) => setPhrase(e.target.value)} disabled={!st.ready_for_live}
            className="h-9 w-36 rounded-lg border border-white/10 bg-black/25 px-3 font-mono text-sm focus:border-emerald-300/50 focus:outline-none disabled:opacity-50" />
          <Button variant="primary" icon={Rocket} disabled={!st.ready_for_live || phrase !== st.confirm_phrase} loading={busy === 'confirm'}
            onClick={() => run('confirm', () => api.confirmLive(phrase))}>
            Go live
          </Button>
          {!st.ready_for_live && <span className="text-[12px] text-faint">unlocks when every item is green</span>}
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="secondary" icon={FlaskConical} loading={busy === 'dry'} onClick={() => run('dry', () => api.backToDryRun(false))}>
            Back to DRY RUN
          </Button>
          <Button variant="ghost" loading={busy === 'dryenv'} onClick={() => run('dryenv', () => api.backToDryRun(true))}>
            …and force dry run in .env
          </Button>
        </div>
      )}
    </Section>
  );
}

function ChecklistRow({ item, action }: { item: GoLiveItem; busy: string | null; action: React.ReactNode }) {
  const Icon = item.ok ? CircleCheck : CircleDashed;
  return (
    <li className="flex flex-wrap items-center gap-3 px-3 py-2.5">
      <Icon className={cn('size-[18px] shrink-0', item.ok ? 'text-emerald-300' : 'text-faint')} aria-label={item.ok ? 'done' : 'to do'} />
      {/* the text keeps a readable width; on a phone the action wraps under it instead of squeezing it */}
      <div className="min-w-[12rem] flex-1">
        <div className={cn('text-[13.5px]', item.ok ? 'text-ink' : 'text-ink/80')}>{item.label}</div>
        <div className="truncate text-[12px] text-muted" title={item.detail}>{item.detail}</div>
      </div>
      {!item.ok && action && <div className="ml-[30px] shrink-0 sm:ml-0">{action}</div>}
    </li>
  );
}

function actionFor(i: GoLiveItem, st: GoLiveState, h: {
  busy: string | null; run: (k: string, fn: () => Promise<unknown>) => Promise<void>; grantSend: () => Promise<void>;
  ackPolicy: () => void; acked: boolean;
}): React.ReactNode {
  const link = LINKS[i.id];
  if (link) return <Link to={link.to} className="text-[12.5px] text-cyan-300 hover:underline">{link.label}</Link>;
  switch (i.id) {
    case 'golden':
      return <Button size="sm" variant="secondary" loading={h.busy === 'golden'} onClick={() => h.run('golden', api.runGolden)}>Run now</Button>;
    case 'cloud':
      return h.acked ? null : <Button size="sm" variant="ghost" onClick={h.ackPolicy}>Accept local checks only</Button>;
    case 'send_scope':
      return <Button size="sm" variant="primary" icon={KeyRound} disabled={!st.ready_for_send_scope} loading={h.busy === 'send'} onClick={h.grantSend}>Grant send permission</Button>;
    case 'env':
      return st.env_file_live ? <Badge color="#FBBF24">restart needed</Badge>
        : <Button size="sm" icon={ShieldCheck} disabled={!st.ready_for_env} loading={h.busy === 'env'} onClick={() => h.run('env', api.writeLiveEnv)}>Write live flags to .env</Button>;
    case 'self_test':
      return <Button size="sm" disabled={!st.items.find((x) => x.id === 'env')?.ok} loading={h.busy === 'self'} onClick={() => h.run('self', api.selfTest)}>Send self-test</Button>;
    default:
      return null;
  }
}
