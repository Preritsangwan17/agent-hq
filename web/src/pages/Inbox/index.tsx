/**
 * Inbox (CONTRACT_D §6): classified replies, notify-only locks (HQ never writes on a locked thread; unlocking is
 * typed and audited), interview/offer banners with a one-time modal, and info-reply drafts to edit, send or discard.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'motion/react';
import {
  ArrowLeft,
  ExternalLink,
  Inbox as InboxIcon,
  Lock,
  LockOpen,
  Mail,
  MailCheck,
  Send,
  ShieldAlert,
  Trash2,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { Badge, Button, EmptyState, GlassPanel, SectionHeader, SimTag, StageChip } from '@/components';
import { ApiError, api } from '@/lib/api';
import { cn } from '@/lib/cn';
import { eventBus } from '@/lib/bus';
import { formatDateTimeIST, formatRelative } from '@/lib/format';
import { useIsMobile } from '@/lib/hooks';
import type { InboxThread, ReplyDraft } from '@/lib/types';
import { withAlpha } from '@/theme/tokens';

type Filter = 'all' | 'alerts' | 'locked' | 'drafts';

export const CLASS_META: Record<string, { label: string; color: string }> = {
  interview_invite: { label: 'Interview', color: '#F87171' },
  interview: { label: 'Interview', color: '#F87171' },
  assessment: { label: 'Assessment', color: '#FB923C' },
  offer: { label: 'Offer', color: '#F5C451' },
  legal: { label: 'Legal', color: '#F87171' },
  scam: { label: 'Scam', color: '#F43F5E' },
  info_request: { label: 'Info request', color: '#22D3EE' },
  rejection: { label: 'Rejection', color: '#94A3B8' },
  auto_ack: { label: 'Auto-ack', color: '#64748B' },
  job_alert: { label: 'Job alert', color: '#A78BFA' },
  other: { label: 'Other', color: '#64748B' },
};

function classMeta(c: string | null | undefined) {
  return (c && CLASS_META[c]) || { label: c ? c.replace(/_/g, ' ') : 'Unclassified', color: '#64748B' };
}

export default function Inbox() {
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState<Filter>('all');
  const selected = params.get('thread');
  const mobile = useIsMobile();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ['inbox', filter], queryFn: () => api.inboxThreads(filter), refetchInterval: 30_000 });
  const gmail = useQuery({ queryKey: ['gmail'], queryFn: api.gmail, staleTime: 30_000 });

  useEffect(
    () =>
      eventBus.on((e) => {
        if (e.type === 'inbox.updated' || e.type === 'mail.sent' || e.type === 'mail.mock_sent') {
          void qc.invalidateQueries({ queryKey: ['inbox'] });
          void qc.invalidateQueries({ queryKey: ['thread'] });
        }
      }),
    [qc],
  );

  const select = (id: string | null) =>
    setParams((p) => {
      const n = new URLSearchParams(p);
      if (id) n.set('thread', id);
      else n.delete('thread');
      return n;
    });

  const items = list.data?.items ?? [];
  const counts = list.data?.counts;
  const alertThread = items.find((t) => list.data?.unacked_alerts.includes(t.id));
  const showList = !mobile || !selected;
  const showDetail = !mobile || !!selected;

  return (
    <div className="space-y-5">
      <SectionHeader
        as="h1"
        size="lg"
        kicker="Replies"
        title="Inbox"
        icon={InboxIcon}
        color="#60A5FA"
        right={<GmailChip connected={!!gmail.data?.connected} healthy={!!gmail.data?.state.healthy} email={gmail.data?.state.email} />}
      />

      {(counts?.locked ?? 0) > 0 && (
        <div className="flex items-center gap-2 rounded-xl border border-red-400/25 bg-red-500/[.08] px-4 py-2.5 text-[13px] text-red-100">
          <ShieldAlert className="size-4 shrink-0 text-red-300" aria-hidden />
          {counts?.locked} notify-only thread{counts?.locked === 1 ? '' : 's'} — interviews, assessments, offers, money and legal
          mail are yours. HQ never writes on them.
        </div>
      )}

      <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Filter threads">
        {(['all', 'alerts', 'locked', 'drafts'] as const).map((f) => (
          <button
            key={f}
            role="radio"
            aria-checked={filter === f}
            onClick={() => setFilter(f)}
            className={cn(
              'inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-[12.5px] font-medium capitalize transition-colors',
              filter === f ? 'border-sky-300/40 bg-sky-400/15 text-sky-100' : 'border-white/10 text-muted hover:text-ink',
            )}
          >
            {f}
            <span className="font-mono text-[10.5px] text-faint">{counts?.[f] ?? 0}</span>
          </button>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(300px,380px)_minmax(0,1fr)]">
        {showList && (
          <GlassPanel padding="none" className="overflow-hidden">
            {items.length === 0 ? (
              <EmptyState
                icon={Mail}
                title={list.isLoading ? 'Loading…' : 'No replies yet'}
                hint={gmail.data?.connected ? 'Replies to your applications show up here within a few minutes.'
                  : 'Connect Gmail (read-only) in Settings › Gmail to watch for replies.'}
                action={!gmail.data?.connected ? <Link to="/settings?tab=gmail" className="text-sm text-cyan-300">Connect Gmail</Link> : undefined}
              />
            ) : (
              <ul className="max-h-[70vh] divide-y divide-white/[.05] overflow-y-auto">
                {items.map((t) => (
                  <ThreadRow key={t.id} t={t} active={t.id === selected} onClick={() => select(t.id)} />
                ))}
              </ul>
            )}
          </GlassPanel>
        )}
        {showDetail && (
          <div className="min-w-0">
            {selected ? (
              <ThreadView id={selected} onBack={mobile ? () => select(null) : undefined} />
            ) : (
              <GlassPanel>
                <EmptyState icon={MailCheck} title="Pick a thread" hint="Locked threads are marked with a padlock." />
              </GlassPanel>
            )}
          </div>
        )}
      </div>

      <AlertModal thread={alertThread} onOpen={(id) => select(id)} onDone={() => qc.invalidateQueries({ queryKey: ['inbox'] })} />
    </div>
  );
}

function GmailChip({ connected, healthy, email }: { connected: boolean; healthy: boolean; email?: string }) {
  const color = connected ? (healthy ? '#34D399' : '#FBBF24') : '#64748B';
  return (
    <Link to="/settings?tab=gmail">
      <Badge color={color} icon={Mail} size="md">
        {connected ? (healthy ? email ?? 'Gmail connected' : 'Gmail needs attention') : 'Gmail not connected'}
      </Badge>
    </Link>
  );
}

function ThreadRow({ t, active, onClick }: { t: InboxThread; active: boolean; onClick: () => void }) {
  const meta = t.inbound === 0 && !t.classification ? { label: 'Sent · no reply yet', color: '#22D3EE' } : classMeta(t.classification);
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        aria-current={active}
        className={cn('flex w-full gap-3 px-4 py-3 text-left transition-colors', active ? 'bg-white/[.07]' : 'hover:bg-white/[.04]')}
      >
        <span
          className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg border"
          style={{ borderColor: withAlpha(meta.color, 0.35), backgroundColor: withAlpha(meta.color, 0.1) }}
        >
          {t.locked ? <Lock className="size-4" style={{ color: meta.color }} aria-label="locked" /> : <Mail className="size-4" style={{ color: meta.color }} aria-hidden />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="truncate text-[13.5px] font-medium text-ink">{t.opportunity?.company_name ?? t.counterpart ?? 'Unknown sender'}</span>
            <span className="ml-auto shrink-0 text-[11px] text-faint">{formatRelative(t.last_message_at)}</span>
          </span>
          <span className="mt-0.5 block truncate text-[12.5px] text-ink/80">{t.subject || '(no subject)'}</span>
          <span className="mt-0.5 line-clamp-1 text-[12px] text-muted">{t.last?.snippet}</span>
          <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <Badge size="xs" color={meta.color}>{meta.label}</Badge>
            {t.drafts > 0 && <Badge size="xs" color="#22D3EE">draft</Badge>}
            <SimTag show={t.simulated} />
          </span>
        </span>
      </button>
    </li>
  );
}

function ThreadView({ id, onBack }: { id: string; onBack?: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['thread', id], queryFn: () => api.inboxThread(id) });
  const [unlocking, setUnlocking] = useState(false);
  const t = q.data;
  if (!t) {
    return (
      <GlassPanel>
        <EmptyState icon={Mail} title={q.isError ? 'Thread not found' : 'Loading…'} />
      </GlassPanel>
    );
  }
  const meta = classMeta(t.classification);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['thread', id] });
    void qc.invalidateQueries({ queryKey: ['inbox'] });
  };
  return (
    <div className="space-y-4">
      {onBack && (
        <button type="button" onClick={onBack} className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
          <ArrowLeft className="size-4" /> Threads
        </button>
      )}
      <GlassPanel padding="lg" glow={meta.color} accentTop>
        <div className="flex flex-wrap items-center gap-2">
          <Badge color={meta.color}>{meta.label}</Badge>
          {t.opportunity && <StageChip stage={t.opportunity.stage} />}
          <SimTag show={t.simulated} />
          {t.gmail_url && (
            <a href={t.gmail_url} target="_blank" rel="noopener noreferrer" className="ml-auto inline-flex items-center gap-1 text-[12.5px] text-cyan-300 hover:underline">
              Open in Gmail <ExternalLink className="size-3.5" />
            </a>
          )}
        </div>
        <h2 className="mt-3 font-display text-xl font-semibold tracking-tight">{t.subject || '(no subject)'}</h2>
        <div className="mt-1 text-sm text-muted">
          {t.counterpart}
          {t.opportunity && (
            <>
              {' · '}
              <Link to={`/o/${t.opportunity.id}`} className="text-ink/85 hover:text-cyan-200">
                {t.opportunity.company_name} — {t.opportunity.title}
              </Link>
            </>
          )}
        </div>
        {t.locked ? (
          <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-red-400/30 bg-red-500/[.1] px-4 py-3">
            <Lock className="size-4 text-red-300" aria-hidden />
            <div className="min-w-0 flex-1 text-[13px] text-red-100">
              <b>Notify-only{t.lock_reason ? ` (${t.lock_reason})` : ''}.</b> HQ will never write on this thread — reply
              yourself from Gmail.
            </div>
            <Button size="sm" variant="ghost" icon={LockOpen} onClick={() => setUnlocking(true)}>
              Unlock…
            </Button>
          </div>
        ) : t.unlocked_at ? (
          <p className="mt-3 text-[12px] text-amber-200/80">Unlocked by you {formatRelative(t.unlocked_at)} (audited).</p>
        ) : null}
      </GlassPanel>

      <div className="space-y-3">
        {t.items.map((m) => {
          const mine = m.direction === 'outbound';
          const mm = classMeta(m.classification);
          return (
            <article
              key={m.id}
              className={cn('rounded-2xl border p-4 text-[13.5px]', mine ? 'ml-6 border-cyan-300/15 bg-cyan-400/[.05] sm:ml-16' : 'mr-6 border-white/10 bg-white/[.03] sm:mr-16')}
            >
              <header className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-muted">
                <span className="font-medium text-ink/90">{mine ? 'You (via HQ)' : m.from_addr}</span>
                <span>→ {m.to_addr}</span>
                <span className="ml-auto" title={formatDateTimeIST(m.date)}>{formatRelative(m.date)}</span>
              </header>
              <pre className="mt-2 font-sans whitespace-pre-wrap text-ink/85">{m.body}</pre>
              {!mine && m.classification && (
                <footer className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-white/[.06] pt-2 text-[11.5px] text-muted">
                  <Badge size="xs" color={mm.color}>{mm.label}</Badge>
                  {m.confidence != null && <span>{Math.round(m.confidence * 100)}%</span>}
                  {m.lock_terms.map((x) => (
                    <span key={x} className="rounded bg-red-500/15 px-1.5 text-red-200">{x}</span>
                  ))}
                  {m.reason && <span className="truncate">· {m.reason}</span>}
                </footer>
              )}
            </article>
          );
        })}
      </div>

      {t.reply_drafts.map((d) => (
        <DraftEditor key={d.id} d={d} locked={t.locked} onChanged={refresh} />
      ))}

      <UnlockDialog open={unlocking} onClose={() => setUnlocking(false)} threadId={t.id} onDone={refresh} />
    </div>
  );
}

function DraftEditor({ d, locked, onChanged }: { d: ReplyDraft; locked: boolean; onChanged: () => void }) {
  const [text, setText] = useState(d.text ?? '');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => setText(d.text ?? ''), [d.text]);
  const editable = d.status === 'draft' || d.status === 'approved';
  const dirty = text !== (d.text ?? '');
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      const detail = e instanceof ApiError ? (e.detail as { sentences?: { text: string; rules: string[] }[] } | undefined) : undefined;
      setErr(detail?.sentences ? detail.sentences.map((s) => `${s.rules.join(', ')}: “${s.text}”`).join(' · ') : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <GlassPanel>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-display text-sm font-semibold">Reply draft</span>
        <Badge size="xs" color={d.status === 'sent' ? '#34D399' : d.status === 'failed' ? '#F87171' : '#22D3EE'}>{d.status}</Badge>
        <span className="text-[12px] text-muted">{d.subject}</span>
        <span className="ml-auto text-[11.5px] text-faint">by {d.author === 'prerit' ? 'you' : 'HQ (template, fact-checked)'}</span>
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={!editable || busy}
        rows={Math.min(14, Math.max(6, text.split('\n').length + 1))}
        aria-label="Reply draft text"
        className="mt-3 w-full rounded-xl border border-white/10 bg-black/25 px-3 py-2.5 font-sans text-[13.5px] leading-relaxed text-ink focus:border-cyan-300/50 focus:outline-none disabled:opacity-70"
      />
      {err && <p className="mt-2 text-[12.5px] text-rose-300">{err}</p>}
      {editable && (
        <div className="mt-3 flex flex-wrap gap-2">
          {dirty && <Button size="sm" variant="secondary" loading={busy} onClick={() => act(() => api.editDraft(d.id, text))}>Save edits</Button>}
          <Button size="sm" icon={Send} disabled={locked || dirty} loading={busy} onClick={() => act(() => api.sendDraft(d.id))}
            title={locked ? 'Locked thread — reply from Gmail' : dirty ? 'Save your edits first' : undefined}>
            Send reply
          </Button>
          <Button size="sm" variant="ghost" icon={Trash2} disabled={busy} onClick={() => act(() => api.discardDraft(d.id))}>
            Discard
          </Button>
        </div>
      )}
    </GlassPanel>
  );
}

function UnlockDialog({ open, onClose, threadId, onDone }: { open: boolean; onClose: () => void; threadId: string; onDone: () => void }) {
  const [text, setText] = useState('');
  const [err, setErr] = useState<string | null>(null);
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <motion.div role="dialog" aria-modal aria-label="Unlock thread" initial={{ y: 12, scale: 0.98 }} animate={{ y: 0, scale: 1 }}
            className="w-full max-w-md rounded-2xl border border-white/10 bg-[#0B111D] p-5 shadow-2xl">
            <h3 className="font-display text-lg font-semibold">Unlock this thread?</h3>
            <p className="mt-2 text-[13px] text-muted">
              HQ could then draft or send on it again (still through every gate). Interviews, offers, money and legal mail
              are normally yours alone. This is recorded in the audit log.
            </p>
            <label className="mt-4 block text-[12px] text-muted" htmlFor="unlock-confirm">Type UNLOCK</label>
            <input id="unlock-confirm" value={text} onChange={(e) => setText(e.target.value)} autoFocus
              className="mt-1 w-full rounded-xl border border-white/10 bg-white/[.04] px-3 py-2 font-mono text-sm focus:border-red-300/50 focus:outline-none" />
            {err && <p className="mt-2 text-[12.5px] text-rose-300">{err}</p>}
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" onClick={onClose}>Cancel</Button>
              <Button variant="danger" disabled={text !== 'UNLOCK'} onClick={async () => {
                try {
                  await api.unlockThread(threadId);
                  onDone();
                  onClose();
                } catch (e) {
                  setErr(e instanceof Error ? e.message : String(e));
                }
              }}>Unlock</Button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function AlertModal({ thread, onOpen, onDone }: { thread: InboxThread | undefined; onOpen: (id: string) => void; onDone: () => void }) {
  const [hidden, setHidden] = useState<string | null>(null);
  const t = thread && thread.id !== hidden ? thread : undefined;
  const offer = t?.classification === 'offer';
  const color = offer ? '#F5C451' : '#F87171';
  const ack = useMemo(() => async (open: boolean) => {
    if (!t) return;
    setHidden(t.id);
    try {
      await api.ackThreadAlert(t.id);
    } finally {
      if (open) onOpen(t.id);
      onDone();
    }
  }, [t, onOpen, onDone]);
  return (
    <AnimatePresence>
      {t && (
        <motion.div className="fixed inset-0 z-50 grid place-items-center bg-black/65 p-4 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <motion.div role="alertdialog" aria-modal aria-label={offer ? 'Offer received' : 'Interview request'}
            initial={{ y: 16, scale: 0.97 }} animate={{ y: 0, scale: 1 }}
            className="w-full max-w-md overflow-hidden rounded-2xl border bg-[#0B111D] shadow-2xl"
            style={{ borderColor: withAlpha(color, 0.5), boxShadow: `0 0 60px -12px ${withAlpha(color, 0.6)}` }}>
            <div className="px-5 py-4" style={{ background: `linear-gradient(180deg, ${withAlpha(color, 0.18)}, transparent)` }}>
              <div className="font-mono text-[11px] tracking-[0.16em] uppercase" style={{ color }}>{offer ? 'Offer' : 'Interview request'}</div>
              <h3 className="mt-1 font-display text-xl font-semibold">{t.opportunity?.company_name ?? t.counterpart}</h3>
              <p className="mt-1 text-[13px] text-ink/80">{t.subject}</p>
            </div>
            <div className="space-y-3 px-5 pb-5 text-[13px] text-muted">
              <p>{t.last?.snippet}</p>
              <p className="rounded-lg border border-white/10 bg-white/[.04] px-3 py-2 text-ink/85">
                This is yours: HQ is locked out of the thread and won't reply, schedule or negotiate. Reply from Gmail.
              </p>
              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={() => ack(false)}>Got it</Button>
                <Button variant="primary" onClick={() => ack(true)}>Open thread</Button>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
