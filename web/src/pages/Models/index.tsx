/**
 * /models — the local-model leaderboard: memory pool bar, Claude status, role assignments (ranked, with overrides
 * and the writer ≠ fact-checker rule), a card per usable model with per-task scores, and the broken/unsupported
 * models with their reasons. Rescan and benchmark (quick/full) run in the worker; progress streams back.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  BatteryMedium,
  Cpu,
  FlaskConical,
  Gauge,
  HardDrive,
  LoaderCircle,
  MemoryStick,
  Pin,
  PinOff,
  Power,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Trophy,
  UserRound,
  type LucideIcon,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Badge, Button, EmptyState, GlassPanel, ProgressBar, SectionHeader, Tooltip } from '@/components';
import { ApiError, api } from '@/lib/api';
import { eventBus } from '@/lib/bus';
import { cn } from '@/lib/cn';
import { formatDuration, formatRelative } from '@/lib/format';
import type { MemoryState, Model, ModelScore, ModelsResponse, RoleAssignment } from '@/lib/types';
import { colors, withAlpha } from '@/theme/tokens';
import { Code } from '@/pages/Settings/parts';

const AMBER = '#F59E0B';
const qk = ['models'] as const;

const TASKS: { id: string; label: string; metric: keyof ModelScore; hint: string }[] = [
  { id: 'factcheck', label: 'Fact-check', metric: 'f1', hint: 'F1 on 158 labelled sentences (recall floor 0.90)' },
  { id: 'write_paragraph', label: 'Writing', metric: 'accuracy', hint: 'Share of sentences passing the fact gate + length + no clichés' },
  { id: 'eligibility', label: 'Eligibility', metric: 'accuracy', hint: 'Verdict accuracy (false eligible ×3) + quote grounding' },
  { id: 'parse_job', label: 'Parse job', metric: 'accuracy', hint: 'Company, title, city and exact requirement quotes' },
  { id: 'title_filter', label: 'Titles', metric: 'f1', hint: 'F1 on 189 scanned titles incl. "Internal"/"International" traps' },
  { id: 'classify_email', label: 'Email', metric: 'accuracy', hint: 'Label accuracy; interview+offer recall floor 0.95' },
];

const RUNTIME_COLOR: Record<string, string> = { mlx: '#22D3EE', ollama: '#A3E635', lmstudio: '#A78BFA', llamacpp: '#FB923C' };

function useModels() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: qk,
    queryFn: api.models,
    refetchInterval: (query) => ((query.state.data as ModelsResponse | undefined)?.benchmark.running ? 3000 : 15000),
  });
  useEffect(
    () =>
      eventBus.on((e) => {
        if (/^(model\.|benchmark\.|roles\.|claude\.)/.test(e.type)) void qc.invalidateQueries({ queryKey: qk });
      }),
    [qc],
  );
  return q;
}

export default function Models() {
  const q = useModels();
  const qc = useQueryClient();
  const [msg, setMsg] = useState<string | null>(null);
  const rescan = useMutation({ mutationFn: api.rescanModels, onSuccess: () => setMsg('Rescan queued — the worker scans every runtime.') });
  const bench = useMutation({
    mutationFn: (suite: 'quick' | 'full') => api.benchmark(suite),
    onSuccess: () => {
      setMsg('Benchmark queued. Each model runs alone, so local agents pause while it runs.');
      void qc.invalidateQueries({ queryKey: qk });
    },
  });
  const data = q.data;
  const usable = useMemo(() => (data?.models ?? []).filter((m) => m.complete && m.runtime_supported && m.modality === 'chat' && m.status !== 'broken'), [data]);
  const broken = useMemo(() => (data?.models ?? []).filter((m) => !(m.complete && m.runtime_supported) || m.status === 'broken'), [data]);
  const other = useMemo(() => (data?.models ?? []).filter((m) => m.complete && m.runtime_supported && m.modality !== 'chat'), [data]);
  const ranked = useMemo(() => [...usable].sort((a, b) => avgScore(b) - avgScore(a)), [usable]);

  return (
    <div className="space-y-5">
      <SectionHeader
        as="h1"
        size="lg"
        kicker="Leaderboard"
        title="Models"
        right={
          <div className="flex flex-wrap gap-2">
            <Button icon={RefreshCw} loading={rescan.isPending} onClick={() => rescan.mutate()}>
              Rescan
            </Button>
            <Button icon={FlaskConical} variant="secondary" disabled={data?.benchmark.running} loading={bench.isPending && bench.variables === 'quick'} onClick={() => bench.mutate('quick')}>
              Benchmark (quick)
            </Button>
            <Button icon={Gauge} variant="ghost" disabled={data?.benchmark.running} onClick={() => bench.mutate('full')}>
              Full
            </Button>
          </div>
        }
      />
      {msg && <p className="text-xs text-muted">{msg}</p>}
      {(rescan.error || bench.error) && <p className="text-xs text-red-300">{String((rescan.error ?? bench.error) as Error)}</p>}

      {q.isLoading ? (
        <div className="grid h-40 place-items-center text-muted">
          <LoaderCircle className="size-5 animate-spin" aria-label="Loading models" />
        </div>
      ) : !data ? (
        <EmptyState icon={Cpu} title="Couldn't load models" hint={q.error instanceof Error ? q.error.message : undefined} />
      ) : (
        <>
          {data.benchmark.running && <BenchBanner b={data.benchmark} />}
          {data.benchmark.error && !data.benchmark.running && (
            <p className="rounded-xl border border-red-400/30 bg-red-400/[.06] px-3 py-2 text-xs text-red-200">Last benchmark failed: {data.benchmark.error}</p>
          )}
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
            <MemoryPanel mem={data.memory} models={data.models} />
            <ClaudeCard data={data} />
          </div>
          <RolesPanel roles={data.roles} models={usable} />
          <section>
            <div className="mb-3 flex items-baseline justify-between">
              <h2 className="font-display text-lg font-semibold text-ink">Usable chat models</h2>
              <span className="text-xs text-muted">{usable.length} usable · sorted by average score</span>
            </div>
            {usable.length === 0 ? (
              <GlassPanel>
                <EmptyState
                  icon={Cpu}
                  color={AMBER}
                  title="No usable local models found"
                  hint="HQ looks in the Hugging Face cache (MLX), Ollama, LM Studio and GGUF files. Download a model or start a server, then Rescan."
                />
              </GlassPanel>
            ) : (
              <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
                {ranked.map((m, i) => (
                  <ModelCard key={m.id} m={m} place={i} />
                ))}
              </div>
            )}
          </section>
          {broken.length > 0 && <BrokenCard models={broken} />}
          {other.length > 0 && (
            <GlassPanel padding="md">
              <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted">Other complete models (not chat)</div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {other.map((m) => (
                  <Badge key={m.id} color="#8B95A7" mono title={m.id}>
                    {shortName(m.name)} · {m.modality}
                  </Badge>
                ))}
              </div>
            </GlassPanel>
          )}
        </>
      )}
    </div>
  );
}

function shortName(name: string): string {
  return name.split('/').pop() ?? name;
}

function scoreOf(m: Model, task: string, metric: keyof ModelScore): number | null {
  const v = m.scores[task]?.[metric];
  return typeof v === 'number' ? v : null;
}

function avgScore(m: Model): number {
  const vals = TASKS.map((t) => scoreOf(m, t.id, t.metric)).filter((v): v is number => v != null);
  return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : -1;
}

function BenchBanner({ b }: { b: ModelsResponse['benchmark'] }) {
  return (
    <GlassPanel padding="md" glow={AMBER} glowStrength={0.4}>
      <div className="flex flex-wrap items-center gap-3">
        <LoaderCircle className="size-4 animate-spin text-amber-300" aria-hidden />
        <span className="text-sm text-ink">
          Benchmarking <span className="font-mono text-[12.5px]">{shortName(b.model_id ?? '')}</span> · {b.task}
        </span>
        <span className="ml-auto text-xs text-muted tabular">
          {Math.round((b.progress ?? 0) * 100)}%{b.eta_s ? ` · ~${formatDuration(b.eta_s * 1000)} left` : ''}
        </span>
      </div>
      <ProgressBar className="mt-3" value={b.progress ?? 0} color={AMBER} height={4} />
    </GlassPanel>
  );
}

// ── memory ────────────────────────────────────────────────────────────

function MemoryPanel({ mem, models }: { mem: MemoryState; models: Model[] }) {
  const byId = Object.fromEntries(models.map((m) => [m.id, m]));
  const poolFrac = mem.pool_budget_gb ? Math.min(1, mem.pool_used_gb / mem.pool_budget_gb) : 0;
  const pressureColor = mem.pressure === 'normal' ? colors.ok : mem.pressure === 'warn' ? colors.warn : colors.danger;
  return (
    <GlassPanel padding="lg" glow="#22D3EE" glowStrength={0.22}>
      <SectionHeader
        kicker="Memory"
        title="Model pool"
        icon={MemoryStick}
        color="#22D3EE"
        right={
          <div className="flex flex-wrap gap-1.5">
            <Badge color={pressureColor}>pressure {mem.pressure}</Badge>
            {mem.usability_reason && (
              <Tooltip content="Usability mode keeps the pool at 8 GB while you're using the Mac, on battery or in quiet hours." side="bottom">
                <Badge color="#A78BFA" icon={UserRound}>
                  small pool · {mem.usability_reason}
                </Badge>
              </Tooltip>
            )}
            {mem.on_battery && <Badge color={colors.warn} icon={BatteryMedium}>battery</Badge>}
          </div>
        }
      />
      <div className="mt-4">
        <div className="flex items-baseline justify-between text-sm">
          <span className="text-muted">Loaded models</span>
          <span className="font-display font-semibold text-ink tabular">
            {mem.pool_used_gb.toFixed(1)} <span className="text-muted">/ {mem.pool_budget_gb.toFixed(0)} GB budget</span>
          </span>
        </div>
        <div className="mt-2 flex h-3 overflow-hidden rounded-full bg-white/[.06]">
          {(mem.servers ?? []).map((s, i) => (
            <Tooltip key={s.model_id} content={`${shortName(s.model_id)} · ${(s.footprint_gb ?? s.need_gb).toFixed(1)} GB · :${s.port}`} side="top">
              <div
                className="h-full"
                style={{
                  width: `${(Math.max(s.footprint_gb ?? 0, s.need_gb) / Math.max(1, mem.pool_budget_gb)) * 100}%`,
                  backgroundColor: ['#22D3EE', '#A78BFA', '#F59E0B', '#34D399', '#FB7185'][i % 5],
                  opacity: 0.85,
                }}
              />
            </Tooltip>
          ))}
        </div>
        <div className="mt-3 grid grid-cols-3 gap-2 text-center">
          <Stat label="system free" value={`${mem.available_gb.toFixed(1)} GB`} />
          <Stat label="system total" value={`${mem.total_gb.toFixed(0)} GB`} />
          <Stat label="pool used" value={`${Math.round(poolFrac * 100)}%`} />
        </div>
        <ul className="mt-3 space-y-1 text-xs text-muted">
          {(mem.servers ?? []).length === 0 ? (
            <li>No model servers running — they start on demand and unload after 20 idle minutes.</li>
          ) : (
            (mem.servers ?? []).map((s) => (
              <li key={s.model_id} className="flex items-center justify-between gap-2">
                <span className="truncate font-mono text-ink/85">{shortName(byId[s.model_id]?.name ?? s.model_id)}</span>
                <span className="shrink-0 tabular">
                  :{s.port} · {(s.footprint_gb ?? s.need_gb).toFixed(1)} GB{s.in_use ? ` · ${s.in_use} busy` : ''}
                </span>
              </li>
            ))
          )}
        </ul>
        {mem.stale && <p className="mt-2 text-[11px] text-faint">Worker hasn't published memory state recently; showing system values only.</p>}
      </div>
    </GlassPanel>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/[.06] bg-white/[.02] py-2">
      <div className="font-display text-[15px] font-semibold text-ink tabular">{value}</div>
      <div className="text-[10px] uppercase tracking-wider text-faint">{label}</div>
    </div>
  );
}

// ── Claude ────────────────────────────────────────────────────────────

function ClaudeCard({ data }: { data: ModelsResponse }) {
  const c = data.claude;
  const qc = useQueryClient();
  const recheck = useMutation({ mutationFn: api.recheckClaude, onSuccess: () => setTimeout(() => void qc.invalidateQueries({ queryKey: qk }), 3000) });
  const ok = c.available === true;
  const unknown = c.available == null;
  return (
    <GlassPanel padding="lg" glow="#E879F9" glowStrength={0.25}>
      <SectionHeader
        kicker="Escalation & sign-off"
        title="Claude"
        icon={Sparkles}
        color="#E879F9"
        right={<Badge color={ok ? colors.ok : unknown ? '#8B95A7' : colors.warn}>{ok ? 'available' : unknown ? 'not checked' : 'unavailable'}</Badge>}
      />
      <div className="mt-3 space-y-3 text-[13px] leading-relaxed text-muted">
        {ok ? (
          <p>
            Logged in. Escalations use <b className="text-ink">{c.model}</b>; final sign-off uses <b className="text-ink">{c.signoff_model}</b>. Every call runs with no tools,
            no hooks and a per-call budget cap.
          </p>
        ) : (
          <div className="rounded-xl border border-amber-300/25 bg-amber-300/[.06] p-3 text-amber-100/90">
            <div className="flex items-center gap-2 font-medium text-amber-100">
              <AlertTriangle className="size-4" aria-hidden /> {unknown ? 'Claude has not been checked yet' : 'Not logged in'}
            </div>
            <p className="mt-1">
              Run <Code>claude auth login</Code> in Terminal on this Mac. Local models keep working; sign-off, polish and the Strategist wait.
            </p>
            {c.reason && !c.reason.includes('auth login') && <p className="mt-1 text-xs text-amber-100/70">{c.reason}</p>}
          </div>
        )}
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-faint">{c.checked_at ? `checked ${formatRelative(c.checked_at)}` : 'checked every 10 minutes'}</span>
          <Button size="sm" icon={RotateCcw} loading={recheck.isPending} onClick={() => recheck.mutate()}>
            Re-check
          </Button>
        </div>
      </div>
    </GlassPanel>
  );
}

// ── roles ─────────────────────────────────────────────────────────────

const ROLE_ICON: Record<string, LucideIcon> = { fact_checker: ShieldCheck, writer: Trophy };

function RolesPanel({ roles, models }: { roles: RoleAssignment[]; models: Model[] }) {
  const qc = useQueryClient();
  const [err, setErr] = useState<string | null>(null);
  const setRole = useMutation({
    mutationFn: ({ role, model }: { role: string; model: string | null }) => (model ? api.setRole(role, model) : api.resetRole(role)),
    onSuccess: () => {
      setErr(null);
      void qc.invalidateQueries({ queryKey: qk });
    },
    onError: (e) => setErr(e instanceof ApiError ? String(e.detail ?? e.message) : String(e)),
  });
  return (
    <GlassPanel padding="lg" glow="#2DD4BF" glowStrength={0.2}>
      <SectionHeader kicker="Routing" title="Role assignments" icon={Trophy} color="#2DD4BF" />
      <p className="mt-1.5 max-w-3xl text-[13px] text-muted">
        The fact-checker is chosen first and must differ from the writer (and from every model that wrote a document it checks). If a model fails
        its role, the next-ranked model of a different family takes over, then Claude.
      </p>
      {err && <p className="mt-2 text-xs text-red-300">{err}</p>}
      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {roles.map((r) => {
          const top = r.ranked[0];
          const Icon = ROLE_ICON[r.role] ?? Cpu;
          return (
            <div key={r.role} className="min-w-0 rounded-xl border border-white/[.07] bg-white/[.02] p-3">
              <div className="flex items-center gap-2">
                <Icon className="size-4 text-teal-300" aria-hidden />
                <span className="text-[13px] font-medium text-ink">{r.label}</span>
                {top?.source === 'override' && <Badge size="xs" color="#FBBF24">override</Badge>}
              </div>
              {r.needs_claude_signoff && (
                <p className="mt-1.5 text-[11px] text-amber-200/90">No local model meets the floor — documents need Claude sign-off.</p>
              )}
              <ol className="mt-2 space-y-1">
                {r.ranked.length === 0 && <li className="text-xs text-faint">Nothing assigned yet — run a benchmark.</li>}
                {r.ranked.slice(0, 3).map((x, i) => (
                  <li key={x.model_id} className={cn('flex items-center justify-between gap-2 text-xs', i === 0 ? 'text-ink' : 'text-muted')}>
                    <span className="truncate font-mono" title={x.reason ?? x.model_id}>
                      {i + 1}. {shortName(x.model_id)}
                    </span>
                    <span className="shrink-0 tabular text-faint">{x.score != null ? x.score.toFixed(2) : '—'}</span>
                  </li>
                ))}
              </ol>
              <select
                aria-label={`Override ${r.label}`}
                className="mt-2 h-8 w-full rounded-lg border border-white/10 bg-[#0D1422] px-2 text-xs text-ink"
                value={top?.source === 'override' ? top.model_id : ''}
                onChange={(e) => setRole.mutate({ role: r.role, model: e.target.value || null })}
              >
                <option value="">Auto (leaderboard)</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {shortName(m.name)}
                  </option>
                ))}
              </select>
            </div>
          );
        })}
      </div>
    </GlassPanel>
  );
}

// ── model cards ───────────────────────────────────────────────────────

function ModelCard({ m, place }: { m: Model; place: number }) {
  const qc = useQueryClient();
  const refresh = () => void qc.invalidateQueries({ queryKey: qk });
  const pin = useMutation({ mutationFn: () => api.pinModel(m.id, !m.pinned), onSuccess: refresh });
  const unload = useMutation({ mutationFn: () => api.unloadModel(m.id), onSuccess: () => setTimeout(refresh, 1500) });
  const bench = useMutation({ mutationFn: () => api.benchmark('quick', m.id), onSuccess: refresh });
  const rc = RUNTIME_COLOR[m.runtime] ?? '#8B95A7';
  const toks = Object.values(m.scores).map((s) => s.tok_s_gen).filter((v): v is number => v != null);
  const tokS = toks.length ? toks.reduce((a, b) => a + b, 0) / toks.length : null;
  const jv = Object.values(m.scores).map((s) => s.json_valid_first).filter((v): v is number => v != null);
  const json = jv.length ? jv.reduce((a, b) => a + b, 0) / jv.length : null;
  return (
    <GlassPanel padding="md" glow={rc} glowStrength={m.status === 'loaded' ? 0.35 : 0.14} className="flex min-w-0 flex-col">
      <div className="flex items-start gap-3">
        <span
          className="grid size-9 shrink-0 place-items-center rounded-xl border font-display text-sm font-bold"
          style={{ borderColor: withAlpha(rc, 0.4), backgroundColor: withAlpha(rc, 0.1), color: rc }}
        >
          {avgScore(m) >= 0 ? place + 1 : '·'}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate font-display text-[15px] font-semibold text-ink" title={m.id}>
            {shortName(m.name)}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
            <Badge size="xs" color={rc} mono>
              {m.runtime}
            </Badge>
            {m.params_b != null && <Badge size="xs" color="#8B95A7">{m.params_b}B</Badge>}
            {m.quant && <Badge size="xs" color="#8B95A7">{m.quant}</Badge>}
            {m.status === 'loaded' && <Badge size="xs" color={colors.ok} icon={Power}>loaded</Badge>}
            {m.pinned && <Badge size="xs" color="#FBBF24" icon={Pin}>pinned</Badge>}
          </div>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        <Mini label="RAM" value={m.measured_ram_gb != null ? `${m.measured_ram_gb.toFixed(1)} GB` : m.est_ram_gb != null ? `~${m.est_ram_gb.toFixed(1)} GB` : '—'} hint={m.measured_ram_gb != null ? `measured peak; estimate ${m.est_ram_gb ?? '—'} GB` : 'estimate (not loaded yet)'} />
        <Mini label="tok/s" value={tokS != null ? Math.round(tokS).toString() : '—'} hint="Average generation speed in benchmarks" />
        <Mini label="JSON ok" value={json != null ? `${Math.round(json * 100)}%` : '—'} hint="Valid JSON on the first answer" />
      </div>

      <div className="mt-3 space-y-1.5">
        {TASKS.map((t) => {
          const v = scoreOf(m, t.id, t.metric);
          return (
            <div key={t.id} title={t.hint} className="grid grid-cols-[84px_minmax(0,1fr)_38px] items-center gap-2 text-[11.5px]">
                <span className="text-muted">{t.label}</span>
                <div className="h-1.5 overflow-hidden rounded-full bg-white/[.06]">
                  <div className="h-full origin-left rounded-full" style={{ transform: `scaleX(${v ?? 0})`, backgroundColor: v == null ? 'transparent' : v >= 0.8 ? colors.ok : v >= 0.6 ? colors.warn : '#F87171' }} />
                </div>
                <span className="text-right font-mono text-ink/85 tabular">{v != null ? v.toFixed(2) : '—'}</span>
            </div>
          );
        })}
      </div>

      {m.roles.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {m.roles.map((r) => (
            <Badge key={r} color="#2DD4BF" size="sm">
              {r.replace('_', '-')}
            </Badge>
          ))}
        </div>
      )}
      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-white/[.06] pt-3">
        <span className="text-[11px] text-faint">{m.last_benchmark_at ? `benchmarked ${formatRelative(m.last_benchmark_at)}` : 'not benchmarked'}</span>
        <div className="flex gap-1.5">
          <Button size="sm" variant="ghost" icon={m.pinned ? PinOff : Pin} loading={pin.isPending} onClick={() => pin.mutate()}>
            {m.pinned ? 'Unpin' : 'Pin'}
          </Button>
          {m.status === 'loaded' && (
            <Button size="sm" variant="ghost" icon={Power} loading={unload.isPending} onClick={() => unload.mutate()}>
              Unload
            </Button>
          )}
          <Button size="sm" variant="secondary" icon={FlaskConical} loading={bench.isPending} onClick={() => bench.mutate()}>
            Benchmark
          </Button>
        </div>
      </div>
    </GlassPanel>
  );
}

function Mini({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div title={hint} className="rounded-lg border border-white/[.05] bg-white/[.02] py-1.5">
      <div className="font-display text-[13.5px] font-semibold text-ink tabular">{value}</div>
      <div className="text-[9.5px] uppercase tracking-wider text-faint">{label}</div>
    </div>
  );
}

function BrokenCard({ models }: { models: Model[] }) {
  return (
    <GlassPanel padding="lg" glow="#FB923C" glowStrength={0.18}>
      <SectionHeader kicker="Not usable" title="Broken or incomplete models" icon={HardDrive} color="#FB923C" />
      <p className="mt-1.5 text-[13px] text-muted">
        HQ never downloads anything on its own. Re-download a model yourself (e.g. <Code>huggingface-cli download &lt;repo&gt;</Code>) and press Rescan.
      </p>
      <ul className="mt-3 divide-y divide-white/[.06]">
        {models.map((m) => (
          <li key={m.id} className="flex flex-col gap-0.5 py-2.5 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
            <span className="min-w-0 truncate font-mono text-[12.5px] text-ink/90" title={m.id}>
              {m.name}
            </span>
            <span className="shrink-0 text-xs text-amber-200/90">
              {m.status === 'broken' && m.complete ? 'failed to run repeatedly' : m.incomplete_reason ?? (m.runtime_supported ? 'incomplete' : 'runtime unsupported')}
            </span>
          </li>
        ))}
      </ul>
    </GlassPanel>
  );
}
