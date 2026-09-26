/**
 * Add Agent wizard: adapter → identity → capabilities → config → schedule → live test.
 * The last step runs POST /api/agents/validate (validation, id clash, loopback-only endpoint probe, YAML preview)
 * before POST /api/agents writes agents/<id>.yaml; hot reload adds the node to the graph with no restart.
 * Wizard-created agents never get side-effect capabilities and run on probation (outputs need approval) for 5 runs.
 */
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  Check,
  CheckCircle2,
  Cloud,
  Code2,
  Cpu,
  FlaskConical,
  Globe2,
  Lock,
  MonitorSmartphone,
  PlugZap,
  Sparkles,
  TriangleAlert,
  XCircle,
  type LucideIcon,
} from 'lucide-react';
import { useEffect, useId, useMemo, useState } from 'react';
import { AgentAvatar, Badge, Button } from '@/components';
import { api } from '@/lib/api';
import { cn } from '@/lib/cn';
import { useAgentsMeta } from '@/lib/queries';
import type { AgentConfig, AgentSchedule, AgentValidation, Capability, CostTier } from '@/lib/types';
import { AGENT_PALETTE, withAlpha } from '@/theme/tokens';
import { CloseButton, Field, Modal, Segmented, Stepper, TextInput } from './formKit';
import { ScheduleEditor } from './ScheduleEditor';
import { SCHEDULABLE_FALLBACK } from './schedule';

interface AdapterDef {
  id: string;
  title: string;
  icon: LucideIcon;
  tier: CostTier;
  blurb: string;
  disabled?: string;
}

const ADAPTERS: AdapterDef[] = [
  { id: 'openai_compatible', title: 'Local model', icon: Cpu, tier: 'local', blurb: 'An MLX, Ollama, LM Studio or llama.cpp model on this Mac (OpenAI-compatible API).' },
  { id: 'cloud', title: 'Grok (paid)', icon: Sparkles, tier: 'cloud', blurb: 'Grok through the xAI API, no tools; redacted prompts; draws from the daily Grok budget.' },
  { id: 'http', title: 'HTTP endpoint', icon: Globe2, tier: 'external', blurb: 'POST /run on a localhost or allowlisted service; payloads are redacted.' },
  { id: 'script', title: 'Script', icon: Code2, tier: 'local', blurb: 'A subprocess speaking JSON over stdio with no secrets. Only from this Mac.' },
  { id: 'sim', title: 'Simulated', icon: FlaskConical, tier: 'local', blurb: 'Plausible fake work for trying the dashboard. Clearly tagged.' },
  { id: 'browser', title: 'Browser', icon: MonitorSmartphone, tier: 'local', blurb: 'Playwright against the local mock ATS only.', disabled: 'Built-in Applicant only' },
];

const STEPS = ['Adapter', 'Identity', 'Capabilities', 'Config', 'Schedule', 'Test'] as const;

interface Draft {
  adapter: string;
  name: string;
  id: string;
  idTouched: boolean;
  avatar: string;
  color: string;
  role: string;
  description: string;
  capabilities: string[];
  model: string;
  config: Record<string, string>;
  concurrency: number;
  schedule: AgentSchedule;
}

const EMPTY: Draft = {
  adapter: '',
  name: '',
  id: '',
  idTouched: false,
  avatar: '🤖',
  color: AGENT_PALETTE[10],
  role: 'custom',
  description: '',
  capabilities: [],
  model: '',
  config: {},
  concurrency: 1,
  schedule: { mode: 'on_demand' },
};

const slug = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^[^a-z]+/, '')
    .replace(/-+$/, '')
    .slice(0, 32);

function toConfig(d: Draft): AgentConfig {
  const def = ADAPTERS.find((a) => a.id === d.adapter);
  const cfg: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(d.config)) {
    if (v.trim() === '') continue;
    cfg[k] = k === 'max_tokens' || k === 'per_call_cap_usd' ? Number(v) : k === 'managed' ? v === 'true' : v.trim();
  }
  return {
    id: d.id,
    name: d.name.trim(),
    avatar: d.avatar || '🤖',
    color: d.color,
    role: d.role.trim() || 'custom',
    description: d.description.trim(),
    adapter: d.adapter,
    adapter_config: cfg,
    model: d.model.trim() || null,
    capabilities: d.capabilities,
    cost_tier: def?.tier ?? 'local',
    concurrency: d.concurrency,
    schedule: d.schedule,
    enabled: true,
  };
}

export function Wizard({ open, onClose }: { open: boolean; onClose: () => void }) {
  const titleId = useId();
  return (
    <Modal open={open} onClose={onClose} labelledBy={titleId} widthClass="max-w-3xl">
      {open && <WizardBody onClose={onClose} titleId={titleId} />}
    </Modal>
  );
}

function WizardBody({ onClose, titleId }: { onClose: () => void; titleId: string }) {
  const meta = useAgentsMeta();
  const [step, setStep] = useState(0);
  const [d, setD] = useState<Draft>(EMPTY);
  const [check, setCheck] = useState<AgentValidation | null>(null);
  const [checking, setChecking] = useState(false);
  const [creating, setCreating] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = (patch: Partial<Draft>) => setD((p) => ({ ...p, ...patch }));

  const caps: Capability[] = meta.data?.capabilities ?? [];
  const schedulableIds = useMemo(() => caps.filter((c) => c.schedulable).map((c) => c.id), [caps]);
  const schedulable = d.capabilities.some((c) => (schedulableIds.length ? schedulableIds : SCHEDULABLE_FALLBACK).includes(c));
  useEffect(() => {
    if (!schedulable && d.schedule.mode !== 'on_demand') set({ schedule: { mode: 'on_demand' } });
  }, [schedulable, d.schedule.mode]);

  const canNext = [
    !!d.adapter,
    d.name.trim().length > 0 && /^[a-z][a-z0-9_-]{1,31}$/.test(d.id),
    d.capabilities.length > 0,
    d.adapter !== 'openai_compatible' || !!d.config.base_url || d.config.managed === 'true',
    true,
    !!check?.ok,
  ][step];

  const runCheck = async () => {
    setChecking(true);
    setErr(null);
    try {
      setCheck(await api.validateAgent(toConfig(d)));
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Check failed');
    } finally {
      setChecking(false);
    }
  };
  useEffect(() => {
    if (step === 5) void runCheck();
  }, [step]); // eslint-disable-line react-hooks/exhaustive-deps

  const create = async () => {
    setCreating(true);
    setErr(null);
    try {
      await api.createAgent(toConfig(d));
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Create failed');
    } finally {
      setCreating(false);
    }
  };

  return (
    <>
      <div className="flex items-center gap-3 border-b border-white/[.06] px-5 py-4 md:px-6">
        <span className="grid size-9 place-items-center rounded-xl border border-white/10 bg-white/[.04]">
          <Bot className="size-4 text-fuchsia-300" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h2 id={titleId} className="font-display text-lg font-semibold text-ink">
            Add an agent
          </h2>
          <p className="text-xs text-muted">
            Step {step + 1} of {STEPS.length} · {STEPS[step]}
          </p>
        </div>
        <CloseButton onClick={onClose} />
      </div>

      <ol className="flex gap-1 px-5 pt-4 md:px-6" aria-label="Wizard steps">
        {STEPS.map((s, i) => (
          <li key={s} className="flex-1">
            <div className="h-1 rounded-full transition-colors" style={{ backgroundColor: i <= step ? d.color : 'rgba(255,255,255,0.08)' }} />
            <div className={cn('mt-1.5 hidden text-[10.5px] md:block', i === step ? 'text-ink' : 'text-faint')}>{s}</div>
          </li>
        ))}
      </ol>

      <div className="min-h-[360px] flex-1 overflow-y-auto px-5 py-5 md:px-6">
        {step === 0 && <AdapterStep value={d.adapter} onChange={(adapter) => set({ adapter, config: {} })} />}
        {step === 1 && <IdentityStep d={d} set={set} />}
        {step === 2 && <CapabilitiesStep caps={caps} value={d.capabilities} onChange={(capabilities) => set({ capabilities })} color={d.color} />}
        {step === 3 && <ConfigStep d={d} set={set} />}
        {step === 4 && (
          <div className="space-y-5">
            <Field label="Concurrency" hint="How many tasks it may run at once. Local models share one memory pool, so 1 is usually right.">
              <Stepper label="Concurrency" value={d.concurrency} min={1} max={8} onCommit={(concurrency) => set({ concurrency })} color={d.color} width={3} />
            </Field>
            <Field label="Schedule">
              <ScheduleEditor value={d.schedule} onChange={(schedule) => set({ schedule })} schedulable={schedulable} color={d.color} />
            </Field>
          </div>
        )}
        {step === 5 && <TestStep d={d} check={check} checking={checking} onRetry={runCheck} />}
        {err && <p className="mt-4 text-sm text-red-300">{err}</p>}
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-white/[.06] px-5 py-4 md:px-6">
        <Button variant="ghost" icon={ArrowLeft} disabled={step === 0} onClick={() => setStep((s) => s - 1)}>
          Back
        </Button>
        {step < STEPS.length - 1 ? (
          <Button variant="primary" iconRight={ArrowRight} disabled={!canNext} onClick={() => setStep((s) => s + 1)}>
            Next
          </Button>
        ) : (
          <Button variant="primary" icon={Check} loading={creating} disabled={!check?.ok} onClick={create}>
            Create agent
          </Button>
        )}
      </div>
    </>
  );
}

function AdapterStep({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div role="radiogroup" aria-label="Adapter" className="grid gap-2.5 sm:grid-cols-2">
      {ADAPTERS.map((a) => {
        const on = a.id === value;
        const Icon = a.icon;
        return (
          <button
            key={a.id}
            type="button"
            role="radio"
            aria-checked={on}
            disabled={!!a.disabled}
            onClick={() => onChange(a.id)}
            className={cn(
              'flex gap-3 rounded-2xl border p-3.5 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-45',
              on ? 'border-cyan-300/50 bg-cyan-300/[.07]' : 'border-white/[.08] bg-white/[.02] hover:border-white/15',
            )}
          >
            <span className="grid size-9 shrink-0 place-items-center rounded-xl border border-white/10 bg-white/[.03]">
              <Icon className={cn('size-4', on ? 'text-cyan-300' : 'text-muted')} aria-hidden />
            </span>
            <span className="min-w-0">
              <span className="flex items-center gap-2">
                <span className="text-[14px] font-medium text-ink">{a.title}</span>
                {a.disabled && (
                  <Badge size="xs" icon={Lock} color="#8B95A7">
                    {a.disabled}
                  </Badge>
                )}
              </span>
              <span className="mt-0.5 block text-xs leading-relaxed text-muted">{a.blurb}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

function IdentityStep({ d, set }: { d: Draft; set: (p: Partial<Draft>) => void }) {
  const idOk = /^[a-z][a-z0-9_-]{1,31}$/.test(d.id);
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4 rounded-2xl border border-white/[.06] bg-white/[.02] p-4">
        <AgentAvatar agent={{ id: d.id || 'new', name: d.name || 'New agent', avatar: d.avatar, color: d.color }} size="xl" />
        <div className="min-w-0">
          <div className="truncate font-display text-lg font-semibold text-ink">{d.name || 'New agent'}</div>
          <div className="font-mono text-xs text-faint">agents/{d.id || '…'}.yaml</div>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-[1fr_1fr_90px]">
        <Field label="Name" htmlFor="wz-name">
          <TextInput
            id="wz-name"
            data-autofocus
            value={d.name}
            maxLength={40}
            onChange={(e) => set({ name: e.target.value, ...(d.idTouched ? {} : { id: slug(e.target.value) }) })}
            placeholder="Lab Scout"
          />
        </Field>
        <Field label="Id" htmlFor="wz-id" error={d.id && !idOk ? 'a–z first, then a–z 0–9 - _ (2–32)' : undefined}>
          <TextInput id="wz-id" mono value={d.id} invalid={!!d.id && !idOk} onChange={(e) => set({ id: e.target.value, idTouched: true })} placeholder="lab-scout" />
        </Field>
        <Field label="Avatar" htmlFor="wz-avatar">
          <TextInput id="wz-avatar" value={d.avatar} maxLength={40} onChange={(e) => set({ avatar: e.target.value })} className="text-center" />
        </Field>
      </div>
      <Field label="Colour">
        <div className="flex flex-wrap gap-1.5">
          {AGENT_PALETTE.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => set({ color: c })}
              aria-label={`Colour ${c}`}
              aria-pressed={d.color === c}
              className="size-7 rounded-lg border-2 transition-transform hover:scale-110"
              style={{ backgroundColor: c, borderColor: d.color === c ? '#fff' : 'transparent', boxShadow: `0 0 10px -2px ${c}` }}
            />
          ))}
        </div>
      </Field>
      <div className="grid gap-3 sm:grid-cols-[180px_1fr]">
        <Field label="Role" htmlFor="wz-role" hint="Used for model auto-assignment.">
          <TextInput id="wz-role" value={d.role} maxLength={40} onChange={(e) => set({ role: e.target.value })} />
        </Field>
        <Field label="Description" htmlFor="wz-desc">
          <TextInput id="wz-desc" value={d.description} maxLength={500} onChange={(e) => set({ description: e.target.value })} placeholder="What this agent does" />
        </Field>
      </div>
    </div>
  );
}

function CapabilitiesStep({ caps, value, onChange, color }: { caps: Capability[]; value: string[]; onChange: (v: string[]) => void; color: string }) {
  const groups = useMemo(() => {
    const g = new Map<string, Capability[]>();
    for (const c of caps) g.set(String(c.group ?? 'other'), [...(g.get(String(c.group ?? 'other')) ?? []), c]);
    return [...g.entries()];
  }, [caps]);
  if (!caps.length) return <p className="text-sm text-muted">Loading capabilities…</p>;
  return (
    <div className="space-y-4">
      <p className="text-xs leading-relaxed text-muted">
        Pick what this agent can do. Sending email, submitting forms, replying and following up stay with the built-in Applicant, Inbox
        Watcher and Follow-up agents, so they are locked here.
      </p>
      {groups.map(([group, items]) => (
        <div key={group}>
          <div className="mb-1.5 text-[11px] font-medium uppercase tracking-[0.12em] text-muted">{group}</div>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {items.map((c) => {
              const reserved = !!c.reserved;
              const on = value.includes(c.id);
              return (
                <button
                  key={c.id}
                  type="button"
                  role="checkbox"
                  aria-checked={on}
                  disabled={reserved}
                  onClick={() => onChange(on ? value.filter((v) => v !== c.id) : [...value, c.id])}
                  className={cn(
                    'flex items-start gap-2.5 rounded-xl border px-3 py-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-45',
                    !on && 'border-white/[.07] bg-white/[.02] hover:border-white/15',
                  )}
                  style={on ? { borderColor: withAlpha(color, 0.5), backgroundColor: withAlpha(color, 0.08) } : undefined}
                >
                  <span
                    className="mt-0.5 grid size-4 shrink-0 place-items-center rounded border"
                    style={{ borderColor: on ? color : 'rgba(255,255,255,0.25)', backgroundColor: on ? color : 'transparent' }}
                  >
                    {reserved ? <Lock className="size-2.5 text-muted" /> : on && <Check className="size-3 text-[#070B14]" strokeWidth={3} />}
                  </span>
                  <span className="min-w-0">
                    <span className="block font-mono text-[11.5px] text-ink">{c.id}</span>
                    <span className="block text-[11.5px] leading-snug text-muted">{c.description}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function ConfigStep({ d, set }: { d: Draft; set: (p: Partial<Draft>) => void }) {
  const c = d.config;
  const setC = (k: string, v: string) => set({ config: { ...c, [k]: v } });
  const envOk = !c.api_key_env || /^[A-Z][A-Z0-9_]*$/.test(c.api_key_env);
  return (
    <div className="space-y-4">
      {d.adapter === 'openai_compatible' && (
        <>
          <Field label="Where does the model run?">
            <Segmented
              label="Managed or external"
              value={c.managed === 'true' ? 'managed' : 'external'}
              onChange={(v) => setC('managed', v === 'managed' ? 'true' : 'false')}
              options={[
                { value: 'managed', label: 'Managed by HQ', icon: Cpu },
                { value: 'external', label: 'Already running', icon: PlugZap },
              ]}
            />
          </Field>
          {c.managed === 'true' ? (
            <Field label="Model" htmlFor="wz-model" hint="auto = the leaderboard winner for the role, or e.g. mlx:mlx-community/Qwen3-4B-Instruct-2507-4bit">
              <TextInput id="wz-model" mono value={d.model} onChange={(e) => set({ model: e.target.value })} placeholder="auto" />
            </Field>
          ) : (
            <>
              <Field label="Base URL" htmlFor="wz-base" hint="OpenAI-compatible, e.g. http://127.0.0.1:11434/v1 (Ollama) or :1234/v1 (LM Studio).">
                <TextInput id="wz-base" mono value={c.base_url ?? ''} onChange={(e) => setC('base_url', e.target.value)} placeholder="http://127.0.0.1:1234/v1" />
              </Field>
              <Field label="Model id served there" htmlFor="wz-served">
                <TextInput id="wz-served" mono value={c.served_model ?? ''} onChange={(e) => setC('served_model', e.target.value)} placeholder="qwen2.5-7b-instruct" />
              </Field>
            </>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Prompt file" htmlFor="wz-prompt" hint="Relative to the repo, e.g. prompts/summarize.md">
              <TextInput id="wz-prompt" mono value={c.prompt ?? ''} onChange={(e) => setC('prompt', e.target.value)} placeholder="prompts/custom.md" />
            </Field>
            <Field label="Max tokens" htmlFor="wz-max">
              <TextInput id="wz-max" mono inputMode="numeric" value={c.max_tokens ?? ''} onChange={(e) => setC('max_tokens', e.target.value.replace(/\D/g, ''))} placeholder="900" />
            </Field>
          </div>
        </>
      )}
      {d.adapter === 'cloud' && (
        <>
          <Field label="Grok model">
            <Segmented
              label="Grok model"
              value={d.model || 'xai:grok-4-fast'}
              onChange={(v) => set({ model: v })}
              color="#E879F9"
              options={[
                { value: 'xai:grok-4-fast', label: 'Grok 4 Fast (cheap)' },
                { value: 'xai:grok-4', label: 'Grok 4 (strong)' },
              ]}
            />
          </Field>
          <Field label="System prompt file" htmlFor="wz-cprompt">
            <TextInput id="wz-cprompt" mono value={c.prompt ?? ''} onChange={(e) => setC('prompt', e.target.value)} placeholder="prompts/custom.md" />
          </Field>
        </>
      )}
      {d.adapter === 'http' && (
        <Field label="Endpoint" htmlFor="wz-endpoint" hint="HQ POSTs tasks to <endpoint>/run. Localhost unless allowlisted.">
          <TextInput id="wz-endpoint" mono value={c.endpoint ?? ''} onChange={(e) => setC('endpoint', e.target.value)} placeholder="http://127.0.0.1:9000" />
        </Field>
      )}
      {d.adapter === 'script' && (
        <Field label="Command" htmlFor="wz-cmd" hint="Receives the task as JSON on stdin and prints a JSON result. Runs with no secrets in its environment.">
          <TextInput id="wz-cmd" mono value={c.command ?? ''} onChange={(e) => setC('command', e.target.value)} placeholder="python agents/scripts/my_agent.py" />
        </Field>
      )}
      {d.adapter === 'sim' && <p className="text-sm text-muted">Nothing to configure — the simulator fakes plausible work and tags it SIM.</p>}
      {(d.adapter === 'openai_compatible' || d.adapter === 'http') && (
        <Field
          label="API key variable (optional)"
          htmlFor="wz-env"
          error={envOk ? undefined : 'Upper-case env var name, e.g. MY_SERVICE_KEY'}
          hint="The name of a variable in .env — never the key itself."
        >
          <TextInput id="wz-env" mono value={c.api_key_env ?? ''} invalid={!envOk} onChange={(e) => setC('api_key_env', e.target.value.toUpperCase())} placeholder="MY_SERVICE_KEY" />
        </Field>
      )}
    </div>
  );
}

function TestStep({ d, check, checking, onRetry }: { d: Draft; check: AgentValidation | null; checking: boolean; onRetry: () => void }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <AgentAvatar agent={{ id: d.id, name: d.name, avatar: d.avatar, color: d.color }} size="lg" />
        <div className="min-w-0 flex-1">
          <div className="font-display text-lg font-semibold text-ink">{d.name}</div>
          <div className="text-xs text-muted">
            {d.capabilities.length} capabilities · {d.adapter}
          </div>
        </div>
        <Button size="sm" variant="secondary" loading={checking} onClick={onRetry}>
          Re-run check
        </Button>
      </div>

      {checking && !check && <p className="text-sm text-muted">Checking…</p>}
      {check && (
        <>
          <div className={cn('flex items-start gap-2.5 rounded-xl border p-3 text-sm', check.ok ? 'border-emerald-400/30 bg-emerald-400/[.06]' : 'border-red-400/30 bg-red-400/[.06]')}>
            {check.ok ? <CheckCircle2 className="mt-0.5 size-4 text-emerald-300" /> : <XCircle className="mt-0.5 size-4 text-red-300" />}
            <div className="min-w-0">
              <div className="font-medium text-ink">{check.ok ? 'Config is valid' : 'Fix these first'}</div>
              {check.errors.map((e, i) => (
                <div key={i} className="text-xs text-red-200">
                  <span className="font-mono">{e.field}</span>: {e.message}
                </div>
              ))}
            </div>
          </div>
          {check.probe && (
            <div className={cn('flex items-start gap-2.5 rounded-xl border p-3 text-sm', check.probe.ok ? 'border-emerald-400/30 bg-emerald-400/[.06]' : 'border-amber-300/30 bg-amber-300/[.06]')}>
              {check.probe.ok ? <PlugZap className="mt-0.5 size-4 text-emerald-300" /> : <TriangleAlert className="mt-0.5 size-4 text-amber-200" />}
              <div className="min-w-0 text-xs">
                <div className="font-medium text-ink">{check.probe.ok ? 'Endpoint answered' : 'Endpoint not reachable'}</div>
                <div className="font-mono text-muted">
                  GET {check.probe.url} {check.probe.status ? `→ ${check.probe.status}` : ''}
                </div>
                {check.probe.error && <div className="text-amber-100/90">{check.probe.error}</div>}
                {check.probe.detail?.models && <div className="text-muted">Models: {check.probe.detail.models.join(', ')}</div>}
                {!check.probe.ok && <div className="mt-1 text-faint">You can still create it; the agent shows as errored until the endpoint is up.</div>}
              </div>
            </div>
          )}
          {check.yaml && (
            <pre className="max-h-64 overflow-auto rounded-xl border border-white/[.06] bg-[#060A12] p-3 font-mono text-[11.5px] leading-relaxed text-ink/85">{check.yaml}</pre>
          )}
          <p className="flex items-start gap-2 text-xs text-muted">
            <Cloud className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            New agents run on probation: their first 5 outputs need your approval in Needs Prerit before anything uses them.
          </p>
        </>
      )}
    </div>
  );
}
