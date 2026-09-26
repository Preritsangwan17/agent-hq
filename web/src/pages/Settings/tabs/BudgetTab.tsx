/** AI & budget: the local/Grok switches, API-saving mode, Grok's daily limits with a live gauge, which Grok models
 * are used, and the final sign-off rule. The full usage dashboard lives at /usage. */
import { useQuery } from '@tanstack/react-query';
import { BadgeCheck, CalendarClock, Cpu, DollarSign, Hash, HandHelping, KeyRound, Moon, Power, Sparkles, Star, Wand2, type LucideIcon } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { Badge } from '@/components/Badge';
import { EnginesControl, ModeControl } from '@/components/AIEngines';
import { TextInput } from '@/pages/Agents/formKit';
import type { ReactNode } from 'react';
import { GlassPanel } from '@/components/GlassPanel';
import { ProgressBar } from '@/components/ProgressBar';
import { SectionHeader } from '@/components/SectionHeader';
import { api } from '@/lib/api';
import { formatCompact, formatDateTimeIST, formatUSD } from '@/lib/format';
import { useSettings, useStats } from '@/lib/store';
import { colors, withAlpha } from '@/theme/tokens';
import { NumberField, SettingRow, Slider, Toggle } from '../controls';
import { Callout, Section } from '../parts';
import { useSaver } from '../saver';

const GROK = '#E879F9';

export function BudgetTab() {
  const s = useSettings();
  const stats = useStats();
  const live = useQuery({ queryKey: ['budget'], queryFn: api.budget, refetchInterval: 15_000 }).data;
  const { save } = useSaver();
  const budget = Number(s.cloud_daily_budget_usd) || 0;
  const cap = Number(s.cloud_daily_call_cap) || 0;
  const spent = live?.spent_usd ?? stats?.cloud_cost_today_usd ?? 0;
  const calls = live?.calls ?? stats?.cloud_calls_today ?? 0;
  const frac = budget > 0 ? Math.min(1, spent / budget) : spent > 0 ? 1 : 0;
  const callFrac = cap > 0 ? Math.min(1, calls / cap) : 0;
  const hot = frac >= 0.85 || callFrac >= 0.85;

  return (
    <div className="space-y-5">
      <Section kicker="On / off" title="Which AI HQ may use" icon={Power} color="#34D399" rows={false}
        description="Local models (free, private) and Grok (paid) can each be switched off. Individual local models have their own switch on the Models page.">
        <EnginesControl />
        <div className="mt-5 mb-2 text-[11px] font-medium uppercase tracking-[0.12em] text-muted">How much Grok to use</div>
        <ModeControl />
      </Section>

      <GlassPanel padding="lg" glow={GROK} accentTop>
        <SectionHeader
          kicker="Today · resets at midnight IST"
          title="Grok spend"
          icon={Sparkles}
          color={GROK}
          right={
            <Link to="/usage" className="text-xs font-medium text-cyan-300 hover:text-cyan-200">
              Full usage dashboard →
            </Link>
          }
        />
        <div className="mt-5 grid items-center gap-6 md:grid-cols-[auto_minmax(0,1fr)]">
          <RingGauge frac={frac} color={hot ? colors.warn : GROK} spent={spent} budget={budget} />
          <div className="grid min-w-0 gap-4 sm:grid-cols-2">
            <Metric icon={DollarSign} label="Spent / limit" value={`${formatUSD(spent, spent < 0.1 ? 4 : 2)} / ${formatUSD(budget)}`} sub={`${Math.round(frac * 100)}% of today's limit`} color={GROK} />
            <Metric
              icon={Hash}
              label="Grok calls"
              value={`${calls} / ${cap}`}
              sub={<ProgressBar value={callFrac} color={callFrac >= 0.85 ? colors.warn : GROK} height={4} className="mt-1.5" />}
              color={GROK}
            />
            <Metric
              icon={Cpu}
              label="Local tokens today"
              value={formatCompact(stats?.local_tokens_today ?? 0)}
              sub="On-device models · no spend"
              color="#22D3EE"
            />
            <Metric
              icon={CalendarClock}
              label="Waiting on the limit"
              value={`${live?.deferred_tasks ?? 0} task${live?.deferred_tasks === 1 ? '' : 's'}`}
              sub={live?.resets_at ? `resets ${formatDateTimeIST(live.resets_at)} IST` : 'Grok tasks wait for midnight IST'}
              color={colors.warn}
            />
          </div>
        </div>
      </GlassPanel>

      <Section kicker="Limits" title="Daily Grok limit" icon={DollarSign} color={GROK}>
        <SettingRow
          title="Limit per day"
          phase="live"
          htmlFor="grok-budget"
          description="HQ never spends more than this on Grok in a day (exact: HQ enforces it). Over it, Grok work waits until midnight IST."
          control={
            <NumberField
              id="grok-budget"
              aria-label="Grok limit in US dollars per day"
              value={budget}
              onChange={(v) => save({ cloud_daily_budget_usd: v })}
              min={0}
              max={1000}
              step={0.5}
              prefix="$"
              suffix="/day"
              display={(v) => v.toFixed(2)}
              className="w-36"
            />
          }
        >
          <Slider
            aria-label="Grok limit per day"
            value={Math.min(budget, 10)}
            min={0}
            max={10}
            step={0.25}
            color={GROK}
            format={(v) => formatUSD(v)}
            onChange={(v) => save({ cloud_daily_budget_usd: v }, 350)}
            pins={spent > 0 ? [{ value: Math.min(spent, 10), color: colors.warn, label: 'Spent today' }] : undefined}
            marks={[
              { value: 0, label: '$0' },
              { value: 2, label: '$2 default' },
              { value: 5, label: '$5' },
              { value: 10, label: '$10' },
            ]}
          />
        </SettingRow>
        <SettingRow
          icon={Hash}
          color={GROK}
          title="Calls per day"
          phase="live"
          htmlFor="grok-calls"
          description="A second ceiling, whatever each call costs."
          control={
            <NumberField
              id="grok-calls"
              aria-label="Grok calls per day"
              value={cap}
              onChange={(v) => save({ cloud_daily_call_cap: v })}
              min={0}
              max={10_000}
              step={5}
              integer
              stepper
              className="w-36"
            />
          }
        />
        <SettingRow
          title="Cap per call"
          htmlFor="per-call"
          description="A single Grok call may not cost more than this (checked before sending)."
          control={
            <NumberField
              id="per-call"
              aria-label="Grok per-call cap in US dollars"
              value={Number(s.cloud_per_call_cap_usd ?? 0.5)}
              onChange={(v) => save({ cloud_per_call_cap_usd: v })}
              min={0.01}
              max={5}
              step={0.05}
              prefix="$"
              display={(v) => v.toFixed(2)}
              className="w-32"
            />
          }
        />
        <SettingRow
          icon={Star}
          color="#FBBF24"
          title="“Important” from match score"
          htmlFor="important"
          description="In Balanced mode, applications at or above this match score may use the strong Grok model and a polish. API-saving mode also allows a Grok rescue for these when the local writer fails."
          control={
            <NumberField
              id="important"
              aria-label="Important application match score threshold"
              value={Number(s.important_score_threshold ?? 75)}
              onChange={(v) => save({ important_score_threshold: v })}
              min={0}
              max={100}
              step={1}
              integer
              stepper
              className="w-32"
            />
          }
        />
      </Section>

      <ProviderSection live={live} />

      <Section kicker="Safety" title="Final sign-off" icon={Wand2} color={GROK}>
        <SettingRow
          icon={BadgeCheck}
          color={GROK}
          title="Require an independent sign-off"
          htmlFor="signoff"
          description="Nothing is submitted until a model that didn't write the text checks every claim against your facts: a second local model when one qualifies (free), Grok otherwise. Turning this off leaves the deterministic rules and the local checker."
          control={<Toggle id="signoff" label="Require an independent sign-off" checked={s.signoff_required !== false} onChange={(v) => save({ signoff_required: v })} color={GROK} size="lg" />}
        />
      </Section>

      <div className="grid gap-3 md:grid-cols-2">
        <Callout icon={Moon} color="#818CF8" title="Over the limit">
          Grok tasks wait until midnight IST; local models keep working and nothing is skipped.
        </Callout>
        <Callout icon={HandHelping} color="#FB923C" title="Deadlines still win">
          Anything due within 48 h that is blocked on the Grok limit becomes a Needs Prerit item instead of waiting.
        </Callout>
      </div>
      {live && Object.keys(live.by_task).length > 0 && (
        <Section kicker="Today" title="Grok spend by task" icon={Sparkles} color={GROK} rows={false}>
          <ul className="divide-y divide-white/[.06] text-[13px]">
            {Object.entries(live.by_task).map(([task, v]) => (
              <li key={task} className="flex items-center justify-between py-2">
                <span className="font-mono text-ink/85">{task}</span>
                <span className="text-muted tabular">
                  {v.calls} call{v.calls === 1 ? '' : 's'} · {formatUSD(v.spent_usd, 4)}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}
      <p className="px-1 text-xs text-faint">
        {live?.cloud_available === false
          ? 'Grok is not reachable, so nothing is being spent; local models carry on.'
          : `Costs are what xAI reports per call when it does (exact), otherwise estimated from config/cloud_prices.yaml.${live?.reserved_usd ? ` ${formatUSD(live.reserved_usd, 4)} is reserved for calls in flight.` : ''}`}
      </p>
    </div>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
  sub,
  color,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  sub?: ReactNode;
  color: string;
}) {
  return (
    <div className="min-w-0 rounded-xl border border-white/[.07] bg-white/[.02] p-3.5">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.12em] text-muted">
        <Icon className="size-3.5" style={{ color }} aria-hidden />
        <span className="truncate">{label}</span>
      </div>
      <div className="mt-1.5 truncate font-display text-xl font-semibold text-ink tabular">{value}</div>
      {sub && <div className="mt-0.5 truncate text-xs text-muted">{sub}</div>}
    </div>
  );
}

function RingGauge({ frac, color, spent, budget }: { frac: number; color: string; spent: number; budget: number }) {
  const size = 168;
  const r = 70;
  const c = 2 * Math.PI * r;
  const arc = 0.75; // 270° gauge
  const track = c * arc;
  return (
    <div className="relative mx-auto grid size-[168px] place-items-center md:mx-0" role="img" aria-label={`Grok spend ${formatUSD(spent)} of ${formatUSD(budget)}`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="absolute inset-0 rotate-[135deg]" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="10" strokeLinecap="round" strokeDasharray={`${track} ${c}`} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={`${Math.max(0.001, track * frac)} ${c}`}
          style={{ filter: `drop-shadow(0 0 8px ${withAlpha(color, 0.8)})` }}
        />
      </svg>
      <div className="relative text-center">
        <div className="font-display text-3xl font-semibold text-ink tabular">{formatUSD(spent)}</div>
        <div className="mt-0.5 text-xs text-muted">of {formatUSD(budget)} today</div>
      </div>
    </div>
  );
}

function ProviderSection({ live }: { live: Awaited<ReturnType<typeof api.budget>> | undefined }) {
  const status = !live?.key_present
    ? { text: 'no key in .env', color: '#5B6577' }
    : live.cloud_available
      ? { text: 'connected', color: '#34D399' }
      : { text: live.cloud_reason ?? 'not checked yet', color: colors.warn };
  return (
    <Section kicker="Grok (xAI)" title="Which Grok models" icon={Sparkles} color={GROK}>
      <SettingRow
        icon={KeyRound}
        color={status.color}
        title="xAI API key"
        description="Put it in .env on this Mac as HQ_XAI_API_KEY=… and restart HQ. The UI never shows it; prompts are redacted before they leave, and only api.x.ai is allowed."
        control={<Badge color={status.color}>{status.text}</Badge>}
      />
      <ModelField label="Fast model (cheap)" settingKey="xai_model" fallback="grok-4-fast" models={[]}
        description="Escalations when no local model can do a task, polish, and the eligibility third opinion. If the exact name isn't listed by xAI, the closest listed model is used." />
      <ModelField label="Strong model (sign-off)" settingKey="xai_signoff_model" fallback="grok-4" models={[]}
        description="Signs off important applications (Balanced/Quality). Should differ from the fast model, so a Grok-polished letter can still be checked independently." />
    </Section>
  );
}

function ModelField({ label, settingKey, fallback, models, description }: {
  label: string; settingKey: 'xai_model' | 'xai_signoff_model'; fallback: string; models: string[]; description: string;
}) {
  const s = useSettings();
  const { save } = useSaver();
  const current = String(s[settingKey] ?? fallback);
  const [draft, setDraft] = useState(current);
  useEffect(() => setDraft(current), [current]);
  const listId = `${settingKey}-models`;
  return (
    <SettingRow
      title={label}
      htmlFor={settingKey}
      description={description}
      control={
        <>
          <TextInput
            id={settingKey}
            mono
            list={listId}
            value={draft}
            onChange={(e) => setDraft(e.target.value.trim())}
            onBlur={() => draft && draft !== current && save({ [settingKey]: draft })}
            onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
            className="w-48"
          />
          <datalist id={listId}>
            {models.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </>
      }
    />
  );
}
