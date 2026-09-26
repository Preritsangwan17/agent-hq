/** One agent on the Agents page: identity, live state, model, capabilities, schedule and quick controls. */
import { Cpu, Lock, Pencil, Sparkles, Trash2 } from 'lucide-react';
import { memo, useState } from 'react';
import { AgentAvatar, Badge, GlassPanel, ProgressBar } from '@/components';
import { api } from '@/lib/api';
import { formatCompact } from '@/lib/format';
import { patchAgent, useHQ, useIsPaused } from '@/lib/store';
import type { Agent, Capability } from '@/lib/types';
import { withAlpha } from '@/theme/tokens';
import { STATE_META, modelLabel, stateLabel, visualState } from '@/pages/CommandCenter/util';
import { ConfirmButton, Switch } from './formKit';
import { describeSchedule } from './schedule';

export const AgentManagerCard = memo(function AgentManagerCard({
  agent,
  capMeta,
  onEdit,
}: {
  agent: Agent;
  capMeta: Record<string, Capability>;
  onEdit: (id: string) => void;
}) {
  const live = useHQ((s) => s.live[agent.id]);
  const globalPause = useIsPaused();
  const state = visualState(agent, globalPause);
  const meta = STATE_META[state];
  const [err, setErr] = useState<string | null>(null);
  const working = state === 'working';

  const toggle = async (patch: { paused?: boolean; enabled?: boolean }) => {
    setErr(null);
    try {
      await patchAgent(agent.id, patch);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Update failed');
    }
  };

  return (
    <GlassPanel padding="md" glow={agent.color} glowStrength={working ? 0.35 : 0.15} className="flex min-w-0 flex-col">
      <div className="flex items-start gap-3">
        <AgentAvatar agent={agent} size="lg" working={working} showStatus />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <h3 className="truncate font-display text-[15px] font-semibold text-ink">{agent.name}</h3>
            {agent.builtin && (
              <Badge size="xs" color="#8B95A7">
                built-in
              </Badge>
            )}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px]">
            <span className="font-medium" style={{ color: meta.color }}>
              {stateLabel(agent, state)}
            </span>
            <span className="text-faint">·</span>
            <span className="inline-flex items-center gap-1 font-mono text-muted">
              {agent.cost_tier === 'claude' ? <Sparkles className="size-3 text-fuchsia-300" aria-hidden /> : <Cpu className="size-3" aria-hidden />}
              {agent.cost_tier === 'claude' ? 'Claude' : modelLabel(live?.model_id ?? agent.model)}
            </span>
            <span className="text-faint">·</span>
            <span className="font-mono text-faint">{agent.adapter}</span>
          </div>
        </div>
        <button
          type="button"
          onClick={() => onEdit(agent.id)}
          className="grid size-8 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/[.03] text-muted hover:bg-white/[.08] hover:text-ink"
          aria-label={`Edit ${agent.name}`}
        >
          <Pencil className="size-3.5" />
        </button>
      </div>

      {agent.description && <p className="mt-3 line-clamp-2 text-[12.5px] leading-relaxed text-muted">{agent.description}</p>}

      <div className="mt-3 flex flex-wrap gap-1">
        {agent.capabilities.map((c) => {
          const side = agent.side_effects.includes(c);
          return (
            <span
              key={c}
              title={capMeta[c]?.description ?? c}
              className="inline-flex h-5 items-center gap-1 rounded-md border px-1.5 font-mono text-[10.5px]"
              style={
                side
                  ? { borderColor: withAlpha('#F472B6', 0.4), backgroundColor: withAlpha('#F472B6', 0.1), color: '#F9A8D4' }
                  : { borderColor: withAlpha(agent.color, 0.22), backgroundColor: withAlpha(agent.color, 0.06), color: withAlpha(agent.color, 0.95) }
              }
            >
              {side && <Lock className="size-2.5" aria-label="side effect" />}
              {c}
            </span>
          );
        })}
      </div>

      <div className="mt-3 h-4 truncate font-mono text-[11px] text-ink/75">{working ? live?.now_line ?? '…' : agent.last_error && state === 'error' ? <span className="text-red-300">{agent.last_error}</span> : <span className="text-faint">{describeSchedule(agent.schedule)} · ×{agent.concurrency}</span>}</div>
      <ProgressBar className="mt-1.5" value={working ? live?.progress ?? null : 0} color={agent.color} height={3} />

      <div className="mt-3 grid grid-cols-4 gap-2 text-center font-mono text-[10.5px] text-faint">
        <Stat label="tasks" value={agent.tasks_today} />
        <Stat label="errors" value={agent.errors_today} warn={agent.errors_today > 0} />
        <Stat label="tokens" value={formatCompact(agent.tokens_today)} />
        <Stat label="restarts" value={agent.restarts} />
      </div>

      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-white/[.06] pt-3">
        <div className="flex items-center gap-4">
          <label className="inline-flex items-center gap-2 text-xs text-muted">
            <Switch size="sm" label={`${agent.name} enabled`} checked={agent.enabled} onChange={(v) => void toggle({ enabled: v })} color={agent.color} />
            Enabled
          </label>
          <label className="inline-flex items-center gap-2 text-xs text-muted">
            <Switch size="sm" label={`${agent.name} running`} checked={!agent.paused} onChange={(v) => void toggle({ paused: !v })} color="#34D399" disabled={!agent.enabled} />
            {agent.paused ? 'Paused' : 'Running'}
          </label>
        </div>
        {!agent.builtin && (
          <ConfirmButton
            icon={Trash2}
            color="#F87171"
            className="h-8 px-2.5 text-xs"
            confirmLabel="Remove?"
            onConfirm={async () => {
              try {
                await api.deleteAgent(agent.id);
              } catch (e) {
                setErr(e instanceof Error ? e.message : 'Delete failed');
              }
            }}
          >
            Remove
          </ConfirmButton>
        )}
      </div>
      {agent.side_effects.length > 0 && agent.paused && (
        <p className="mt-2 text-[11px] text-amber-200/90">Paused: {agent.side_effects.join(', ')} are held system-wide until resumed.</p>
      )}
      {err && <p className="mt-2 text-xs text-red-300">{err}</p>}
    </GlassPanel>
  );
});

function Stat({ label, value, warn }: { label: string; value: number | string; warn?: boolean }) {
  return (
    <div className="rounded-lg border border-white/[.05] bg-white/[.02] py-1.5">
      <div className={`text-[13px] font-semibold tabular ${warn ? 'text-red-300' : 'text-ink/90'}`}>{value}</div>
      <div className="uppercase tracking-wider">{label}</div>
    </div>
  );
}
