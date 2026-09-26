/**
 * Analytics (CONTRACT_E §2): one filter row (real/SIM/all · range) scopes every tile and chart below it —
 * funnel, found vs applied per day, reply rate by source/country/role (always with n), the source yield table,
 * why things were filtered, cloud spend vs cap, local tokens by model, pay histogram and pay by country —
 * plus the Strategist's daily review. Every chart has a hover tooltip and a table view.
 */
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import {
  Banknote,
  ChartColumn,
  Cpu,
  Filter,
  Globe2,
  Inbox,
  LineChart as LineIcon,
  Radar,
  Send,
  Trophy,
  Wallet,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Badge, EmptyState, GlassPanel, SectionHeader, StatCounter } from '@/components';
import { api } from '@/lib/api';
import { cn } from '@/lib/cn';
import { flagEmoji, formatCompact, formatINRCompact, formatPercent, formatRelative, formatUSD, titleCase } from '@/lib/format';
import type { AnalyticsData, AnalyticsRate, AnalyticsScope, SourceYield } from '@/lib/types';
import { Segmented } from '@/components/Segmented';
import { KIND_LABEL, STAGE_META, colors } from '@/theme/tokens';
import {
  AXIS_TICK,
  ChartCard,
  GRID,
  Legend,
  MONEY,
  SERIES,
  SURFACE,
  TipBox,
  VALUE_LABEL,
  barsHeight,
  shortDate,
  type Column,
} from './kit';
import { StrategistPanel } from './StrategistPanel';

const PINK = '#F472B6';
const RANGES = [7, 30, 90] as const;
type Dim = 'source' | 'country' | 'role' | 'kind';
const DIM_OPTIONS = [
  { value: 'source' as const, label: 'Source' },
  { value: 'country' as const, label: 'Country' },
  { value: 'role' as const, label: 'Role' },
  { value: 'kind' as const, label: 'Kind' },
];

function readPref<T extends string | number>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    const v = (typeof fallback === 'number' ? Number(raw) : raw) as T;
    return allowed.includes(v) ? v : fallback;
  } catch {
    return fallback;
  }
}

function writePref(key: string, v: string | number) {
  try {
    localStorage.setItem(key, String(v));
  } catch {
    /* storage unavailable: the choice just isn't remembered */
  }
}

export default function Analytics() {
  const [scope, setScope] = useState<AnalyticsScope>(() => readPref('hq.analytics.scope', ['all', 'real', 'sim'] as const, 'all'));
  const [days, setDays] = useState<number>(() => readPref('hq.analytics.days', RANGES, 30));
  useEffect(() => {
    document.title = 'Analytics · Agent HQ';
  }, []);
  useEffect(() => writePref('hq.analytics.scope', scope), [scope]);
  useEffect(() => writePref('hq.analytics.days', days), [days]);
  const q = useQuery({
    queryKey: ['analytics', scope, days],
    queryFn: () => api.analytics(scope, days),
    placeholderData: keepPreviousData,
    refetchInterval: 60_000,
  });
  const d = q.data;

  return (
    <div className="space-y-5">
      <SectionHeader as="h1" size="lg" kicker="Trends" title="Analytics" />
      {/* one filter row scoping everything below */}
      <div className="flex flex-wrap items-center gap-2">
        <Segmented
          ariaLabel="Which opportunities"
          value={scope}
          onChange={setScope}
          color={PINK}
          options={[
            { value: 'all', label: 'All' },
            { value: 'real', label: 'Real' },
            { value: 'sim', label: 'SIM' },
          ]}
        />
        <Segmented
          ariaLabel="Date range"
          value={days}
          onChange={setDays}
          color={PINK}
          options={RANGES.map((r) => ({ value: r, label: `${r} days` }))}
        />
        {d && d.totals.simulated > 0 && scope !== 'real' && (
          <Badge color="#38BDF8" size="md" title="Simulated roles from the simulator are included">
            includes {d.totals.simulated} SIM
          </Badge>
        )}
      </div>

      {q.isError && !d ? (
        <GlassPanel>
          <EmptyState icon={ChartColumn} color={PINK} title="Couldn't load analytics" hint={(q.error as Error).message} />
        </GlassPanel>
      ) : !d ? (
        <div className="grid gap-4 md:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-64 animate-breathe rounded-2xl bg-white/[.03]" />
          ))}
        </div>
      ) : (
        <div className={cn('space-y-5 transition-opacity duration-200', q.isFetching && q.isPlaceholderData && 'opacity-60')}>
          <Tiles d={d} />
          <div className="grid gap-5 xl:grid-cols-2">
            <FunnelCard d={d} />
            <ActivityCard d={d} />
            <ReplyRateCard d={d} />
            <FilteredCard d={d} />
          </div>
          <SourcesCard rows={d.sources} />
          <div className="grid gap-5 xl:grid-cols-2">
            <PayHistogramCard d={d} />
            <PayByCountryCard d={d} />
            <SpendCard d={d} />
            <TokensCard d={d} />
          </div>
        </div>
      )}
      <StrategistPanel />
    </div>
  );
}

// ── tiles ────────────────────────────────────────────────────────────────────────────────────────────
function Tiles({ d }: { d: AnalyticsData }) {
  const t = d.totals;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <Tile><StatCounter label="In the pipeline" value={t.opportunities} icon={Radar} accent="#22D3EE" size="sm"
        sub={`${t.filtered} filtered out · ${t.history} legacy`} /></Tile>
      <Tile><StatCounter label="Applied" value={t.applied} icon={Send} accent={PINK} size="sm"
        sub={`${d.applications_per_day.reduce((a, x) => a + x.total, 0)} in the last ${d.days} days`} /></Tile>
      <Tile><StatCounter label="Reply rate" value={t.reply_rate == null ? null : Math.round(t.reply_rate * 100)}
        format={(n) => `${n}%`} icon={Inbox} accent="#A3E635" size="sm"
        sub={t.applied ? `${t.replied} of ${t.applied} replied` : 'no applications yet'} /></Tile>
      <Tile><StatCounter label="Interviews" value={t.interviews} icon={Trophy} accent="#E879F9" size="sm"
        sub={`${t.offers} offer${t.offers === 1 ? '' : 's'}`} /></Tile>
      <Tile><StatCounter label="Median pay" value={d.pay_histogram.median} money size="sm" icon={Banknote}
        format={(n) => `${formatINRCompact(n)}`} sub="₹/month, live roles" /></Tile>
      <Tile><StatCounter label="Best pay" value={d.pay_histogram.max} money size="sm" icon={Wallet}
        format={(n) => `${formatINRCompact(n)}`} sub="highest ₹/month in play" /></Tile>
    </div>
  );
}

function Tile({ children }: { children: React.ReactNode }) {
  return <GlassPanel padding="md" className="min-w-0">{children}</GlassPanel>;
}

// ── funnel ───────────────────────────────────────────────────────────────────────────────────────────
function FunnelCard({ d }: { d: AnalyticsData }) {
  const rows = d.funnel.map((f, i) => {
    const prev = i ? d.funnel[i - 1]!.n : f.n;
    return { label: STAGE_META[f.stage]?.label ?? f.stage, n: f.n, conv: i && prev ? f.n / prev : null };
  });
  const empty = !rows[0]?.n;
  return (
    <ChartCard
      kicker="Funnel"
      title="Found → offer"
      icon={Filter}
      color="#22D3EE"
      note="How many opportunities reached each step (legacy items excluded)."
      empty={empty ? <EmptyState compact title="Nothing found yet" hint="The Scout's first sweep fills this." /> : undefined}
      table={{
        columns: [
          { key: 'label', label: 'Step' },
          { key: 'n', label: 'Reached', align: 'right' },
          { key: 'conv', label: 'From previous', align: 'right', render: (r) => (r.conv == null ? '—' : formatPercent(r.conv)) },
        ] as Column<(typeof rows)[number]>[],
        rows,
      }}
    >
      <ResponsiveContainer width="100%" height={barsHeight(rows.length)}>
        <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 56, bottom: 0, left: 0 }} barCategoryGap={6}>
          <CartesianGrid horizontal={false} stroke={GRID} />
          <XAxis type="number" allowDecimals={false} tick={AXIS_TICK} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="label" width={78} tick={AXIS_TICK} axisLine={false} tickLine={false} />
          <Tooltip
            cursor={{ fill: 'rgba(255,255,255,0.04)' }}
            content={({ active, payload }) => {
              const r = active && payload?.[0]?.payload as (typeof rows)[number] | undefined;
              return r ? <TipBox title={r.label} rows={[{ color: SERIES[0], name: 'reached', value: r.n },
                ...(r.conv != null ? [{ color: 'transparent', name: 'of the step before', value: formatPercent(r.conv) }] : [])]} /> : null;
            }}
          />
          <Bar dataKey="n" fill={SERIES[0]} radius={[0, 4, 4, 0]} maxBarSize={20} isAnimationActive={false}>
            <LabelList dataKey="n" position="right" style={VALUE_LABEL} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

// ── activity per day ─────────────────────────────────────────────────────────────────────────────────
function ActivityCard({ d }: { d: AnalyticsData }) {
  const rows = useMemo(() => {
    const applied = new Map(d.applications_per_day.map((a) => [a.date, a.total]));
    return d.found_per_day.map((f) => ({ date: f.date, found: f.found, applied: applied.get(f.date) ?? 0 }));
  }, [d]);
  const empty = rows.every((r) => !r.found && !r.applied);
  return (
    <ChartCard
      kicker="Per day (IST)"
      title="Found vs applied"
      icon={LineIcon}
      color={SERIES[0]}
      toolbar={!empty ? <Legend items={[{ color: SERIES[0], label: 'Found' }, { color: SERIES[1], label: 'Applied' }]} /> : undefined}
      note={`New opportunities and submitted applications per day, last ${d.days} days.`}
      empty={empty ? <EmptyState compact title="No activity in this range" /> : undefined}
      table={{
        columns: [
          { key: 'date', label: 'Day' },
          { key: 'found', label: 'Found', align: 'right' },
          { key: 'applied', label: 'Applied', align: 'right' },
        ] as Column<(typeof rows)[number]>[],
        rows: [...rows].reverse(),
      }}
    >
      <ResponsiveContainer width="100%" height={236}>
        <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="date" tickFormatter={shortDate} tick={AXIS_TICK} axisLine={false} tickLine={false}
            minTickGap={24} />
          <YAxis allowDecimals={false} tick={AXIS_TICK} axisLine={false} tickLine={false} width={40} />
          <Tooltip
            cursor={{ stroke: 'rgba(255,255,255,0.25)', strokeWidth: 1 }}
            content={({ active, payload, label }) =>
              active && payload?.length ? (
                <TipBox title={shortDate(String(label))} rows={[
                  { color: SERIES[0], name: 'found', value: payload.find((p) => p.dataKey === 'found')?.value as number },
                  { color: SERIES[1], name: 'applied', value: payload.find((p) => p.dataKey === 'applied')?.value as number },
                ]} />
              ) : null
            }
          />
          <Line type="monotone" dataKey="found" stroke={SERIES[0]} strokeWidth={2} dot={false} isAnimationActive={false}
            activeDot={{ r: 4, stroke: SURFACE, strokeWidth: 2 }} strokeLinecap="round" strokeLinejoin="round" />
          <Line type="monotone" dataKey="applied" stroke={SERIES[1]} strokeWidth={2} dot={false} isAnimationActive={false}
            activeDot={{ r: 4, stroke: SURFACE, strokeWidth: 2 }} strokeLinecap="round" strokeLinejoin="round" />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

// ── reply rate ───────────────────────────────────────────────────────────────────────────────────────
function dimLabel(dim: Dim, r: AnalyticsRate): string {
  if (dim === 'country') return `${flagEmoji(r.key)} ${r.key}`;
  if (dim === 'kind') return KIND_LABEL[r.key] ?? titleCase(r.key);
  if (dim === 'role') return r.key === 'ml' ? 'ML / AI' : titleCase(r.key);
  return r.label;
}

function ReplyRateCard({ d }: { d: AnalyticsData }) {
  const [dim, setDim] = useState<Dim>('source');
  const rows = d.reply_rates[dim].slice(0, 10).map((r) => ({
    ...r, name: dimLabel(dim, r), pct: Math.round(r.rate * 100), text: `${Math.round(r.rate * 100)}% · ${r.replied}/${r.applied}`,
  }));
  return (
    <ChartCard
      kicker="Replies"
      title="Reply rate"
      icon={Inbox}
      color="#A3E635"
      toolbar={<Segmented ariaLabel="Reply rate by" value={dim} onChange={setDim} options={DIM_OPTIONS} color="#A3E635" />}
      note="Share of applications that got any reply (rejections count). n = applications; under 5 is too early to tell."
      empty={!rows.length ? <EmptyState compact title="No applications yet" hint="Rates appear after the first applications go out." /> : undefined}
      table={{
        columns: [
          { key: 'name', label: titleCase(dim) },
          { key: 'applied', label: 'Applied (n)', align: 'right' },
          { key: 'replied', label: 'Replied', align: 'right' },
          { key: 'interviews', label: 'Interviews', align: 'right' },
          { key: 'pct', label: 'Rate', align: 'right', render: (r) => `${r.pct}%` },
        ] as Column<(typeof rows)[number]>[],
        rows,
      }}
    >
      <ResponsiveContainer width="100%" height={barsHeight(rows.length)}>
        <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 84, bottom: 0, left: 0 }} barCategoryGap={6}>
          <CartesianGrid horizontal={false} stroke={GRID} />
          <XAxis type="number" domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={AXIS_TICK} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="name" width={140} tick={AXIS_TICK} axisLine={false} tickLine={false} />
          <Tooltip
            cursor={{ fill: 'rgba(255,255,255,0.04)' }}
            content={({ active, payload }) => {
              const r = active && payload?.[0]?.payload as (typeof rows)[number] | undefined;
              return r ? <TipBox title={r.name} rows={[
                { color: '#A3E635', name: 'reply rate', value: `${r.pct}%` },
                { color: 'transparent', name: 'applications (n)', value: r.applied },
                { color: 'transparent', name: 'interviews', value: r.interviews },
              ]} /> : null;
            }}
          />
          <Bar dataKey="pct" fill={SERIES[2]} radius={[0, 4, 4, 0]} maxBarSize={20} minPointSize={2} isAnimationActive={false}>
            <LabelList dataKey="text" position="right" style={VALUE_LABEL} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

// ── why things were filtered ─────────────────────────────────────────────────────────────────────────
const REASON_LABEL: Record<string, string> = {
  ineligible: 'Not eligible', scam: 'Scam / fee', mill: 'Known job mill', expired: 'Expired / closed', unpaid: 'Unpaid',
  pay: 'Pay too low',
  location: 'Location', availability: 'Dates / hours', duplicate: 'Duplicate', low_fit: 'Fit below threshold',
  unreadable: 'Posting unreadable', other: 'Other',
};

function FilteredCard({ d }: { d: AnalyticsData }) {
  const rows = d.gate_failures.filtered.map((r) => ({ ...r, name: REASON_LABEL[r.reason] ?? titleCase(r.reason) }));
  const drafts = d.gate_failures.drafts;
  const empty = !rows.length && !drafts.length;
  return (
    <ChartCard
      kicker="Gates"
      title="Why things were stopped"
      icon={Filter}
      color="#94A3B8"
      note={`${d.totals.filtered} opportunities filtered out; ${drafts.reduce((a, x) => a + x.n, 0)} draft check failures (rewritten automatically).`}
      empty={empty ? <EmptyState compact title="Nothing stopped yet" /> : undefined}
      table={{
        columns: [
          { key: 'name', label: 'Reason' },
          { key: 'n', label: 'Count', align: 'right' },
        ] as Column<{ name: string; n: number }>[],
        rows: [...rows, ...drafts.map((g) => ({ name: `Draft · ${titleCase(g.gate.replace('_', ' '))}${g.rule ? ` · ${g.rule}` : ''}`, n: g.n }))],
      }}
    >
      {rows.length > 0 && (
        <ResponsiveContainer width="100%" height={barsHeight(rows.length)}>
          <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 40, bottom: 0, left: 0 }} barCategoryGap={6}>
            <CartesianGrid horizontal={false} stroke={GRID} />
            <XAxis type="number" allowDecimals={false} tick={AXIS_TICK} axisLine={false} tickLine={false} />
            <YAxis type="category" dataKey="name" width={120} tick={AXIS_TICK} axisLine={false} tickLine={false} />
            <Tooltip
              cursor={{ fill: 'rgba(255,255,255,0.04)' }}
              content={({ active, payload }) => {
                const r = active && payload?.[0]?.payload as (typeof rows)[number] | undefined;
                return r ? <TipBox title={r.name} rows={[{ color: SERIES[0], name: 'filtered', value: r.n }]} /> : null;
              }}
            />
            <Bar dataKey="n" fill={SERIES[0]} radius={[0, 4, 4, 0]} maxBarSize={20} isAnimationActive={false}>
              <LabelList dataKey="n" position="right" style={VALUE_LABEL} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
      {drafts.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-[11px] uppercase tracking-[0.14em] text-muted">Draft checks that failed</div>
          <ul className="flex flex-wrap gap-1.5">
            {drafts.slice(0, 8).map((g) => (
              <li key={`${g.gate}-${g.rule}`}>
                <Badge color="#94A3B8" size="md" mono>
                  {g.rule ?? titleCase(g.gate.replace('_', ' '))} · {g.n}
                </Badge>
              </li>
            ))}
          </ul>
        </div>
      )}
    </ChartCard>
  );
}

// ── sources ──────────────────────────────────────────────────────────────────────────────────────────
function SourcesCard({ rows }: { rows: SourceYield[] }) {
  const cols: Column<SourceYield>[] = [
    { key: 'name', label: 'Source', render: (r) => <span className="font-medium text-ink">{r.name}</span> },
    { key: 'kind', label: 'Kind', render: (r) => <span className="text-muted">{r.kind}</span> },
    { key: 'found', label: 'Found', align: 'right' },
    { key: 'verified', label: 'Verified', align: 'right' },
    { key: 'filtered', label: 'Filtered', align: 'right' },
    { key: 'applied', label: 'Applied', align: 'right' },
    { key: 'replies', label: 'Replies', align: 'right' },
    { key: 'median_pay_inr', label: 'Median ₹/mo', align: 'right', render: (r) => (r.median_pay_inr == null ? '—' : formatINRCompact(r.median_pay_inr)) },
    {
      key: 'health', label: 'Health', render: (r) =>
        r.enabled == null ? <span className="text-faint">—</span>
          : !r.enabled ? <Badge color="#64748B" size="xs">off</Badge>
            : r.errors >= 5 ? <Badge color="#F87171" size="xs">{r.errors} errors</Badge>
              : r.errors ? <Badge color="#FBBF24" size="xs">{r.errors} error{r.errors === 1 ? '' : 's'}</Badge>
                : <Badge color="#34D399" size="xs">{r.last_ok_at ? `ok · ${formatRelative(r.last_ok_at)}` : 'on'}</Badge>,
    },
  ];
  return (
    <GlassPanel padding="lg" glow="#22D3EE" glowStrength={0.14}>
      <SectionHeader kicker="Which sources work" title="Source yield" icon={Radar} color="#22D3EE" />
      <p className="mt-1 text-[12.5px] text-muted">Per source: how many roles it found, how many survived the checks, and what came of them.</p>
      <div className="mt-4">
        {rows.length ? <DataTableWide columns={cols} rows={rows} /> : <EmptyState compact title="No sources have found anything yet" hint="Settings › Sources lists every board and when it last answered." />}
      </div>
    </GlassPanel>
  );
}

function DataTableWide({ columns, rows }: { columns: Column<SourceYield>[]; rows: SourceYield[] }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-white/[.06]">
      <table className="w-full min-w-[760px] text-left text-[12.5px]">
        <thead className="bg-white/[.02]">
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col" className={cn('px-3 py-2 font-medium text-muted', c.align === 'right' && 'text-right')}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-white/[.05]">
          {rows.map((r) => (
            <tr key={r.source_id} className="hover:bg-white/[.02]">
              {columns.map((c) => (
                <td key={c.key} className={cn('px-3 py-2 text-ink/90', c.align === 'right' && 'text-right tabular')}>
                  {c.render ? c.render(r) : String((r as unknown as Record<string, unknown>)[c.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── pay ──────────────────────────────────────────────────────────────────────────────────────────────
function PayHistogramCard({ d }: { d: AnalyticsData }) {
  const h = d.pay_histogram;
  // short tick labels so six buckets fit a phone; the note and tooltip carry the ₹ / month
  const rows = h.buckets.map((b) => ({ label: b.label, tick: b.label.replace('₹', '').replace('< ', '<'), n: b.n }));
  const known = rows.reduce((a, r) => a + r.n, 0);
  return (
    <ChartCard
      kicker="How much they pay"
      title="Pay histogram"
      icon={Banknote}
      color={colors.gold}
      note={`Monthly pay in ₹ for live roles (n=${known}${h.unknown ? `; ${h.unknown} with unknown pay` : ''}).`}
      empty={!known ? <EmptyState compact title="No pay data yet" /> : undefined}
      table={{ columns: [{ key: 'label', label: '₹ / month' }, { key: 'n', label: 'Roles', align: 'right' }] as Column<(typeof rows)[number]>[], rows }}
    >
      <ResponsiveContainer width="100%" height={236}>
        <BarChart data={rows} margin={{ top: 18, right: 8, bottom: 0, left: -12 }} barCategoryGap={4}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="tick" tick={AXIS_TICK} axisLine={false} tickLine={false} interval={0} />
          <YAxis allowDecimals={false} tick={AXIS_TICK} axisLine={false} tickLine={false} width={40} />
          <Tooltip
            cursor={{ fill: 'rgba(255,255,255,0.04)' }}
            content={({ active, payload }) => {
              const r = active && payload?.[0]?.payload as (typeof rows)[number] | undefined;
              return r ? <TipBox title={`${r.label} / month`} rows={[{ color: MONEY, name: 'roles', value: r.n }]} /> : null;
            }}
          />
          <Bar dataKey="n" fill={MONEY} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false}>
            <LabelList dataKey="n" position="top" style={VALUE_LABEL} formatter={(v: unknown) => (Number(v) ? String(v) : '')} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function PayByCountryCard({ d }: { d: AnalyticsData }) {
  const rows = d.pay_by_country.slice(0, 10).map((r) => ({
    ...r, name: `${flagEmoji(r.country)} ${r.country}`, text: `${formatINRCompact(r.median_inr)} · n=${r.n}`,
  }));
  return (
    <ChartCard
      kicker="Where the money is"
      title="Pay by country"
      icon={Globe2}
      color={colors.gold}
      note="Median ₹/month of live roles per country, with n. Ratio = pay ÷ local living cost."
      empty={!rows.length ? <EmptyState compact title="No pay data yet" /> : undefined}
      table={{
        columns: [
          { key: 'name', label: 'Country' },
          { key: 'n', label: 'Roles (n)', align: 'right' },
          { key: 'median_inr', label: 'Median ₹/mo', align: 'right', render: (r) => formatINRCompact(r.median_inr) },
          { key: 'max_inr', label: 'Max ₹/mo', align: 'right', render: (r) => formatINRCompact(r.max_inr) },
          { key: 'median_ratio', label: 'vs living cost', align: 'right', render: (r) => (r.median_ratio == null ? '—' : `${r.median_ratio}×`) },
        ] as Column<(typeof rows)[number]>[],
        rows,
      }}
    >
      <ResponsiveContainer width="100%" height={barsHeight(rows.length)}>
        <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 96, bottom: 0, left: 0 }} barCategoryGap={6}>
          <CartesianGrid horizontal={false} stroke={GRID} />
          <XAxis type="number" tickFormatter={(v) => formatINRCompact(Number(v))} tick={AXIS_TICK} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="name" width={64} tick={AXIS_TICK} axisLine={false} tickLine={false} />
          <Tooltip
            cursor={{ fill: 'rgba(255,255,255,0.04)' }}
            content={({ active, payload }) => {
              const r = active && payload?.[0]?.payload as (typeof rows)[number] | undefined;
              return r ? <TipBox title={r.name} rows={[
                { color: MONEY, name: 'median / month', value: formatINRCompact(r.median_inr) },
                { color: 'transparent', name: 'max / month', value: formatINRCompact(r.max_inr) },
                { color: 'transparent', name: 'roles (n)', value: r.n },
                ...(r.median_ratio != null ? [{ color: 'transparent', name: 'vs living cost', value: `${r.median_ratio}×` }] : []),
              ]} /> : null;
            }}
          />
          <Bar dataKey="median_inr" fill={MONEY} radius={[0, 4, 4, 0]} maxBarSize={20} isAnimationActive={false}>
            <LabelList dataKey="text" position="right" style={VALUE_LABEL} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

// ── cloud spend & tokens ─────────────────────────────────────────────────────────────────────────────
function SpendCard({ d }: { d: AnalyticsData }) {
  const s = d.cloud_spend;
  const today = s.days[s.days.length - 1];
  const total = s.days.reduce((a, x) => a + x.usd, 0);
  const pct = today ? Math.min(1, today.usd / (s.cap_usd || 1)) : 0;
  const rows = s.days.map((x) => ({ ...x, label: shortDate(x.date) }));
  const meter = pct >= 0.9 ? '#F87171' : pct >= 0.6 ? '#FBBF24' : '#34D399';
  return (
    <ChartCard
      kicker="Budget"
      title="Cloud spend vs cap"
      icon={Wallet}
      color={colors.gold}
      note={`${formatUSD(total)} over ${d.days} days · daily cap ${formatUSD(s.cap_usd)} and ${s.call_cap} calls (Settings › Budget).`}
      table={{
        columns: [
          { key: 'date', label: 'Day' },
          { key: 'usd', label: 'Spend', align: 'right', render: (r) => formatUSD(r.usd) },
          { key: 'calls', label: 'Calls', align: 'right' },
        ] as Column<(typeof rows)[number]>[],
        rows: [...rows].reverse(),
      }}
    >
      <div className="mb-4">
        <div className="flex items-baseline justify-between text-[12.5px]">
          <span className="text-muted">Today</span>
          <span><span className="font-semibold text-ink">{formatUSD(today?.usd ?? 0)}</span> <span className="text-muted">of {formatUSD(s.cap_usd)} · {today?.calls ?? 0}/{s.call_cap} calls</span></span>
        </div>
        <div className="mt-1.5 h-1.5 overflow-hidden rounded-full" style={{ backgroundColor: 'rgba(255,255,255,0.08)' }}
          role="meter" aria-valuemin={0} aria-valuemax={s.cap_usd} aria-valuenow={today?.usd ?? 0} aria-label="Cloud spend today vs cap">
          <div className="h-full origin-left rounded-full" style={{ width: `${Math.max(pct * 100, pct ? 2 : 0)}%`, backgroundColor: meter }} />
        </div>
      </div>
      {total > 0 ? (
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={rows} margin={{ top: 6, right: 8, bottom: 0, left: -6 }} barCategoryGap={2}>
            <CartesianGrid vertical={false} stroke={GRID} />
            <XAxis dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} minTickGap={24} />
            <YAxis tickFormatter={(v) => `$${Number(v).toFixed(2)}`} tick={AXIS_TICK} axisLine={false} tickLine={false} width={52} />
            <Tooltip
              cursor={{ fill: 'rgba(255,255,255,0.04)' }}
              content={({ active, payload }) => {
                const r = active && payload?.[0]?.payload as (typeof rows)[number] | undefined;
                return r ? <TipBox title={r.label} rows={[{ color: MONEY, name: 'spent', value: formatUSD(r.usd) },
                  { color: 'transparent', name: 'calls', value: r.calls }]} /> : null;
              }}
            />
            <Bar dataKey="usd" fill={MONEY} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false}>
              {rows.map((r) => <Cell key={r.date} fill={r.usd > s.cap_usd ? '#F87171' : MONEY} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <p className="text-[12.5px] text-faint">No cloud calls in this range — local models or the built-in rules did the work.</p>
      )}
    </ChartCard>
  );
}

function TokensCard({ d }: { d: AnalyticsData }) {
  const rows = d.tokens_by_model.filter((m) => !m.cloud).slice(0, 8).map((m) => ({
    ...m, name: m.simulated ? `${m.label} (sim)` : m.label, text: `${formatCompact(m.total_tokens)} tok`,
  }));
  return (
    <ChartCard
      kicker="Local models"
      title="Tokens by model"
      icon={Cpu}
      color="#F59E0B"
      note={`Prompt + completion tokens per local model, last ${d.days} days. Free — they run on this Mac.`}
      empty={!rows.length ? <EmptyState compact title="No local model runs yet" hint="Models page: rescan or start Ollama / LM Studio." /> : undefined}
      table={{
        columns: [
          { key: 'name', label: 'Model' },
          { key: 'runs', label: 'Runs', align: 'right' },
          { key: 'prompt_tokens', label: 'Prompt', align: 'right', render: (r) => formatCompact(r.prompt_tokens) },
          { key: 'completion_tokens', label: 'Completion', align: 'right', render: (r) => formatCompact(r.completion_tokens) },
          { key: 'avg_tok_s', label: 'Avg tok/s', align: 'right', render: (r) => (r.avg_tok_s == null ? '—' : String(r.avg_tok_s)) },
        ] as Column<(typeof rows)[number]>[],
        rows,
      }}
    >
      <ResponsiveContainer width="100%" height={barsHeight(rows.length)}>
        <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 72, bottom: 0, left: 0 }} barCategoryGap={6}>
          <CartesianGrid horizontal={false} stroke={GRID} />
          <XAxis type="number" tickFormatter={(v) => formatCompact(Number(v))} tick={AXIS_TICK} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="name" width={170} tick={AXIS_TICK} axisLine={false} tickLine={false} />
          <Tooltip
            cursor={{ fill: 'rgba(255,255,255,0.04)' }}
            content={({ active, payload }) => {
              const r = active && payload?.[0]?.payload as (typeof rows)[number] | undefined;
              return r ? <TipBox title={r.name} rows={[
                { color: SERIES[0], name: 'tokens', value: formatCompact(r.total_tokens) },
                { color: 'transparent', name: 'runs', value: r.runs },
                ...(r.avg_tok_s ? [{ color: 'transparent', name: 'avg tok/s', value: r.avg_tok_s }] : []),
              ]} /> : null;
            }}
          />
          <Bar dataKey="total_tokens" fill={SERIES[0]} radius={[0, 4, 4, 0]} maxBarSize={20} isAnimationActive={false}>
            <LabelList dataKey="text" position="right" style={VALUE_LABEL} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
