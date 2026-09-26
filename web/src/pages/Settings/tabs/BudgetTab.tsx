/** Budget: Claude $/day and call cap with a live gauge (spend today vs the budget being edited). */
import { CalendarClock, Cpu, DollarSign, Hash, HandHelping, Moon, Sparkles, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { GlassPanel } from '@/components/GlassPanel';
import { ProgressBar } from '@/components/ProgressBar';
import { SectionHeader } from '@/components/SectionHeader';
import { formatCompact, formatUSD } from '@/lib/format';
import { useSettings, useStats } from '@/lib/store';
import { colors, withAlpha } from '@/theme/tokens';
import { NumberField, SettingRow, Slider } from '../controls';
import { Callout, Section } from '../parts';
import { useSaver } from '../saver';

const CLAUDE = '#E879F9';

export function BudgetTab() {
  const s = useSettings();
  const stats = useStats();
  const { save } = useSaver();
  const budget = Number(s.claude_daily_budget_usd) || 0;
  const cap = Number(s.claude_daily_call_cap) || 0;
  const spent = stats?.claude_cost_today_usd ?? 0;
  const calls = stats?.claude_calls_today ?? 0;
  const frac = budget > 0 ? Math.min(1, spent / budget) : spent > 0 ? 1 : 0;
  const callFrac = cap > 0 ? Math.min(1, calls / cap) : 0;
  const hot = frac >= 0.85 || callFrac >= 0.85;

  return (
    <div className="space-y-5">
      <GlassPanel padding="lg" glow={CLAUDE} accentTop>
        <SectionHeader kicker="Today · resets at midnight IST" title="Claude spend" icon={Sparkles} color={CLAUDE} />
        <div className="mt-5 grid items-center gap-6 md:grid-cols-[auto_minmax(0,1fr)]">
          <RingGauge frac={frac} color={hot ? colors.warn : CLAUDE} spent={spent} budget={budget} />
          <div className="grid min-w-0 gap-4 sm:grid-cols-2">
            <Metric icon={DollarSign} label="Spent / budget" value={`${formatUSD(spent)} / ${formatUSD(budget)}`} sub={`${Math.round(frac * 100)}% of today's budget`} color={CLAUDE} />
            <Metric
              icon={Hash}
              label="Claude calls"
              value={`${calls} / ${cap}`}
              sub={<ProgressBar value={callFrac} color={callFrac >= 0.85 ? colors.warn : CLAUDE} height={4} className="mt-1.5" />}
              color={CLAUDE}
            />
            <Metric
              icon={Cpu}
              label="Local tokens today"
              value={formatCompact(stats?.local_tokens_today ?? 0)}
              sub="On-device models · no spend"
              color="#22D3EE"
            />
            <Metric icon={CalendarClock} label="When over budget" value="Defer" sub="Claude tasks wait for midnight IST" color={colors.warn} />
          </div>
        </div>
      </GlassPanel>

      <Section kicker="Limits" title="Daily Claude budget" icon={DollarSign} color={CLAUDE}>
        <SettingRow
          title="Budget per day"
          phase="b"
          htmlFor="claude-budget"
          description="Notional spend reported by Claude Code per call (subscription auth). Sign-off, polish and the Strategist draw from it."
          control={
            <NumberField
              id="claude-budget"
              aria-label="Claude budget in US dollars per day"
              value={budget}
              onChange={(v) => save({ claude_daily_budget_usd: v })}
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
            aria-label="Claude budget per day"
            value={Math.min(budget, 25)}
            min={0}
            max={25}
            step={0.5}
            color={CLAUDE}
            format={(v) => formatUSD(v)}
            onChange={(v) => save({ claude_daily_budget_usd: v }, 350)}
            pins={spent > 0 ? [{ value: Math.min(spent, 25), color: colors.warn, label: 'Spent today' }] : undefined}
            marks={[
              { value: 0, label: '$0' },
              { value: 5, label: '$5 default' },
              { value: 10, label: '$10' },
              { value: 25, label: '$25' },
            ]}
          />
        </SettingRow>
        <SettingRow
          icon={Hash}
          color={CLAUDE}
          title="Calls per day"
          phase="b"
          htmlFor="claude-calls"
          description="A second ceiling in case per-call cost reporting is unavailable."
          control={
            <NumberField
              id="claude-calls"
              aria-label="Claude calls per day"
              value={cap}
              onChange={(v) => save({ claude_daily_call_cap: v })}
              min={0}
              max={10_000}
              step={5}
              integer
              stepper
              className="w-36"
            />
          }
        />
      </Section>

      <div className="grid gap-3 md:grid-cols-2">
        <Callout icon={Moon} color="#818CF8" title="Over budget">
          Claude tasks are deferred to midnight IST; local models keep working and nothing is skipped.
        </Callout>
        <Callout icon={HandHelping} color="#FB923C" title="Deadlines still win">
          Anything due within 48 h that is blocked on the budget becomes a Needs Prerit item instead of waiting.
        </Callout>
      </div>
      <p className="px-1 text-xs text-faint">
        Phase (a): Claude work is simulated, so today's spend stays at $0. Real calls arrive with the claude_code adapter in phase (b).
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
    <div className="relative mx-auto grid size-[168px] place-items-center md:mx-0" role="img" aria-label={`Claude spend ${formatUSD(spent)} of ${formatUSD(budget)}`}>
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
