/** Rules: eligibility gate, pay floor (ratio vs living cost), funded-program floor, unknown pay, fit thresholds, caps. */
import {
  CircleHelp,
  Coins,
  FilePenLine,
  Gauge,
  Mail,
  Scale,
  ShieldCheck,
  Sparkles,
  Target,
  TriangleAlert,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { ratioColor } from '@/components/PayBadge';
import { formatINR, formatRatio } from '@/lib/format';
import { useSettings } from '@/lib/store';
import type { Settings } from '@/lib/types';
import { colors, withAlpha } from '@/theme/tokens';
import { NumberField, Segmented, SettingRow, Slider } from '../controls';
import { Callout, Section } from '../parts';
import { useSaver } from '../saver';

const SLIDE_MS = 350;
const EXAMPLE_LIVING_INR = 32_000;

export function RulesTab() {
  const s = useSettings();
  const { save } = useSaver();
  const ratio = Number(s.min_pay_ratio) || 0;
  const draft = Number(s.fit_draft_threshold) || 0;
  const polish = Number(s.fit_polish_threshold) || 0;

  return (
    <div className="space-y-5">
      <Section
        kicker="Gate 1"
        title="Eligibility"
        icon={ShieldCheck}
        color="#2DD4BF"
        description="Every requirement is checked with an exact quote from the posting. Below this confidence the role goes to Needs Prerit as a decision instead of being drafted."
      >
        <SettingRow
          title="Eligibility confidence threshold"
          phase="c"
          control={<Value>{Math.round((Number(s.eligibility_threshold) || 0) * 100)}%</Value>}
        >
          <Slider
            aria-label="Eligibility confidence threshold"
            value={Number(s.eligibility_threshold) || 0}
            min={0.5}
            max={1}
            step={0.05}
            color="#2DD4BF"
            format={(v) => `${Math.round(v * 100)}%`}
            onChange={(v) => save({ eligibility_threshold: round(v, 2) }, SLIDE_MS)}
            marks={[
              { value: 0.5, label: '50%' },
              { value: 0.7, label: '70%' },
              { value: 0.8, label: '80% default' },
              { value: 1, label: '100%' },
            ]}
          />
        </SettingRow>
      </Section>

      <Section
        kicker="Gate 2"
        title="Pay floor"
        icon={Coins}
        color={colors.gold}
        description="Pay is normalised to ₹/month and divided by the city's living cost. Roles below the floor are filtered, never applied to."
      >
        <SettingRow
          title="Minimum pay ÷ living cost"
          phase="live"
          control={<Value color={ratioColor(ratio)}>{formatRatio(ratio)}</Value>}
        >
          <Slider
            aria-label="Minimum pay to living cost ratio"
            value={ratio}
            min={0}
            max={3}
            step={0.1}
            color={ratioColor(ratio)}
            format={formatRatio}
            onChange={(v) => save({ min_pay_ratio: round(v, 2) }, SLIDE_MS)}
            bands={[
              { from: 0, to: 1, color: colors.ratioLow },
              { from: 1, to: 1.5, color: colors.ratioOk },
              { from: 1.5, to: 3, color: colors.ratioGood },
            ]}
            marks={[
              { value: 0, label: '0×' },
              { value: 1, label: '1× covers costs' },
              { value: 1.5, label: '1.5×' },
              { value: 3, label: '3×' },
            ]}
          />
          <div className="mt-3 flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[13px] text-muted">
            <span>Example: a city costing</span>
            <span className="font-display font-semibold text-money tabular">{formatINR(EXAMPLE_LIVING_INR)}/mo</span>
            <span>to live in needs at least</span>
            <span className="font-display text-[15px] font-semibold text-money tabular">{formatINR(Math.round(EXAMPLE_LIVING_INR * ratio))}/mo</span>
          </div>
          {ratio < 1 && (
            <div className="mt-2 flex items-center gap-1.5 text-xs text-amber-200/90">
              <TriangleAlert className="size-3.5" aria-hidden /> Below 1× lets through roles that don't cover living costs.
            </div>
          )}
        </SettingRow>

        <SettingRow
          icon={Sparkles}
          color={colors.gold}
          title="Funded-program allowance floor"
          phase="live"
          htmlFor="funded-min"
          description="Programs that cover stay and food qualify when the extra allowance is at least this much per month."
          control={
            <NumberField
              id="funded-min"
              aria-label="Funded program minimum allowance in rupees per month"
              value={Number(s.funded_program_min_inr) || 0}
              onChange={(v) => save({ funded_program_min_inr: v })}
              min={0}
              max={1_000_000}
              step={500}
              integer
              money
              prefix="₹"
              suffix="/mo"
              display={(v) => formatINR(v, { symbol: false })}
              className="w-44"
            />
          }
        />

        <SettingRow
          icon={CircleHelp}
          color="#8B95A7"
          title="When pay isn't listed"
          phase="live"
          description="Unknown pay can't be compared to living cost. Ask me creates a 30-second decision in Needs Prerit."
          control={
            <Segmented<Settings['unknown_pay_policy']>
              aria-label="Unknown pay policy"
              value={s.unknown_pay_policy}
              onChange={(v) => save({ unknown_pay_policy: v })}
              color="#FB923C"
              options={[
                { value: 'decision', label: 'Ask me' },
                { value: 'accept', label: 'Keep' },
                { value: 'reject', label: 'Drop' },
              ]}
            />
          }
        />
      </Section>

      <Section
        kicker="Fit"
        title="Drafting thresholds"
        icon={Target}
        color="#A78BFA"
        description="The Verifier scores fit 0–100. Below the draft line a role is parked; at or above the polish line the draft also gets a budgeted Claude polish."
      >
        <FitBar draft={draft} polish={polish} />
        <SettingRow icon={FilePenLine} color="#A78BFA" title="Draft at fit ≥" phase="live" control={<Value>{draft}</Value>}>
          <Slider
            aria-label="Fit threshold for drafting"
            value={draft}
            min={0}
            max={100}
            step={1}
            color="#A78BFA"
            pins={[{ value: polish, color: '#E879F9', label: 'Polish threshold' }]}
            onChange={(v) => save({ fit_draft_threshold: Math.round(v) }, SLIDE_MS)}
          />
        </SettingRow>
        <SettingRow icon={Sparkles} color="#E879F9" title="Claude polish at fit ≥" phase="b" control={<Value>{polish}</Value>}>
          <Slider
            aria-label="Fit threshold for Claude polish"
            value={polish}
            min={0}
            max={100}
            step={1}
            color="#E879F9"
            pins={[{ value: draft, color: '#A78BFA', label: 'Draft threshold' }]}
            onChange={(v) => save({ fit_polish_threshold: Math.round(v) }, SLIDE_MS)}
          />
          {polish < draft && (
            <div className="mt-2 flex items-center gap-1.5 text-xs text-amber-200/90">
              <TriangleAlert className="size-3.5" aria-hidden /> Polish is below the draft line, so every drafted role would be polished.
            </div>
          )}
        </SettingRow>
      </Section>

      <Section kicker="Throttle" title="Daily caps" icon={Gauge} color="#60A5FA" description="Hard ceilings per IST day. When a cap is hit the work waits for midnight; nothing is dropped.">
        <SettingRow
          icon={FilePenLine}
          color="#A78BFA"
          title="Drafts per day"
          phase="live"
          htmlFor="draft-cap"
          description="Cover letters and form answers started by the Writer."
          control={
            <NumberField
              id="draft-cap"
              aria-label="Drafts per day"
              value={Number(s.daily_draft_cap) || 0}
              onChange={(v) => save({ daily_draft_cap: v })}
              min={0}
              max={500}
              step={1}
              integer
              stepper
              className="w-36"
            />
          }
        />
        <SettingRow
          icon={Mail}
          color="#F472B6"
          title="Application emails per day"
          phase="d"
          htmlFor="email-cap"
          description="Outbound applications from the Applicant once sending is real. In dry run they only reach the mock mailbox."
          control={
            <NumberField
              id="email-cap"
              aria-label="Application emails per day"
              value={Number(s.email_daily_cap) || 0}
              onChange={(v) => save({ email_daily_cap: v })}
              min={0}
              max={100}
              step={1}
              integer
              stepper
              className="w-36"
            />
          }
        />
      </Section>

      <Callout icon={Scale} color="#2DD4BF" title="Always-on filters">
        Scam checks (fees, known mills, lookalike domains) and hard ineligibility are not configurable — they always filter.
      </Callout>
    </div>
  );
}

function round(v: number, digits: number): number {
  const f = 10 ** digits;
  return Math.round(v * f) / f;
}

function Value({ children, color }: { children: ReactNode; color?: string }) {
  return (
    <span className="min-w-[3.5rem] text-right font-display text-xl font-semibold tabular" style={{ color: color ?? colors.ink }}>
      {children}
    </span>
  );
}

/** 0–100 strip showing the three fit zones. */
function FitBar({ draft, polish }: { draft: number; polish: number }) {
  const d = Math.max(0, Math.min(100, draft));
  const p = Math.max(d, Math.min(100, polish));
  const zones = [
    { from: 0, to: d, label: 'Parked', color: '#526077' },
    { from: d, to: p, label: 'Draft', color: '#A78BFA' },
    { from: p, to: 100, label: 'Draft + polish', color: '#E879F9' },
  ].filter((z) => z.to - z.from > 0);
  return (
    <div className="pb-2">
      <div className="flex h-9 overflow-hidden rounded-xl border border-white/10">
        {zones.map((z) => (
          <div
            key={z.label}
            className="flex min-w-0 items-center justify-center overflow-hidden px-1 text-[11px] font-medium whitespace-nowrap"
            style={{ flexGrow: z.to - z.from, flexBasis: 0, backgroundColor: withAlpha(z.color, 0.16), color: z.color, borderRight: '1px solid rgba(255,255,255,0.06)' }}
          >
            <span className="truncate">{z.to - z.from >= 12 ? z.label : ''}</span>
          </div>
        ))}
      </div>
      <div className="mt-1 flex justify-between font-mono text-[10px] text-faint tabular">
        <span>0</span>
        <span>100</span>
      </div>
    </div>
  );
}
