/**
 * One terminal line: IST clock, agent tag (agent color), level, event type, message (search matches marked) and a
 * relative time. Desktop = one fixed grid line; phones = two lines (meta, then the message wrapped to 2 lines).
 */
import { memo, type ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { formatClockIST, formatDateTimeIST, formatRelative } from '@/lib/format';
import type { Agent, HQEvent } from '@/lib/types';
import { agentColor, withAlpha } from '@/theme/tokens';
import { LEVEL_META } from './model';

export interface RowContext {
  now: number;
  q: string;
  selectedId: number | null;
  onOpen: (e: HQEvent) => void;
  mobile: boolean;
  agents: Readonly<Record<string, Agent>>;
  /** events newer than this id that are < 2 s old fade in */
  liveAfterId: number;
}

export function agentTag(e: HQEvent, agents: Readonly<Record<string, Agent>>): { name: string; color: string } {
  if (!e.agent_id) return { name: 'system', color: '#8B95A7' };
  const a = agents[e.agent_id];
  return { name: e.agent_id, color: a?.color ?? agentColor(e.agent_id) };
}

export function Highlight({ text, q }: { text: string; q: string }): ReactNode {
  const needle = q.trim();
  if (!needle) return text;
  const lower = text.toLowerCase();
  const n = needle.toLowerCase();
  const parts: ReactNode[] = [];
  let i = 0;
  let k = 0;
  for (;;) {
    const j = lower.indexOf(n, i);
    if (j < 0) break;
    if (j > i) parts.push(text.slice(i, j));
    parts.push(
      <mark key={k++} className="rounded-[3px] bg-cyan-300/25 px-px text-cyan-50">
        {text.slice(j, j + n.length)}
      </mark>,
    );
    i = j + n.length;
  }
  if (!parts.length) return text;
  if (i < text.length) parts.push(text.slice(i));
  return parts;
}

export const LogRow = memo(function LogRow({ e, ctx }: { e: HQEvent; ctx: RowContext }) {
  const lv = LEVEL_META[e.level] ?? LEVEL_META.info;
  const tag = agentTag(e, ctx.agents);
  const selected = ctx.selectedId === e.id;
  const fresh = e.id > ctx.liveAfterId && ctx.now - Date.parse(e.ts) < 2500;
  const tint =
    e.level === 'error' ? 'rgba(248,113,113,0.06)' : e.level === 'alert' ? 'rgba(232,121,249,0.06)' : e.level === 'warn' ? 'rgba(251,191,36,0.035)' : undefined;

  return (
    <button
      type="button"
      onClick={() => ctx.onOpen(e)}
      className={cn(
        'group relative block w-full text-left font-mono text-[12px] leading-[18px] outline-none transition-colors duration-100',
        'hover:bg-white/[.045] focus-visible:bg-white/[.06]',
        selected && '!bg-cyan-300/[.09]',
        fresh && 'hq-row-in',
      )}
      style={{ backgroundColor: selected ? undefined : tint }}
      aria-label={`${lv.label} ${e.type}: ${e.message}`}
    >
      <span
        aria-hidden
        className="absolute inset-y-0 left-0 w-[2px] transition-opacity"
        style={{ backgroundColor: selected ? '#67E8F9' : lv.color, opacity: selected ? 1 : e.level === 'debug' || e.level === 'info' ? 0.35 : 0.9 }}
      />
      {ctx.mobile ? (
        <span className="block px-3 py-1.5">
          <span className="flex items-center gap-2 text-[10.5px]">
            <span className="tabular text-faint">{formatClockIST(e.ts)}</span>
            <span className="max-w-[40%] truncate font-medium" style={{ color: tag.color }}>
              {tag.name}
            </span>
            <span className="font-semibold" style={{ color: lv.color }}>
              {lv.label}
            </span>
            <span className="min-w-0 truncate text-faint">{e.type}</span>
            <span className="ml-auto shrink-0 tabular text-faint">{formatRelative(e.ts, ctx.now)}</span>
          </span>
          <span className="mt-0.5 line-clamp-2 break-words text-[12px]" style={{ color: lv.text }}>
            <Highlight text={e.message} q={ctx.q} />
          </span>
        </span>
      ) : (
        <span className="grid h-[26px] grid-cols-[62px_104px_42px_128px_minmax(0,1fr)_64px] items-center gap-3 pl-4 pr-4">
          <span className="tabular text-faint" title={`${formatDateTimeIST(e.ts)} IST`}>
            {formatClockIST(e.ts)}
          </span>
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="size-1.5 shrink-0 rounded-full" style={{ backgroundColor: tag.color, boxShadow: `0 0 6px ${withAlpha(tag.color, 0.8)}` }} />
            <span className="truncate" style={{ color: tag.color }}>
              {tag.name}
            </span>
          </span>
          <span className="font-semibold uppercase tracking-wide text-[10.5px]" style={{ color: lv.color }}>
            {lv.short}
          </span>
          <span className="truncate text-[11px] text-faint group-hover:text-muted">{e.type}</span>
          <span className="truncate" style={{ color: lv.text }}>
            <Highlight text={e.message} q={ctx.q} />
          </span>
          <span className="truncate text-right text-[11px] tabular text-faint">{formatRelative(e.ts, ctx.now)}</span>
        </span>
      )}
    </button>
  );
});
