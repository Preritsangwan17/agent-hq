/**
 * The AI switches, shared by the AI usage page, Settings and Models:
 * engines   — Both (local first, cloud when it earns its place) / Local only / Cloud only / None,
 * providers — which cloud providers may be used: Claude CLI, ChatGPT (Codex CLI), Grok — each on/off,
 * mode      — API-saving (default) / Balanced / Quality: how much cloud is used when both are on.
 */
import { Bot, Cloud, Cpu, MessageSquare, PiggyBank, PowerOff, Scale, Sparkles, type LucideIcon } from 'lucide-react';
import { useState } from 'react';
import { api } from '@/lib/api';
import { cn } from '@/lib/cn';
import { useHQ, useSettings } from '@/lib/store';
import type { CloudMode, Engines, Settings } from '@/lib/types';
import { Switch } from '@/pages/Agents/formKit';
import { withAlpha } from '@/theme/tokens';

export const GROK = '#E879F9';
export const LOCAL = '#22D3EE';

const ENGINE_OPTIONS: { value: Engines; label: string; icon: LucideIcon; color: string; blurb: string }[] = [
  { value: 'both', label: 'Both', icon: Sparkles, color: '#34D399', blurb: 'Local models do the work; cloud models only when they add real value (per the mode below).' },
  { value: 'local', label: 'Local only', icon: Cpu, color: LOCAL, blurb: 'Free and private. Nothing leaves the Mac; steps no local model can do wait.' },
  { value: 'cloud', label: 'Cloud only', icon: Cloud, color: GROK, blurb: 'Every AI step goes to the cloud providers switched on below. Local models are unloaded.' },
  { value: 'none', label: 'None', icon: PowerOff, color: '#8B95A7', blurb: 'No AI at all. Rules-only steps (discovery, pay, scam and link checks) keep running; AI steps wait.' },
];

const MODE_OPTIONS: { value: CloudMode; label: string; icon: LucideIcon; blurb: string }[] = [
  { value: 'saver', label: 'API-saving', icon: PiggyBank, blurb: 'Cloud only when no local model can do the task, or for the final sign-off when no second local checker exists. Unclear cases become one-click decisions for you instead of cloud calls. No optional polish.' },
  { value: 'balanced', label: 'Balanced', icon: Scale, blurb: 'Also asks the cloud about unclear eligibility, polishes important letters, and a strong cloud model signs off important applications.' },
  { value: 'quality', label: 'Quality', icon: Sparkles, blurb: 'A strong cloud model signs off every application and polishes every high-fit letter. Uses the most.' },
];

export function anyCloud(s: Partial<Settings>): boolean {
  return s.cloud_ai_enabled !== false && (s.grok_enabled !== false || s.claude_cli_enabled === true || s.codex_cli_enabled === true);
}

export function engineOf(s: Partial<Settings>): Engines {
  const lo = s.local_ai_enabled !== false;
  const cl = anyCloud(s);
  return lo && cl ? 'both' : lo ? 'local' : cl ? 'cloud' : 'none';
}

const PROVIDER_ROWS: { key: 'claude_cli_enabled' | 'codex_cli_enabled' | 'grok_enabled'; label: string; icon: LucideIcon; color: string; how: string; blurb: string }[] = [
  { key: 'claude_cli_enabled', label: 'Claude (CLI)', icon: Bot, color: '#F59E0B', how: 'subscription', blurb: 'Your Claude plan through the claude CLI (run: claude auth login). No per-call cost; uses your plan\'s usage windows.' },
  { key: 'codex_cli_enabled', label: 'ChatGPT (Codex CLI)', icon: MessageSquare, color: '#34D399', how: 'subscription', blurb: 'Your ChatGPT plan through the codex CLI (run: codex login). No per-call cost; uses your plan\'s usage windows.' },
  { key: 'grok_enabled', label: 'Grok (API)', icon: Sparkles, color: GROK, how: 'pay per token', blurb: 'xAI API key in .env. Paid per call — HQ\'s daily limit applies.' },
];

export function ProvidersControl() {
  const s = useSettings();
  const [err, setErr] = useState<string | null>(null);
  const cloudOn = s.cloud_ai_enabled !== false;
  const set = async (patch: Partial<Settings>) => {
    const prev: Partial<Settings> = {};
    for (const k of Object.keys(patch)) prev[k] = s[k];
    useHQ.getState().mergeSettings(patch);
    setErr(null);
    try {
      const r = await api.patchSettings(patch);
      useHQ.getState().mergeSettings(r.settings);
    } catch (e) {
      useHQ.getState().mergeSettings(prev);
      setErr(e instanceof Error ? e.message : String(e));
    }
  };
  return (
    <div className={cn(!cloudOn && 'opacity-60')}>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(15.5rem,1fr))] gap-2">
        {PROVIDER_ROWS.map((p) => {
          const on = p.key === 'grok_enabled' ? s[p.key] !== false : s[p.key] === true;
          const Icon = p.icon;
          return (
            <div key={p.key} className="flex min-w-0 gap-3 rounded-xl border border-white/[.08] bg-white/[.02] p-3" style={on ? { borderColor: withAlpha(p.color, 0.45) } : undefined}>
              <Icon className="mt-0.5 size-4 shrink-0" style={{ color: p.color }} aria-hidden />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-[13.5px] font-semibold text-ink">
                  {p.label}
                  <span className="rounded-md border border-white/10 px-1.5 text-[10px] font-medium uppercase tracking-wider text-muted">{p.how}</span>
                </div>
                <p className="mt-1 text-[12px] leading-snug text-muted">{p.blurb}</p>
              </div>
              <Switch checked={on} onChange={(v) => void set({ [p.key]: v })} label={`Use ${p.label}`} color={p.color} size="sm" />
            </div>
          );
        })}
      </div>
      <label className="mt-3 flex items-center gap-2 text-[12.5px] text-muted">
        <Switch
          checked={s.prefer_subscriptions !== false}
          onChange={(v) => void set({ prefer_subscriptions: v })}
          label="Use subscriptions before Grok"
          size="sm"
          color="#34D399"
        />
        Try your already-paid subscriptions (Claude, ChatGPT) before pay-per-token Grok
      </label>
      {!cloudOn && <p className="mt-2 text-xs text-muted">Cloud is switched off above — these take effect when it is on.</p>}
      {err && <p className="mt-2 text-xs text-red-300">{err}</p>}
    </div>
  );
}

function Cards<T extends string>({ value, options, onPick, busy, label }: {
  value: T;
  options: { value: T; label: string; icon: LucideIcon; blurb: string; color?: string }[];
  onPick: (v: T) => void;
  busy?: boolean;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
      {options.map((o) => {
        const active = o.value === value;
        const color = o.color ?? GROK;
        const Icon = o.icon;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={busy}
            onClick={() => onPick(o.value)}
            className={cn(
              'min-w-0 rounded-xl border p-3 text-left transition-colors disabled:opacity-60',
              active ? 'text-ink' : 'border-white/[.08] bg-white/[.02] text-muted hover:border-white/20 hover:text-ink',
            )}
            style={active ? { borderColor: withAlpha(color, 0.5), backgroundColor: withAlpha(color, 0.1), boxShadow: `0 0 22px -10px ${color}` } : undefined}
          >
            <span className="flex items-center gap-2 text-[13.5px] font-semibold">
              <Icon className="size-4 shrink-0" style={{ color }} aria-hidden />
              {o.label}
            </span>
            <span className="mt-1 block text-[12px] leading-snug text-muted">{o.blurb}</span>
          </button>
        );
      })}
    </div>
  );
}

export function EnginesControl() {
  const s = useSettings();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const value = engineOf(s);
  const pick = async (v: Engines) => {
    if (v === value) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api.setEngines(v);
      useHQ.getState().mergeSettings(r.settings);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      <Cards label="Which AI HQ may use" value={value} options={ENGINE_OPTIONS} onPick={(v) => void pick(v)} busy={busy} />
      {err && <p className="mt-2 text-xs text-red-300">{err}</p>}
    </div>
  );
}

export function ModeControl() {
  const s = useSettings();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const value = (s.cloud_mode ?? 'saver') as CloudMode;
  const disabled = engineOf(s) !== 'both';
  const pick = async (v: CloudMode) => {
    if (v === value) return;
    setBusy(true);
    setErr(null);
    const prev = value;
    useHQ.getState().mergeSettings({ cloud_mode: v });
    try {
      const r = await api.patchSettings({ cloud_mode: v });
      useHQ.getState().mergeSettings(r.settings);
    } catch (e) {
      useHQ.getState().mergeSettings({ cloud_mode: prev });
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={cn(disabled && 'opacity-60')}>
      <Cards
        label="How much cloud to use"
        value={value}
        options={MODE_OPTIONS.map((o) => ({ ...o, color: o.value === 'saver' ? '#34D399' : GROK }))}
        onPick={(v) => void pick(v)}
        busy={busy}
      />
      {disabled && <p className="mt-2 text-xs text-muted">The mode matters when both local models and Grok are switched on.</p>}
      {err && <p className="mt-2 text-xs text-red-300">{err}</p>}
    </div>
  );
}
