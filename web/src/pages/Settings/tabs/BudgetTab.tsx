/** Models & Budget: an on/off switch per model source (local, Claude CLI, xAI, ChatGPT via the Codex CLI) and the
 * preferred cloud provider; cloud $/day and call cap with a live gauge (spend today vs the budget being edited); which
 * models each provider uses. */
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, BadgeCheck, Bot, CalendarClock, Cloud, Cpu, DollarSign, Hash, HandHelping, KeyRound, Moon, Power, Sparkles, Wand2, Zap, type LucideIcon } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Badge } from '@/components/Badge';
import { TextInput } from '@/pages/Agents/formKit';
import type { ReactNode } from 'react';
import { GlassPanel } from '@/components/GlassPanel';
import { ProgressBar } from '@/components/ProgressBar';
import { SectionHeader } from '@/components/SectionHeader';
import { api } from '@/lib/api';
import { formatCompact, formatDateTimeIST, formatUSD } from '@/lib/format';
import type { CloudProvider, ProviderState } from '@/lib/types';
import { useSettings, useStats } from '@/lib/store';
import { colors, withAlpha } from '@/theme/tokens';
import { NumberField, Segmented, SettingRow, Slider, Toggle } from '../controls';
import { Callout, Code, Section } from '../parts';
import { useSaver } from '../saver';

const CLAUDE = '#E879F9';
const CHATGPT = '#10A37F';
const LABEL: Record<CloudProvider, string> = { claude: 'Claude', xai: 'xAI', codex: 'ChatGPT' };

export function BudgetTab() {
  const s = useSettings();
  const stats = useStats();
  const live = useQuery({ queryKey: ['budget'], queryFn: api.budget, refetchInterval: 15_000 }).data;
  const { save } = useSaver();
  const budget = Number(s.claude_daily_budget_usd) || 0;
  const cap = Number(s.claude_daily_call_cap) || 0;
  const spent = live?.spent_usd ?? stats?.claude_cost_today_usd ?? 0;
  const calls = live?.calls ?? stats?.claude_calls_today ?? 0;
  const frac = budget > 0 ? Math.min(1, spent / budget) : spent > 0 ? 1 : 0;
  const callFrac = cap > 0 ? Math.min(1, calls / cap) : 0;
  const hot = frac >= 0.85 || callFrac >= 0.85;

  return (
    <div className="space-y-5">
      <SourcesSection live={live} />

      <GlassPanel padding="lg" glow={CLAUDE} accentTop>
        <SectionHeader
          kicker="Today · resets at midnight IST"
          title={`Cloud spend · ${live?.using ? LABEL[live.using] : live?.provider ? LABEL[live.provider] : 'all off'}`}
          icon={Sparkles}
          color={CLAUDE}
        />
        <div className="mt-5 grid items-center gap-6 md:grid-cols-[auto_minmax(0,1fr)]">
          <RingGauge frac={frac} color={hot ? colors.warn : CLAUDE} spent={spent} budget={budget} />
          <div className="grid min-w-0 gap-4 sm:grid-cols-2">
            <Metric icon={DollarSign} label="Spent / budget" value={`${formatUSD(spent)} / ${formatUSD(budget)}`} sub={`${Math.round(frac * 100)}% of today's budget`} color={CLAUDE} />
            <Metric
              icon={Hash}
              label="Cloud calls"
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
            <Metric
              icon={CalendarClock}
              label="Waiting on budget"
              value={`${live?.deferred_tasks ?? 0} task${live?.deferred_tasks === 1 ? '' : 's'}`}
              sub={live?.resets_at ? `resets ${formatDateTimeIST(live.resets_at)} IST` : 'Claude tasks wait for midnight IST'}
              color={colors.warn}
            />
          </div>
        </div>
      </GlassPanel>

      <Section kicker="Limits" title="Daily Claude budget" icon={DollarSign} color={CLAUDE}>
        <SettingRow
          title="Budget per day"
          phase="live"
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
          phase="live"
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

      <Section kicker="Models" title="Which Claude, and when" icon={Wand2} color={CLAUDE}>
        <SettingRow
          title="Escalation & polish model"
          description="Used when two local models fail a task, for Claude polish of high-fit drafts and the Strategist."
          control={
            <Segmented
              aria-label="Claude model"
              value={String(s.claude_model ?? 'sonnet')}
              onChange={(v) => save({ claude_model: v })}
              color={CLAUDE}
              options={[
                { value: 'haiku', label: 'Haiku' },
                { value: 'sonnet', label: 'Sonnet' },
                { value: 'opus', label: 'Opus' },
              ]}
            />
          }
        />
        <SettingRow
          icon={BadgeCheck}
          color={CLAUDE}
          title="Sign-off model"
          description="The final independent check on every outbound text. It must differ from any Claude model that wrote or polished the text."
          control={
            <Segmented
              aria-label="Claude sign-off model"
              value={String(s.claude_signoff_model ?? 'opus')}
              onChange={(v) => save({ claude_signoff_model: v })}
              color={CLAUDE}
              options={[
                { value: 'haiku', label: 'Haiku' },
                { value: 'sonnet', label: 'Sonnet' },
                { value: 'opus', label: 'Opus' },
              ]}
            />
          }
        />
        <SettingRow
          title="Require cloud sign-off"
          htmlFor="signoff"
          description="Nothing is submitted without a cloud sign-off (Claude, xAI or ChatGPT, whichever is on and didn't write the text). Turning this off leaves the deterministic rules and the local checker."
          control={<Toggle id="signoff" label="Require cloud sign-off" checked={s.require_claude_signoff !== false} onChange={(v) => save({ require_claude_signoff: v })} color={CLAUDE} size="lg" />}
        />
        <SettingRow
          title="Cap per call"
          htmlFor="per-call"
          description="Passed to Claude Code as --max-budget-usd on every call."
          control={
            <NumberField
              id="per-call"
              aria-label="Claude per-call cap in US dollars"
              value={Number(s.claude_per_call_cap_usd ?? 0.5)}
              onChange={(v) => save({ claude_per_call_cap_usd: v })}
              min={0.01}
              max={5}
              step={0.05}
              prefix="$"
              display={(v) => v.toFixed(2)}
              className="w-32"
            />
          }
        />
      </Section>

      <ProviderDetails live={live} />

      <div className="grid gap-3 md:grid-cols-2">
        <Callout icon={Moon} color="#818CF8" title="Over budget">
          Claude tasks are deferred to midnight IST; local models keep working and nothing is skipped.
        </Callout>
        <Callout icon={HandHelping} color="#FB923C" title="Deadlines still win">
          Anything due within 48 h that is blocked on the budget becomes a Needs Prerit item instead of waiting.
        </Callout>
      </div>
      {live && Object.keys(live.by_task).length > 0 && (
        <Section kicker="Today" title="Spend by task" icon={Sparkles} color={CLAUDE} rows={false}>
          <ul className="divide-y divide-white/[.06] text-[13px]">
            {Object.entries(live.by_task).map(([task, v]) => (
              <li key={task} className="flex items-center justify-between py-2">
                <span className="font-mono text-ink/85">{task}</span>
                <span className="text-muted tabular">
                  {v.calls} call{v.calls === 1 ? '' : 's'} · {formatUSD(v.spent_usd)}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}
      <p className="px-1 text-xs text-faint">
        {live?.claude_available === false
          ? 'Claude is not logged in, so nothing is being spent; see Models or Needs Prerit to log in.'
          : `Costs are Claude Code's own estimates under subscription auth (notional spend).${live?.reserved_usd ? ` ${formatUSD(live.reserved_usd)} is reserved for calls in flight.` : ''}`}
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

type Live = Awaited<ReturnType<typeof api.budget>> | undefined;
type Status = { text: string; color: string };

const OFF: Status = { text: 'off', color: '#5B6577' };
const SOURCES = [
  { key: 'llm_local_enabled', id: 'local', title: 'Local models', icon: Cpu, color: '#22D3EE',
    description: 'Ollama, LM Studio and MLX models on this Mac. Free. Off: nothing is loaded and running ones are unloaded. Steps that only use local models (title filter, parsing, local fact check) then use their built-in rules; they never move to the cloud.' },
  { key: 'llm_claude_enabled', id: 'claude', title: 'Claude CLI', icon: Sparkles, color: CLAUDE,
    description: 'Claude Code on this Mac (claude auth login in Terminal). Runs with no tools and a per-call cap.' },
  { key: 'llm_xai_enabled', id: 'xai', title: 'xAI · Grok', icon: Zap, color: '#A5B4FC',
    description: 'Grok via the API key in .env (HQ_XAI_API_KEY). Only api.x.ai is reachable, prompts are redacted.' },
  { key: 'llm_codex_enabled', id: 'codex', title: 'ChatGPT · Codex CLI', icon: Bot, color: CHATGPT,
    description: 'The Codex CLI signed in with your ChatGPT account (codex login in Terminal). Read-only sandbox, shell and browser tools off, no session files.' },
] as const;

function providerStatus(id: CloudProvider, p: ProviderState | null | undefined): Status {
  if (!p || !p.checked) return { text: 'not checked yet', color: '#8B95A7' };
  if (p.resting) return { text: 'resting (usage limit)', color: colors.warn };
  if (p.available) return { text: id === 'xai' ? 'connected' : 'logged in', color: '#34D399' };
  if (id === 'xai' && !p.key_present) return { text: 'no key in .env', color: colors.warn };
  if (id === 'codex' && p.installed === false) return { text: 'not installed', color: colors.warn };
  return { text: id === 'xai' ? 'unavailable' : 'not logged in', color: colors.warn };
}

/** The on/off switch per model source, the preferred cloud provider and what HQ is using right now. */
function SourcesSection({ live }: { live: Live }) {
  const s = useSettings();
  const { save } = useSaver();
  const on = (key: string) => s[key] !== false;
  const cloudOn = (['claude', 'xai', 'codex'] as const).filter((id) => on(`llm_${id}_enabled`));
  const pref = String(s.cloud_llm ?? 'auto');
  const using = live?.using;
  const signoff = s.require_claude_signoff !== false;
  return (
    <Section kicker="Sources" title="Models on/off" icon={Power} color={CLAUDE}>
      {SOURCES.map((src) => {
        const enabled = on(src.key);
        const st = !enabled ? OFF : src.id === 'local' ? { text: 'on', color: '#34D399' } : providerStatus(src.id, live?.[src.id]);
        const reason = enabled && src.id !== 'local' && st.text !== 'no key in .env' ? live?.[src.id]?.reason : null;
        return (
          <SettingRow
            key={src.key}
            icon={src.icon}
            color={enabled ? src.color : '#5B6577'}
            title={src.title}
            htmlFor={src.key}
            description={
              <>
                {src.description}
                {reason && st.color !== '#34D399' && <span className="mt-1 block text-xs text-amber-200/80">{reason}</span>}
              </>
            }
            control={
              <div className="flex items-center gap-3">
                <Badge color={st.color}>{st.text}</Badge>
                <Toggle id={src.key} label={`Use ${src.title}`} checked={enabled} onChange={(v) => save({ [src.key]: v })} color={src.color} />
              </div>
            }
          />
        );
      })}
      <SettingRow
        icon={Cloud}
        color={CLAUDE}
        title="Preferred cloud"
        description="Tried first for escalations, polish, sign-off and the Strategist. If it can't be reached (not logged in, no key, or resting after hitting its usage limit) the next switched-on one is used. Auto: xAI when its key is in .env, else Claude, then ChatGPT. Status checks are free: they never call a model."
        control={
          <Segmented
            aria-label="Preferred cloud provider"
            value={pref}
            onChange={(v) => save({ cloud_llm: v })}
            color={CLAUDE}
            size="sm"
            options={[
              { value: 'auto', label: 'Auto' },
              { value: 'claude', label: 'Claude', disabled: !on('llm_claude_enabled') },
              { value: 'xai', label: 'xAI', disabled: !on('llm_xai_enabled') },
              { value: 'codex', label: 'ChatGPT', disabled: !on('llm_codex_enabled') },
            ]}
          />
        }
      >
        <p className="text-xs text-muted">
          {cloudOn.length === 0
            ? 'No cloud model is on.'
            : using
              ? `Using ${LABEL[using]} right now${live?.provider && live.provider !== using ? ` (${LABEL[live.provider]} can't be reached)` : ''}.`
              : 'None of the switched-on cloud models can be reached yet. Tasks that need one wait; nothing is spent.'}
        </p>
      </SettingRow>
      {cloudOn.length === 0 && (
        <Callout icon={AlertTriangle} color={colors.warn} title="Every cloud model is off">
          {signoff
            ? 'Letters wait at sign-off until you switch one on, or turn off Require sign-off below (then only the rules and the local checker decide).'
            : 'Sign-off is off, so letters are decided by the rules and the local checker only.'}
          {!on('llm_local_enabled') && ' Local models are off too, so nothing can be drafted.'}
        </Callout>
      )}
      <p className="pt-3 text-xs text-faint">
        Limits are never spent twice: a provider that reports a usage or rate limit gets no calls for an hour while the others carry on,
        and every cloud call counts against the daily budget and call cap below.
      </p>
    </Section>
  );
}

function ProviderDetails({ live }: { live: Live }) {
  const s = useSettings();
  const xaiOn = s.llm_xai_enabled !== false;
  const codexOn = s.llm_codex_enabled !== false;
  if (!xaiOn && !codexOn) return null;
  const xai = live?.xai;
  const models = xai?.models ?? [];
  const status = !xai?.key_present
    ? { text: 'no key in .env', color: '#5B6577' }
    : xai.available
      ? { text: 'connected', color: '#34D399' }
      : { text: xai.reason ?? (xai.checked ? 'unavailable' : 'not checked yet'), color: colors.warn };
  const codex = live?.codex;
  return (
    <Section kicker="Providers" title="xAI and ChatGPT models" icon={Cloud} color={CLAUDE}>
      {xaiOn && (
        <>
          <SettingRow
            icon={KeyRound}
            color={status.color}
            title="xAI API key"
            description="Put it in .env on this Mac as HQ_XAI_API_KEY=… and restart HQ. The UI never shows it; prompts are redacted before they leave, and only api.x.ai is allowed."
            control={<Badge color={status.color}>{status.text}</Badge>}
          />
          <ModelField label="xAI model" settingKey="xai_model" fallback="grok-4-fast" models={models}
            description="Escalations and polish. If the exact name isn't listed by xAI, the closest listed model is used." />
          <ModelField label="xAI sign-off model" settingKey="xai_signoff_model" fallback="grok-4" models={models}
            description="Should differ from the model above, so a polished letter can still be checked independently." />
        </>
      )}
      {codexOn && (
        <>
          <SettingRow
            icon={Bot}
            color={CHATGPT}
            title="ChatGPT sign-in"
            description={
              <>
                In Terminal on this Mac: <Code>npm install -g @openai/codex</Code> (once), then <Code>codex login</Code> and sign in with ChatGPT.
                Calls use your ChatGPT plan's Codex allowance; spend here is an estimate from token counts.
                {codex?.version ? ` Codex ${codex.version}.` : ''}
              </>
            }
            control={<Badge color={providerStatus('codex', codex).color}>{providerStatus('codex', codex).text}</Badge>}
          />
          <ModelField label="ChatGPT model" settingKey="codex_model" fallback="default" models={[]}
            description="“default” uses Codex's own default model. Any model name your plan offers in Codex works." />
          <ModelField label="ChatGPT sign-off model" settingKey="codex_signoff_model" fallback="default" models={[]}
            description="A letter ChatGPT polished can only be signed off by a different model: set another name here, or another provider signs it off." />
        </>
      )}
    </Section>
  );
}

function ModelField({ label, settingKey, fallback, models, description }: {
  label: string; settingKey: 'xai_model' | 'xai_signoff_model' | 'codex_model' | 'codex_signoff_model'; fallback: string; models: string[]; description: string;
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
