/**
 * Run drawer for one event: level/type header, who/when/what meta, links to the opportunity, the other events of
 * the same task run, and the raw event JSON (syntax-colored, copyable). Right-side panel on desktop, bottom sheet
 * on phones. Rendered in a portal so page transforms never offset its fixed positioning. Esc closes.
 */
import { AnimatePresence, motion } from 'motion/react';
import { ArrowUpRight, Check, Copy, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router';
import { AgentAvatar } from '@/components';
import { cn } from '@/lib/cn';
import { formatClockIST, formatDateTimeIST, formatRelative } from '@/lib/format';
import { useOpp } from '@/lib/store';
import type { Agent, HQEvent } from '@/lib/types';
import { withAlpha } from '@/theme/tokens';
import { agentTag } from './LogRow';
import { LEVEL_META } from './model';

export interface EventDrawerProps {
  event: HQEvent | null;
  onClose: () => void;
  onSelect: (e: HQEvent) => void;
  log: readonly HQEvent[];
  agents: Readonly<Record<string, Agent>>;
  mobile: boolean;
  now: number;
}

export function EventDrawer(props: EventDrawerProps) {
  const { event, onClose, mobile } = props;
  useEffect(() => {
    if (!event) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [event, onClose]);

  return createPortal(
    <AnimatePresence>
      {event && (
        <motion.div key="drawer" className="fixed inset-0 z-[80]" initial={{ opacity: 1 }} exit={{ opacity: 1 }}>
          <motion.button
            type="button"
            aria-label="Close event details"
            className="absolute inset-0 bg-[#03060C]/60 backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            onClick={onClose}
          />
          <motion.aside
            role="dialog"
            aria-modal="true"
            aria-label="Event details"
            className={cn(
              'absolute flex flex-col border-white/10 bg-[#0A101C]/95 shadow-[0_0_80px_-20px_rgba(0,0,0,0.9)] backdrop-blur-2xl',
              mobile ? 'inset-x-0 bottom-0 max-h-[86dvh] rounded-t-2xl border-t' : 'inset-y-0 right-0 w-[min(540px,100vw)] border-l',
            )}
            initial={mobile ? { y: '100%' } : { x: '100%' }}
            animate={mobile ? { y: 0 } : { x: 0 }}
            exit={mobile ? { y: '100%' } : { x: '100%' }}
            transition={{ type: 'spring', stiffness: 420, damping: 42 }}
          >
            <DrawerBody {...props} event={event} />
          </motion.aside>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}

function DrawerBody({ event: e, onClose, onSelect, log, agents, mobile, now }: EventDrawerProps & { event: HQEvent }) {
  const lv = LEVEL_META[e.level] ?? LEVEL_META.info;
  const tag = agentTag(e, agents);
  const agent = e.agent_id ? agents[e.agent_id] : undefined;
  const opp = useOpp(e.opportunity_id);
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => closeRef.current?.focus({ preventScroll: true }), []);

  const run = useMemo(() => (e.task_id ? log.filter((x) => x.task_id === e.task_id) : []), [log, e.task_id]);
  const json = useMemo(() => JSON.stringify(e, null, 2), [e]);

  return (
    <>
      {mobile && <div className="mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-white/15" aria-hidden />}
      <header className="flex items-start gap-3 border-b border-white/[.07] px-5 pb-4 pt-4">
        {agent ? (
          <AgentAvatar agent={agent} size="md" />
        ) : (
          <span className="grid size-9 shrink-0 place-items-center rounded-full border border-white/10 bg-white/[.04] font-mono text-[10px] text-muted">
            sys
          </span>
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className="inline-flex h-5 items-center rounded-md border px-1.5 font-mono text-[10.5px] font-semibold uppercase tracking-wider"
              style={{ color: lv.color, borderColor: withAlpha(lv.color, 0.35), backgroundColor: withAlpha(lv.color, 0.1) }}
            >
              {lv.label}
            </span>
            <span className="font-mono text-[12px] text-ink/90">{e.type}</span>
          </div>
          <p className="mt-1.5 break-words text-[13.5px] leading-snug" style={{ color: lv.text }}>
            {e.message}
          </p>
        </div>
        <button
          ref={closeRef}
          type="button"
          onClick={onClose}
          className="grid size-8 shrink-0 place-items-center rounded-lg text-muted transition-colors hover:bg-white/[.07] hover:text-ink"
          aria-label="Close"
        >
          <X className="size-4" aria-hidden />
        </button>
      </header>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain px-5 py-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
        <dl className="grid grid-cols-[92px_minmax(0,1fr)] gap-x-3 gap-y-2 text-[12.5px]">
          <Meta k="When">
            <span className="text-ink">{formatDateTimeIST(e.ts)} IST</span>
            <span className="text-faint"> · {formatRelative(e.ts, now)}</span>
          </Meta>
          <Meta k="Agent">
            <span style={{ color: tag.color }}>{agent?.name ?? tag.name}</span>
          </Meta>
          <Meta k="Event id">
            <span className="font-mono text-ink/85">#{e.id}</span>
          </Meta>
          {e.opportunity_id && (
            <Meta k="Opportunity">
              <Link to={`/o/${e.opportunity_id}`} className="inline-flex items-center gap-1 text-cyan-300 hover:text-cyan-200" onClick={onClose}>
                <span className="truncate">{opp ? `${opp.company_name} · ${opp.title}` : e.opportunity_id}</span>
                <ArrowUpRight className="size-3.5 shrink-0" aria-hidden />
              </Link>
            </Meta>
          )}
          {e.task_id && (
            <Meta k="Task">
              <span className="break-all font-mono text-[11.5px] text-ink/80">{e.task_id}</span>
            </Meta>
          )}
        </dl>

        {run.length > 1 && (
          <section>
            <h4 className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted">This run · {run.length} events</h4>
            <ol className="relative space-y-0.5 border-l border-white/10 pl-3">
              {run.map((x) => {
                const l = LEVEL_META[x.level] ?? LEVEL_META.info;
                const cur = x.id === e.id;
                return (
                  <li key={x.id}>
                    <button
                      type="button"
                      onClick={() => onSelect(x)}
                      className={cn(
                        'relative flex w-full items-center gap-2 rounded-md px-2 py-1 text-left font-mono text-[11.5px] transition-colors hover:bg-white/[.05]',
                        cur && 'bg-cyan-300/[.08]',
                      )}
                    >
                      <span className="absolute -left-[17px] size-2 rounded-full border-2 border-[#0A101C]" style={{ backgroundColor: l.color }} />
                      <span className="shrink-0 tabular text-faint">{formatClockIST(x.ts)}</span>
                      <span className="shrink-0" style={{ color: l.color }}>
                        {x.type}
                      </span>
                      <span className="min-w-0 truncate text-muted">{x.message}</span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </section>
        )}

        <section>
          <div className="mb-2 flex items-center justify-between">
            <h4 className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted">Event JSON</h4>
            <CopyButton text={json} />
          </div>
          <pre className="overflow-x-auto rounded-xl border border-white/[.07] bg-[#060A12] p-3.5 font-mono text-[11.5px] leading-[1.6] text-ink/85">
            <code>{highlightJson(json)}</code>
          </pre>
        </section>
      </div>
    </>
  );
}

function Meta({ k, children }: { k: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-faint">{k}</dt>
      <dd className="min-w-0 truncate">{children}</dd>
    </>
  );
}

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (!done) return;
    const t = setTimeout(() => setDone(false), 1400);
    return () => clearTimeout(t);
  }, [done]);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(
          () => setDone(true),
          () => undefined,
        );
      }}
      className="inline-flex h-7 items-center gap-1.5 rounded-lg border border-white/10 bg-white/[.04] px-2.5 text-xs text-muted transition-colors hover:text-ink"
    >
      {done ? <Check className="size-3.5 text-emerald-300" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
      {done ? 'Copied' : 'Copy'}
    </button>
  );
}

const JSON_TOKEN = /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;

/** Minimal JSON syntax coloring: keys, strings, numbers, literals. */
export function highlightJson(src: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let k = 0;
  for (const m of src.matchAll(JSON_TOKEN)) {
    const i = m.index ?? 0;
    if (i > last) out.push(src.slice(last, i));
    if (m[1] && m[2]) {
      out.push(
        <span key={k++} className="text-sky-300">
          {m[1]}
        </span>,
        m[2],
      );
    } else if (m[1]) {
      out.push(
        <span key={k++} className="text-lime-200/90">
          {m[1]}
        </span>,
      );
    } else if (m[3]) {
      out.push(
        <span key={k++} className="text-rose-300">
          {m[3]}
        </span>,
      );
    } else if (m[4]) {
      out.push(
        <span key={k++} className="text-violet-300">
          {m[4]}
        </span>,
      );
    }
    last = i + m[0].length;
  }
  if (last < src.length) out.push(src.slice(last));
  return out;
}
