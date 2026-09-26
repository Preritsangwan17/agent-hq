/**
 * Agent cards: one per agent with its live "now" line (typed in character by character when it changes),
 * progress, tok/s, model and today's counters. Live values come from `live[agentId]` (~4 updates/s per agent).
 */
import { Bot, Cpu, Sparkles } from 'lucide-react';
import { memo, useMemo } from 'react';
import { Link } from 'react-router';
import { AgentAvatar, GlassPanel, ProgressBar, SectionHeader } from '@/components';
import { formatCompact } from '@/lib/format';
import { useAgentsList, useHQ, useIsPaused } from '@/lib/store';
import type { Agent } from '@/lib/types';
import { withAlpha } from '@/theme/tokens';
import { STATE_META, modelLabel, shortName, stateLabel, visualState } from './util';

export function AgentCards() {
  const agents = useAgentsList();
  const working = agents.filter((a) => a.status === 'working').length;
  return (
    <GlassPanel padding="lg" glow="#A78BFA" glowStrength={0.2}>
      <SectionHeader
        kicker="Team"
        title="Agents"
        icon={Bot}
        color="#A78BFA"
        right={
          <Link to="/agents" className="text-xs font-medium text-cyan-300 hover:text-cyan-200">
            Manage · {working} working
          </Link>
        }
      />
      <div className="mt-4 grid gap-2.5 sm:grid-cols-2 2xl:grid-cols-3">
        {agents.map((a) => (
          <AgentCard key={a.id} agent={a} />
        ))}
      </div>
    </GlassPanel>
  );
}

const AgentCard = memo(function AgentCard({ agent }: { agent: Agent }) {
  const live = useHQ((s) => s.live[agent.id]);
  const paused = useIsPaused();
  const state = visualState(agent, paused);
  const meta = STATE_META[state];
  const working = state === 'working';
  const model = live?.model_id ?? agent.model;
  const cloud = agent.cost_tier === 'cloud';
  const line = working ? live?.now_line ?? 'Starting…' : agent.last_error && state === 'error' ? agent.last_error : null;

  return (
    <div
      className="relative min-w-0 overflow-hidden rounded-xl border p-3 transition-[border-color,background-color] duration-300"
      style={{
        borderColor: working ? withAlpha(agent.color, 0.35) : 'rgba(255,255,255,0.06)',
        backgroundColor: working ? withAlpha(agent.color, 0.05) : 'rgba(255,255,255,0.02)',
      }}
    >
      {working && (
        <span
          aria-hidden
          className="cc-sweep pointer-events-none absolute inset-y-0 left-0 w-1/3"
          style={{ background: `linear-gradient(90deg, transparent, ${withAlpha(agent.color, 0.08)}, transparent)` }}
        />
      )}
      <div className="relative flex items-center gap-3">
        <AgentAvatar agent={agent} size="md" working={working} showStatus />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-[13.5px] font-medium text-ink">{shortName(agent.name)}</span>
            <span className="shrink-0 text-[10.5px] font-medium uppercase tracking-[0.12em]" style={{ color: meta.color }}>
              {stateLabel(agent, state)}
            </span>
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 truncate font-mono text-[10.5px] text-faint">
            {cloud ? <Sparkles className="size-3 shrink-0 text-fuchsia-300/80" aria-hidden /> : <Cpu className="size-3 shrink-0" aria-hidden />}
            <span className="truncate">{modelLabel(model)}</span>
            <span aria-hidden>·</span>
            <span className="shrink-0">{agent.adapter}</span>
          </div>
        </div>
      </div>
      <div className="relative mt-2.5 h-4 truncate font-mono text-[11px] text-ink/80">
        {line ? <NowLine text={line} color={agent.color} typing={working} /> : <span className="text-faint">{state === 'paused' ? 'paused' : 'waiting for work'}</span>}
      </div>
      <ProgressBar className="relative mt-2" value={working ? live?.progress ?? null : 0} color={agent.color} height={3} />
      <div className="relative mt-2 flex items-center justify-between font-mono text-[10.5px] text-muted tabular">
        <span>
          <span className="text-ink/90">{agent.tasks_today}</span> tasks
          {agent.errors_today > 0 && <span className="text-red-300"> · {agent.errors_today} err</span>}
        </span>
        <span>
          {working && live?.tok_s ? (
            <span style={{ color: agent.color }}>{Math.round(live.tok_s)} tok/s</span>
          ) : (
            <>{formatCompact(agent.tokens_today)} tok</>
          )}
        </span>
      </div>
    </div>
  );
});

/** Types the line in (CSS per-character delay) whenever it changes; the key restarts the animation. */
function NowLine({ text, color, typing }: { text: string; color: string; typing: boolean }) {
  const chars = useMemo(() => [...text.slice(0, 90)], [text]);
  if (!typing) return <span className="text-red-300/90">{text}</span>;
  return (
    <span key={text} aria-label={text}>
      {chars.map((c, i) => (
        <span key={i} className="cc-ch" style={{ animationDelay: `${i * 14}ms` }} aria-hidden>
          {c}
        </span>
      ))}
      <span className="cc-caret ml-0.5 align-[-1px]" style={{ backgroundColor: color, animationDelay: `${chars.length * 14}ms` }} aria-hidden />
    </span>
  );
}
