/**
 * Notifications center (CONTRACT_D §6): a bell with the unacknowledged count; the panel lists the latest
 * notifications (alerts first-class), each linking to where it matters. Opening an item marks it read.
 */
import { useQuery } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'motion/react';
import { Bell, BellRing, CheckCheck, ShieldAlert, TriangleAlert, Info } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { api } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatRelative } from '@/lib/format';
import { useHQ } from '@/lib/store';
import type { NotificationRow } from '@/lib/types';

const TONE = {
  alert: { color: '#F87171', Icon: ShieldAlert },
  warn: { color: '#FBBF24', Icon: TriangleAlert },
  info: { color: '#22D3EE', Icon: Info },
} as const;

export function NotificationBell({ compact }: { compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const unacked = useHQ((s) => s.notificationsUnacked);
  const setUnacked = useHQ((s) => s.setNotificationsUnacked);
  const ref = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ['notifications', unacked], queryFn: api.notifications, enabled: open });

  useEffect(() => {
    if (q.data) setUnacked(q.data.unacked);
  }, [q.data, setUnacked]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('pointerdown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const openItem = async (n: NotificationRow) => {
    setOpen(false);
    if (!n.acknowledged_at) {
      try {
        const r = await api.ackNotification(n.id);
        setUnacked(r.unacked);
      } catch {
        /* the list refreshes next time */
      }
    }
    if (n.url) {
      if (n.url.startsWith('/')) navigate(n.url);
      else window.open(n.url, '_blank', 'noopener');
    }
  };

  const ackAll = async () => {
    const r = await api.ackAllNotifications();
    setUnacked(r.unacked);
    void q.refetch();
  };

  const ringing = unacked > 0;
  const BellIcon = ringing ? BellRing : Bell;
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`Notifications${unacked ? ` (${unacked} unread)` : ''}`}
        className={cn(
          'relative grid place-items-center rounded-xl border border-white/10 bg-white/[.04] text-muted transition-colors hover:border-white/20 hover:text-ink',
          compact ? 'size-9' : 'size-10',
        )}
      >
        <BellIcon className={cn('size-[18px]', ringing && 'text-amber-300')} aria-hidden />
        {ringing && (
          <span className="absolute -top-1 -right-1 grid h-[18px] min-w-[18px] place-items-center rounded-full bg-amber-400 px-1 font-mono text-[10px] font-bold text-[#1a1203] shadow-[0_0_12px_rgba(251,191,36,0.7)]">
            {unacked > 99 ? '99+' : unacked}
          </span>
        )}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            role="dialog"
            aria-label="Notifications"
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ duration: 0.14 }}
            className="fixed inset-x-3 top-16 z-50 origin-top-right overflow-hidden rounded-2xl border border-white/10 bg-[#0B111D]/95 shadow-[0_24px_60px_-12px_rgba(0,0,0,0.9)] backdrop-blur-xl sm:absolute sm:inset-x-auto sm:top-12 sm:right-0 sm:w-[380px]"
          >
            <div className="flex items-center justify-between border-b border-white/[.07] px-4 py-2.5">
              <span className="font-display text-sm font-semibold">Notifications</span>
              <button
                type="button"
                onClick={ackAll}
                disabled={!unacked}
                className="inline-flex items-center gap-1 text-[12px] text-muted transition-colors hover:text-ink disabled:opacity-40"
              >
                <CheckCheck className="size-3.5" aria-hidden /> Mark all read
              </button>
            </div>
            <ul className="max-h-[60vh] overflow-y-auto">
              {(q.data?.items ?? []).map((n) => {
                const tone = TONE[n.severity] ?? TONE.info;
                return (
                  <li key={n.id}>
                    <button
                      type="button"
                      onClick={() => openItem(n)}
                      className={cn('flex w-full gap-3 px-4 py-3 text-left transition-colors hover:bg-white/[.05]',
                        !n.acknowledged_at && 'bg-white/[.025]')}
                    >
                      <tone.Icon className="mt-0.5 size-4 shrink-0" style={{ color: tone.color }} aria-hidden />
                      <span className="min-w-0 flex-1">
                        <span className={cn('block text-[13px] leading-snug', n.acknowledged_at ? 'text-ink/70' : 'font-medium text-ink')}>
                          {n.title}
                        </span>
                        {n.body && <span className="mt-0.5 block text-[12px] leading-snug text-muted">{n.body}</span>}
                        <span className="mt-1 block text-[11px] text-faint">{formatRelative(n.created_at)}</span>
                      </span>
                      {!n.acknowledged_at && <span className="mt-1.5 size-2 shrink-0 rounded-full" style={{ backgroundColor: tone.color }} aria-label="unread" />}
                    </button>
                  </li>
                );
              })}
              {q.isLoading && <li className="px-4 py-6 text-center text-sm text-muted">Loading…</li>}
              {q.data && q.data.items.length === 0 && (
                <li className="px-4 py-8 text-center text-sm text-muted">Nothing yet. Interview and offer alerts show up here.</li>
              )}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function RefusalBanner({ reason }: { reason: string | null | undefined }) {
  const navigate = useNavigate();
  if (!reason) return null;
  return (
    <div role="alert" className="border-b border-red-500/30 bg-red-500/[.12] px-4 py-2.5 text-[13px] text-red-100 md:px-6 lg:px-8">
      <b>The worker refused to start.</b> {reason}{' '}
      <button type="button" onClick={() => navigate('/settings?tab=gmail')} className="underline underline-offset-2">
        Open Settings › Gmail
      </button>
    </div>
  );
}
