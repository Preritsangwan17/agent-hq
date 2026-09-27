import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router';
import { Cpu, RefreshCw, ShieldCheck, Sparkles, Workflow } from 'lucide-react';
import { api } from '@/lib/api';
import { useHQ } from '@/lib/store';
import { Badge, Button, GlassPanel, SectionHeader } from '@/components';
import { Toggle } from '@/pages/Settings/controls';
import { formatDateTimeIST } from '@/lib/format';
import type { Settings } from '@/lib/types';

const money = (n: number) => `$${n.toFixed(4)}`;
const gb = (n: number | null | undefined) => n == null ? 'Not reported' : `${n.toFixed(1)} GB`;

export default function AIControlPage() {
  const qc = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [task, setTask] = useState('');
  const [workflow, setWorkflow] = useState('job_search');
  const control = useQuery({ queryKey: ['ai-control'], queryFn: api.aiControl, refetchInterval: 5000 });
  const runs = useQuery({ queryKey: ['ai-runs', offset, task], queryFn: () => api.aiRuns(offset, task), refetchInterval: 5000 });
  const plan = useQuery({ queryKey: ['ai-plan', workflow, control.data?.current_mode], queryFn: () => api.aiPlan(workflow) });
  const save = useMutation({ mutationFn: (patch: Partial<Settings>) => api.patchSettings(patch), onSuccess: async r => {
    useHQ.getState().mergeSettings(r.settings);
    await Promise.all([qc.invalidateQueries({ queryKey: ['ai-control'] }), qc.invalidateQueries({ queryKey: ['ai-plan'] }), qc.invalidateQueries({ queryKey: ['budget'] })]);
  } });
  const refresh = useMutation({ mutationFn: api.recheckClaude, onSuccess: () => qc.invalidateQueries({ queryKey: ['ai-control'] }) });
  const d = control.data;
  if (!d) return <GlassPanel padding="lg"><p role="status">{control.error ? `Couldn't load AI controls: ${control.error.message}` : 'Loading AI controls…'}</p><Button className="mt-3" onClick={() => void control.refetch()}>Retry</Button></GlassPanel>;
  const selected = d.modes.find(m => m.id === d.current_mode);
  const total = (period: typeof d.today) => Object.values(period).reduce((n, u) => n + u.estimated_cost_usd, 0);
  const assigned = d.roles.filter(r => r.ranked.length > 0);
  const failures = d.execution_today.reduce((n, r) => n + (r.failed ?? 0), 0);
  const fallbacks = d.execution_today.reduce((n, r) => n + (r.fallbacks ?? 0), 0);
  return <div className="min-w-0 space-y-6 pb-8">
    <SectionHeader kicker="Local first · external help when useful" title="AI Control" icon={Workflow} color="#22D3EE" right={<Button icon={RefreshCw} loading={refresh.isPending} onClick={() => refresh.mutate()}>Check access</Button>} />
    {(save.error || refresh.error || control.error) && <p role="alert" className="rounded-xl border border-red-400/30 bg-red-500/10 p-3 text-sm text-red-200">{(save.error || refresh.error || control.error)?.message}</p>}
    <GlassPanel padding="lg" glow="#22D3EE" accentTop>
      <div className="flex flex-wrap items-center gap-2"><Badge color="#22D3EE">Local AI · Always ON / Required</Badge><span role="status" className="text-xs text-muted">{save.isPending ? 'Saving…' : save.isSuccess ? 'Saved · applies to the next dispatch' : 'Changes apply without restarting'}</span></div>
      <h2 className="mt-4 font-display text-xl font-semibold text-ink">{selected?.label}</h2>
      <p className="mt-2 text-sm text-muted">Local models handle each step first. If output fails validation or the benchmark quality floor, an enabled assistant can help. Calls already in progress finish normally.</p>
      <label className="mt-5 block text-sm font-medium text-ink" htmlFor="ai-mode">Active mode</label>
      <select id="ai-mode" value={d.current_mode} disabled={save.isPending} onChange={e => save.mutate({ ai_mode: e.target.value })} className="mt-2 w-full min-w-0 rounded-xl border border-white/15 bg-surface-1 p-3 text-sm text-ink">
        {d.modes.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
      </select>
      <p className="mt-2 text-xs text-muted">Auto respects providers you switched off. Change a provider switch to choose an explicit combination.</p>
      <div className="mt-5 rounded-xl border border-emerald-400/20 bg-emerald-400/5 p-4">
        <div className="flex flex-wrap items-center gap-2"><Badge color="#34D399">Recommended</Badge><h3 className="text-sm font-semibold text-ink">{d.recommendation.label}</h3></div>
        <p className="mt-2 text-sm text-muted">{d.recommendation.reason}</p>
        <Button size="sm" className="mt-3" disabled={save.isPending || d.current_mode === d.recommendation.mode} onClick={() => save.mutate({ ai_mode: d.recommendation.mode })}>Use recommended mode</Button>
      </div>
      {assigned.length === 0 && <p className="mt-3 text-sm text-amber-200">Local AI is enabled, but no model is assigned yet. <Link className="underline" to="/models">Discover and benchmark models</Link> to make local execution available.</p>}
      {d.signoff_required && <p className="mt-3 text-xs text-muted"><ShieldCheck className="mr-1 inline size-4" />Applications retain the independent external sign-off requirement after local checks. In Local AI Only mode, that step waits. Manage this policy in <Link to="/settings?tab=budget" className="underline">Models & Budget</Link>.</p>}
    </GlassPanel>
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {d.providers.map(p => <GlassPanel key={p.id} padding="md">
        <div className="flex items-start justify-between gap-2"><h2 className="text-sm font-semibold text-ink">{p.label}</h2>{p.required ? <Badge color="#22D3EE">Required</Badge> : <Toggle id={`ai-${p.id}`} label={`Enable ${p.label}`} checked={p.enabled} disabled={save.isPending} onChange={v => save.mutate({ [`llm_${p.id}_enabled`]: v })} />}</div>
        <p className="mt-3 text-sm text-cyan-200">{p.required ? 'Always ON' : !p.enabled ? 'OFF' : p.status.resting ? 'Resting · usage limit' : p.status.available ? 'Ready' : p.status.checked ? 'Unavailable' : 'Not checked yet'}</p>
        <p className="mt-2 text-xs leading-relaxed text-muted">{p.billing}</p>
        {p.status.reason && <p className="mt-2 break-words text-xs text-amber-200">{p.status.reason}</p>}
        <dl className="mt-4 space-y-2 text-xs text-muted"><div className="flex justify-between gap-2"><dt>HQ calls today / month</dt><dd className="text-ink">{p.required ? `${p.performance.attempts} / —` : `${p.today?.calls ?? 0} / ${p.month?.calls ?? 0}`}</dd></div>
          <div className="flex justify-between gap-2"><dt>Mean response today</dt><dd className="text-ink">{p.performance.latency == null ? 'No samples' : `${(p.performance.latency / 1000).toFixed(1)} s`}</dd></div>
          <div className="flex justify-between gap-2"><dt>Succeeded / failed</dt><dd className="text-ink">{p.performance.succeeded ?? 0} / {p.performance.failed ?? 0}</dd></div>
          {!p.required && <div className="flex justify-between gap-2"><dt>Est. cost today / month</dt><dd className="text-ink">{money(p.today?.estimated_cost_usd ?? 0)} / {money(p.month?.estimated_cost_usd ?? 0)}</dd></div>}
        </dl>
        {!p.required && <p className="mt-3 text-xs text-muted">{p.quota_note}</p>}
      </GlassPanel>)}
    </div>
    <div className="grid gap-4 lg:grid-cols-2">
      <GlassPanel padding="lg"><SectionHeader title="Usage & reliability" icon={Sparkles} size="sm" />
        <dl className="mt-4 grid grid-cols-2 gap-4 text-sm"><Metric label="HQ external cost today" value={money(total(d.today))} /><Metric label="HQ external cost this month" value={money(total(d.month))} /><Metric label="Daily budget / reserved" value={`${money(d.budget.budget_usd)} / ${money(d.budget.reserved_usd)}`} /><Metric label="Failed attempts / fallbacks today" value={`${failures} / ${fallbacks}`} /></dl>
        <p className="mt-4 text-xs text-muted">{d.usage_note}</p>
      </GlassPanel>
      <GlassPanel padding="lg"><SectionHeader title="This Mac" icon={Cpu} size="sm" />
        <dl className="mt-4 grid grid-cols-2 gap-4 text-sm"><Metric label="Last local model used" value={d.current_local_model ?? 'No recorded local run'} /><Metric label="RAM / unified memory available" value={`${gb(d.memory.available_gb)} / ${gb(d.memory.total_gb)}`} /><Metric label="Local model pool / budget" value={`${gb(d.memory.pool_used_gb)} / ${gb(d.memory.pool_budget_gb)}`} /><Metric label="Memory pressure" value={d.memory.pressure} /></dl>
        <p className="mt-4 text-xs text-muted">Loaded models: {d.servers.filter(s => s.status === 'running').map(s => s.model_id).join(', ') || 'None reported'}.</p>
        {d.memory.stale && <p className="mt-2 text-xs text-amber-200">Model-pool telemetry is stale; system memory is current.</p>}
        <Link to="/models" className="mt-3 inline-block text-sm text-cyan-300 underline">Models, role assignments & benchmarks</Link>
      </GlassPanel>
    </div>
    <GlassPanel padding="lg"><div className="flex flex-wrap items-center justify-between gap-3"><SectionHeader title="Subtask routing preview" icon={Workflow} size="sm" /><select aria-label="Workflow preview" value={workflow} onChange={e => setWorkflow(e.target.value)} className="rounded-lg border border-white/15 bg-surface-1 p-2 text-sm text-ink"><option value="job_search">Job / internship workflow</option><option value="coding">Coding task plan</option></select></div>
      <p className="mt-2 text-xs text-muted">A preview of routing policy, not a running job. Actual decisions and results appear below. Coding assistance produces proposals; it does not modify files.</p>
      {plan.error && <p role="alert" className="mt-3 text-sm text-red-200">{plan.error.message}</p>}
      <ol className="mt-4 grid gap-3 lg:grid-cols-3">{plan.data?.steps.map((s, i) => <li key={s.task_type} className="min-w-0 rounded-xl border border-white/10 p-4"><p className="text-xs text-cyan-300">STEP {i + 1} · Local first</p><h3 className="mt-2 text-sm font-semibold text-ink">{s.title}</h3><p className="mt-2 break-words text-xs text-muted">{s.local_model ?? 'No local assignment'} · {s.reason}</p><p className="mt-2 text-xs text-muted">External fallback: {s.fallback_providers.join(' → ') || 'None for this step'}</p></li>)}</ol>
    </GlassPanel>
    <GlassPanel padding="lg"><div className="flex flex-wrap items-center justify-between gap-3"><SectionHeader title="Task & subtask history" size="sm" /><span className="text-xs text-muted">{runs.data?.total ?? 0} recorded AI attempts</span></div>
      <label htmlFor="task-filter" className="mt-4 block text-xs text-muted">Filter by task ID</label><input id="task-filter" value={task} onChange={e => { setTask(e.target.value.trim()); setOffset(0); }} placeholder="All tasks" className="mt-1 w-full rounded-lg border border-white/15 bg-surface-1 p-2 text-sm text-ink" />
      {runs.error && <p role="alert" className="mt-3 text-sm text-red-200">{runs.error.message}</p>}
      {!runs.isLoading && !runs.data?.items.length && <p className="py-8 text-center text-sm text-muted">No routing attempts recorded yet. New AI work will show its model, reason, outcome and cost here.</p>}
      <div className="mt-4 space-y-3">{runs.data?.items.map(r => <article key={r.id} className="min-w-0 rounded-xl border border-white/10 p-4">
        <div className="flex flex-wrap items-center gap-2"><Badge color={r.status === 'succeeded' ? '#34D399' : '#FCA5A5'}>{r.status}</Badge><Badge color={r.execution === 'local' ? '#22D3EE' : '#C4B5FD'}>{r.execution}</Badge>{r.escalated_from_run_id && <Badge color="#FBBF24">Fallback</Badge>}<h3 className="break-all text-sm font-semibold text-ink">{r.task_type || r.capability} · {r.model_id}</h3></div>
        <p className="mt-2 text-sm text-muted">{r.route_reason}</p>{r.error && <p className="mt-2 break-words text-xs text-red-200">{r.error}</p>}
        <p className="mt-3 break-all text-xs text-muted">{formatDateTimeIST(r.started_at)} · {r.agent_id} · {(r.duration_ms / 1000).toFixed(1)} s · {r.execution === 'local' ? '$0 API cost' : r.estimated_cost_usd != null ? `${money(r.estimated_cost_usd)} estimated` : r.cost_usd != null ? `${money(r.cost_usd)} reported estimate` : 'Cost not reported'} · {r.ai_mode}</p>
        <p className="mt-1 break-all text-xs text-muted">Task: {r.task_id ?? 'Standalone'} · Parent run: {r.parent_run_id ?? 'None'} · Tokens: {r.prompt_tokens ?? '—'} in / {r.completion_tokens ?? '—'} out</p>
        {r.opportunity_id && <Link className="mt-2 inline-block text-xs text-cyan-300 underline" to={`/o/${r.opportunity_id}`}>Open opportunity</Link>}
      </article>)}</div>
      <div className="mt-4 flex items-center justify-between"><Button size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</Button><span className="text-xs text-muted">Page {Math.floor(offset / 50) + 1}</span><Button size="sm" disabled={offset + 50 >= (runs.data?.total ?? 0)} onClick={() => setOffset(offset + 50)}>Next</Button></div>
    </GlassPanel>
  </div>;
}
function Metric({ label, value }: { label: string; value: string }) { return <div className="min-w-0"><dt className="text-xs text-muted">{label}</dt><dd className="mt-1 break-words font-medium text-ink">{value}</dd></div>; }
