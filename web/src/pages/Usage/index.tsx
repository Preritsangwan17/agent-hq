/**
 * /usage — AI & Grok: the on/off switches and API-saving mode, then Grok (xAI) usage. Every figure says whether it
 * is exact or an estimate: per-call cost is exact when xAI reported it, HQ's daily limit is exact (HQ enforces it),
 * and remaining credit is an estimate (xAI's API doesn't give HQ the account balance).
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  BadgeCheck,
  CalendarDays,
  Cpu,
  DollarSign,
  Gauge,
  KeyRound,
  LoaderCircle,
  PiggyBank,
  Power,
  RotateCcw,
  Sparkles,
  Wallet,
  type LucideIcon,
} from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { Badge, Button, EmptyState, EnginesControl, GlassPanel, GROK, LOCAL, ModeControl, SectionHeader, Tooltip } from '@/components';
import { api } from '@/lib/api';
import { eventBus } from '@/lib/bus';
import { formatCompact, formatDateIST, formatDateTimeIST, formatRelative } from '@/lib/format';
import { useHQ } from '@/lib/store';
import type { GrokUsage } from '@/lib/types';
import { colors, withAlpha } from '@/theme/tokens';

const qk = ['usage'] as const;

/** Grok calls cost fractions of a cent: show enough digits to be honest. */
export function usd(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n === 0) return '$0';
  if (Math.abs(n) < 0.01) return `$${n.toFixed(4)}`;
  if (Math.abs(n) < 10) return `$${n.toFixed(3)}`;
  return `$${n.toFixed(2)}`;
}

function Exactness({ exact, why }: { exact: boolean | 'mixed'; why: string }) {
  const label = exact === true ? 'exact' : exact === 'mixed' ? 'mostly exact' : 'estimate';
  const color = exact === true ? colors.ok : exact === 'mixed' ? '#60A5FA' : colors.warn;
  return (
    <Tooltip content={why} side="bottom">
      <span>
        <Badge size="xs" color={color}>
          {label}
        </Badge>
      </span>
    </Tooltip>
  );
}

function spendExactness(share: number | null): boolean | 'mixed' {
  if (share == null) return true;
  return share >= 0.999 ? true : share > 0 ? 'mixed' : false;
}

const SPEND_WHY =
  "Exact when xAI returned the call's cost with the response; otherwise estimated from config/cloud_prices.yaml.";

export default function Usage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: qk, queryFn: () => api.usage(30), refetchInterval: 20_000 });
  useEffect(
    () =>
      eventBus.on((e) => {
        if (/^(budget\.|cloud\.|settings\.)/.test(e.type)) void qc.invalidateQueries({ queryKey: qk });
      }),
    [qc],
  );
  const u = q.data;

  return (
    <div className="space-y-5">
      <SectionHeader as="h1" size="lg" kicker="Local first · Grok when it counts" title="AI & Grok usage" />

      <GlassPanel padding="lg" glow="#34D399" glowStrength={0.22}>
        <SectionHeader kicker="On / off" title="Which AI HQ may use" icon={Power} color="#34D399" />
        <p className="mt-1.5 max-w-3xl text-[13px] text-muted">
          Local models run on your Mac for free and keep your data private. Grok is paid, so HQ only uses it when it gives a real advantage. Switch
          individual local models on or off on the <Link className="text-cyan-300 hover:text-cyan-200" to="/models">Models</Link> page.
        </p>
        <div className="mt-4">
          <EnginesControl />
        </div>
        <div className="mt-5">
          <div className="mb-2 text-[11px] font-medium uppercase tracking-[0.12em] text-muted">How much Grok to use</div>
          <ModeControl />
        </div>
      </GlassPanel>

      {q.isLoading ? (
        <div className="grid h-40 place-items-center text-muted">
          <LoaderCircle className="size-5 animate-spin" aria-label="Loading usage" />
        </div>
      ) : !u ? (
        <EmptyState icon={Sparkles} title="Couldn't load Grok usage" hint={q.error instanceof Error ? q.error.message : undefined} />
      ) : (
        <>
          <KeyPanel u={u} />
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <Tile
              icon={DollarSign}
              label="Grok today"
              value={usd(u.today.spent_usd)}
              sub={`${u.today.calls} call${u.today.calls === 1 ? '' : 's'} · ${formatCompact(u.today.input_tokens + u.today.output_tokens)} tokens`}
              badge={<Exactness exact={spendExactness(u.today.reported_share)} why={SPEND_WHY} />}
              color={GROK}
            />
            <Tile
              icon={CalendarDays}
              label={`This month (${u.month.month})`}
              value={usd(u.month.spent_usd)}
              sub={`${u.month.calls} calls · last ${u.last_days.days} days ${usd(u.last_days.spent_usd)} · all time ${usd(u.all_time.spent_usd)}`}
              badge={<Exactness exact={spendExactness(u.month.reported_share)} why={SPEND_WHY} />}
              color={GROK}
            />
            <Tile
              icon={Gauge}
              label="Left in today's HQ limit"
              value={usd(u.budget.remaining_today_usd)}
              sub={`of ${usd(u.budget.daily_usd)}/day · ${u.budget.calls_left_today} of ${u.budget.call_cap} calls left · resets ${formatDateTimeIST(u.budget.resets_at)} IST`}
              badge={<Exactness exact why={u.budget.note} />}
              color={colors.ok}
            />
            <CreditTile u={u} />
            <Tile
              icon={Cpu}
              label="Handled locally (30 days)"
              value={u.local.local_share == null ? '—' : `${Math.round(u.local.local_share * 100)}%`}
              sub={`${u.local.calls} local model calls vs ${u.local.grok_calls} Grok calls`}
              badge={<Exactness exact why="Counted from HQ's own run log." />}
              color={LOCAL}
            />
            <Tile
              icon={PiggyBank}
              label="Saved by running locally"
              value={`≈ ${usd(u.local.est_saved_usd)}`}
              sub={`${formatCompact(u.local.input_tokens + u.local.output_tokens)} local tokens in 30 days`}
              badge={<Exactness exact={false} why={u.local.saved_note} />}
              color={LOCAL}
            />
          </div>

          <DailyChart u={u} />

          <div className="grid gap-5 xl:grid-cols-2">
            <Breakdown
              title="By model (30 days)"
              rows={u.by_model.map((m) => ({ key: m.model, label: m.model.replace(/^xai:/, ''), calls: m.calls, spent: m.spent_usd, extra: `${formatCompact(m.input_tokens)} in · ${formatCompact(m.output_tokens)} out` }))}
            />
            <Breakdown
              title="By task (30 days)"
              rows={u.by_task.map((t) => ({ key: t.task_type, label: t.task_type, calls: t.calls, spent: t.spent_usd }))}
            />
          </div>

          <RecentCalls u={u} />
          <RateLimits u={u} />
        </>
      )}
    </div>
  );
}

function Tile({ icon: Icon, label, value, sub, badge, color, children }: {
  icon: LucideIcon; label: string; value: string; sub?: ReactNode; badge?: ReactNode; color: string; children?: ReactNode;
}) {
  return (
    <GlassPanel padding="md" glow={color} glowStrength={0.16} className="min-w-0">
      <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.12em] text-muted">
        <Icon className="size-3.5 shrink-0" style={{ color }} aria-hidden />
        <span className="min-w-0 flex-1 truncate">{label}</span>
        {badge}
      </div>
      <div className="mt-2 font-display text-2xl font-semibold text-ink tabular">{value}</div>
      {sub && <div className="mt-1 text-xs leading-snug text-muted">{sub}</div>}
      {children}
    </GlassPanel>
  );
}

function CreditTile({ u }: { u: GrokUsage }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState('');
  const [editing, setEditing] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const c = u.credit;
  const save = async (value: number | null) => {
    setErr(null);
    try {
      const r = await api.patchSettings({ grok_credit_usd: value });
      useHQ.getState().mergeSettings(r.settings);
      setEditing(false);
      setDraft('');
      void qc.invalidateQueries({ queryKey: qk });
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };
  return (
    <Tile
      icon={Wallet}
      label="Remaining Grok credit"
      value={c ? `≈ ${usd(c.estimated_remaining_usd)}` : 'unknown'}
      sub={
        c
          ? `You entered ${usd(c.entered_usd)} on ${formatDateIST(c.entered_at)}; HQ has spent ${usd(c.spent_since_usd)} since.`
          : "xAI's API doesn't tell HQ your balance. Enter what console.x.ai shows and HQ keeps an estimate."
      }
      badge={<Exactness exact={false} why={c?.note ?? 'Estimate based on the balance you enter; check console.x.ai for the exact figure.'} />}
      color="#FBBF24"
    >
      {editing ? (
        <form
          className="mt-2 flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const v = Number(draft);
            if (Number.isFinite(v) && v >= 0) void save(v);
            else setErr('Enter a dollar amount, e.g. 25');
          }}
        >
          <label className="sr-only" htmlFor="grok-credit">Balance on console.x.ai in US dollars</label>
          <input
            id="grok-credit"
            inputMode="decimal"
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value.replace(/[^0-9.]/g, ''))}
            placeholder="25.00"
            className="h-8 w-28 rounded-lg border border-white/10 bg-[#0D1422] px-2 font-mono text-sm text-ink"
          />
          <Button size="sm" type="submit">Save</Button>
          <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
        </form>
      ) : (
        <div className="mt-2 flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
            {c ? 'Update balance' : 'Enter balance'}
          </Button>
          {c && (
            <Button size="sm" variant="ghost" onClick={() => void save(null)}>
              Clear
            </Button>
          )}
          <a className="self-center text-xs text-cyan-300 hover:text-cyan-200" href="https://console.x.ai" target="_blank" rel="noreferrer">
            console.x.ai ↗
          </a>
        </div>
      )}
      {err && <p className="mt-1 text-xs text-red-300">{err}</p>}
    </Tile>
  );
}

function KeyPanel({ u }: { u: GrokUsage }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const k = u.key;
  const off = !u.policy.grok_enabled;
  const status = off
    ? { text: 'switched off', color: '#8B95A7' }
    : !k.present
      ? { text: 'no key in .env', color: '#8B95A7' }
      : k.available
        ? { text: 'connected', color: colors.ok }
        : k.available == null
          ? { text: 'not checked yet', color: '#8B95A7' }
          : { text: 'unavailable', color: colors.warn };
  const info = k.info ?? {};
  const blocked = info.api_key_blocked === true || info.api_key_disabled === true || info.team_blocked === true;
  return (
    <GlassPanel padding="md" glow={GROK} glowStrength={0.18}>
      <div className="flex flex-wrap items-center gap-3">
        <KeyRound className="size-4 shrink-0" style={{ color: GROK }} aria-hidden />
        <span className="font-display text-[15px] font-semibold text-ink">Grok (xAI)</span>
        <Badge color={status.color}>{status.text}</Badge>
        {k.fingerprint && <Badge color="#8B95A7" mono>{k.fingerprint}</Badge>}
        {typeof info.name === 'string' && <span className="text-xs text-muted">key “{info.name}”</span>}
        {blocked && <Badge color={colors.danger}>xAI reports this key blocked or disabled</Badge>}
        <span className="text-xs text-muted">
          fast: <b className="font-mono text-ink/85">{u.policy.fast_model.replace('xai:', '')}</b> · strong:{' '}
          <b className="font-mono text-ink/85">{u.policy.strong_model.replace('xai:', '')}</b>
        </span>
        <span className="ml-auto flex items-center gap-2 text-xs text-faint">
          {k.checked_at ? `checked ${formatRelative(k.checked_at)}` : 'checked every 10 minutes'}
          <Button
            size="sm"
            icon={RotateCcw}
            loading={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await api.recheckCloud();
                setTimeout(() => void qc.invalidateQueries({ queryKey: qk }), 3000);
              } finally {
                setBusy(false);
              }
            }}
          >
            Re-check
          </Button>
        </span>
      </div>
      {!k.present && !off && (
        <p className="mt-2 text-[13px] text-muted">
          Add <span className="font-mono text-ink/85">HQ_XAI_API_KEY=…</span> to <span className="font-mono text-ink/85">.env</span> on this Mac (never paste it into chat) and
          restart HQ. Until then everything runs on local models.
        </p>
      )}
      {k.reason && k.present && !k.available && !off && <p className="mt-2 text-[13px] text-amber-200/90">{k.reason}</p>}
    </GlassPanel>
  );
}

function DailyChart({ u }: { u: GrokUsage }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(...u.daily.map((d) => d.spent_usd), u.budget.daily_usd > 0 ? 0 : 0.0001, 0.0001);
  const h = 140;
  const shown = hover != null ? u.daily[hover] : null;
  return (
    <GlassPanel padding="lg" glow={GROK} glowStrength={0.16}>
      <SectionHeader
        kicker={`Last ${u.daily.length} days`}
        title="Grok spend per day"
        icon={BadgeCheck}
        color={GROK}
        right={
          <span className="text-xs text-muted tabular" aria-live="polite">
            {shown ? `${formatDateIST(shown.date)} · ${usd(shown.spent_usd)} · ${shown.calls} calls` : `max ${usd(max)} / day`}
          </span>
        }
      />
      <div
        className="mt-4 flex items-end gap-[2px]"
        style={{ height: h }}
        role="img"
        aria-label={`Grok spend per day over the last ${u.daily.length} days; highest ${usd(max)}`}
        onMouseLeave={() => setHover(null)}
      >
        {u.daily.map((d, i) => {
          const frac = d.spent_usd / max;
          return (
            <div key={d.date} className="flex h-full min-w-0 flex-1 items-end" onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} tabIndex={-1}>
              <div
                className="w-full rounded-t-[4px]"
                style={{
                  height: d.spent_usd > 0 ? `${Math.max(2, frac * 100)}%` : '1px',
                  backgroundColor: d.spent_usd > 0 ? withAlpha(GROK, hover === i ? 1 : 0.75) : 'rgba(255,255,255,0.12)',
                }}
              />
            </div>
          );
        })}
      </div>
      <div className="mt-1.5 flex justify-between text-[10px] text-faint">
        <span>{formatDateIST(u.daily[0]?.date)}</span>
        <span>today</span>
      </div>
      <details className="mt-3 text-xs text-muted">
        <summary className="cursor-pointer select-none text-faint hover:text-muted">Show as a table</summary>
        <table className="mt-2 w-full text-left tabular">
          <thead className="text-faint">
            <tr>
              <th className="py-1 font-medium">Date</th>
              <th className="py-1 text-right font-medium">Calls</th>
              <th className="py-1 text-right font-medium">Spend</th>
            </tr>
          </thead>
          <tbody>
            {[...u.daily].reverse().filter((d) => d.calls > 0).map((d) => (
              <tr key={d.date} className="border-t border-white/[.05]">
                <td className="py-1">{formatDateIST(d.date)}</td>
                <td className="py-1 text-right">{d.calls}</td>
                <td className="py-1 text-right text-ink/85">{usd(d.spent_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </GlassPanel>
  );
}

function Breakdown({ title, rows }: { title: string; rows: { key: string; label: string; calls: number; spent: number; extra?: string }[] }) {
  const total = rows.reduce((a, r) => a + r.spent, 0) || 1;
  return (
    <GlassPanel padding="lg">
      <SectionHeader title={title} icon={Sparkles} color={GROK} />
      {rows.length === 0 ? (
        <p className="mt-3 text-[13px] text-muted">No Grok calls in this period — everything ran locally.</p>
      ) : (
        <ul className="mt-3 space-y-2.5">
          {rows.map((r) => (
            <li key={r.key} className="text-[13px]">
              <div className="flex items-baseline justify-between gap-3">
                <span className="min-w-0 truncate font-mono text-ink/90">{r.label}</span>
                <span className="shrink-0 text-muted tabular">
                  {r.calls} call{r.calls === 1 ? '' : 's'} · <span className="text-ink">{usd(r.spent)}</span>
                </span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/[.06]">
                <div className="h-full rounded-full" style={{ width: `${(r.spent / total) * 100}%`, backgroundColor: GROK }} />
              </div>
              {r.extra && <div className="mt-0.5 text-[11px] text-faint">{r.extra}</div>}
            </li>
          ))}
        </ul>
      )}
    </GlassPanel>
  );
}

function RecentCalls({ u }: { u: GrokUsage }) {
  return (
    <GlassPanel padding="lg">
      <SectionHeader
        title="Recent Grok calls"
        icon={DollarSign}
        color={GROK}
        right={
          <span className="text-xs text-muted">
            {u.cost_sources.reported} exact · {u.cost_sources.estimated} estimated (all time)
          </span>
        }
      />
      {u.recent.length === 0 ? (
        <p className="mt-3 text-[13px] text-muted">No Grok calls yet.</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-[12.5px] tabular">
            <thead className="text-[11px] uppercase tracking-wider text-faint">
              <tr>
                <th className="py-1.5 font-medium">When</th>
                <th className="py-1.5 font-medium">Task</th>
                <th className="py-1.5 font-medium">Model</th>
                <th className="py-1.5 text-right font-medium">Tokens</th>
                <th className="py-1.5 text-right font-medium">Cost</th>
              </tr>
            </thead>
            <tbody>
              {u.recent.map((r, i) => (
                <tr key={`${r.at}-${i}`} className="border-t border-white/[.05]">
                  <td className="py-1.5 text-muted">{formatRelative(r.at)}</td>
                  <td className="py-1.5 font-mono text-ink/85">{r.task_type ?? '—'}</td>
                  <td className="py-1.5 font-mono text-muted">{(r.model ?? '—').replace(/^xai:/, '')}</td>
                  <td className="py-1.5 text-right text-muted">{formatCompact((r.input_tokens ?? 0) + (r.output_tokens ?? 0))}</td>
                  <td className="py-1.5 text-right">
                    <span className="text-ink">{usd(r.cost_usd)}</span>{' '}
                    <span className={r.cost_source === 'reported' ? 'text-emerald-300/80' : 'text-amber-200/80'}>
                      {r.cost_source === 'reported' ? 'exact' : 'est.'}
                    </span>
                    {r.result && r.result !== 'success' && <span className="ml-1 text-red-300/80">{r.result}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </GlassPanel>
  );
}

function RateLimits({ u }: { u: GrokUsage }) {
  const entries = Object.entries(u.rate_limits.headers ?? {});
  return (
    <p className="px-1 text-xs leading-relaxed text-faint">
      {entries.length > 0 ? (
        <>
          Rate limits reported by xAI{u.rate_limits.at ? ` (${formatRelative(u.rate_limits.at)})` : ''}:{' '}
          {entries.map(([k, v]) => `${k.replace('x-ratelimit-', '')} ${v}`).join(' · ')}.{' '}
        </>
      ) : null}
      {u.key.info_source}. HQ's daily limit is yours to set in Settings › AI &amp; budget.
    </p>
  );
}
