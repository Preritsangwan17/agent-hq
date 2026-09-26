/**
 * The two AI switches, shared by the AI & Grok page, Settings and Models:
 * engines — Both (local first, Grok when it earns its cost) / Local only / Grok only / None,
 * mode    — API-saving (default) / Balanced / Quality: how much Grok is used when both are on.
 */
import { Cloud, Cpu, PiggyBank, PowerOff, Scale, Sparkles, type LucideIcon } from 'lucide-react';
import { useState } from 'react';
import { api } from '@/lib/api';
import { cn } from '@/lib/cn';
import { useHQ, useSettings } from '@/lib/store';
import type { CloudMode, Engines } from '@/lib/types';
import { withAlpha } from '@/theme/tokens';

export const GROK = '#E879F9';
export const LOCAL = '#22D3EE';

const ENGINE_OPTIONS: { value: Engines; label: string; icon: LucideIcon; color: string; blurb: string }[] = [
  { value: 'both', label: 'Both', icon: Sparkles, color: '#34D399', blurb: 'Local models do the work; Grok only when it adds real value (per the mode below).' },
  { value: 'local', label: 'Local only', icon: Cpu, color: LOCAL, blurb: 'Free and private. Nothing is sent to Grok; steps no local model can do wait.' },
  { value: 'grok', label: 'Grok only', icon: Cloud, color: GROK, blurb: 'Every AI step goes to Grok (paid). Local models are unloaded.' },
  { value: 'none', label: 'None', icon: PowerOff, color: '#8B95A7', blurb: 'No AI at all. Rules-only steps (discovery, pay, scam and link checks) keep running; AI steps wait.' },
];

const MODE_OPTIONS: { value: CloudMode; label: string; icon: LucideIcon; blurb: string }[] = [
  { value: 'saver', label: 'API-saving', icon: PiggyBank, blurb: 'Grok only when no local model can do the task, or for the final sign-off when no second local checker exists. Unclear cases become one-click decisions for you instead of paid calls. No optional polish.' },
  { value: 'balanced', label: 'Balanced', icon: Scale, blurb: 'Also uses Grok for unclear eligibility, polishes important letters, and the strong Grok model signs off important applications.' },
  { value: 'quality', label: 'Quality', icon: Sparkles, blurb: 'The strong Grok model signs off every application and polishes every high-fit letter. Costs the most.' },
];

export function engineOf(s: { local_ai_enabled?: boolean; grok_enabled?: boolean }): Engines {
  const lo = s.local_ai_enabled !== false;
  const gr = s.grok_enabled !== false;
  return lo && gr ? 'both' : lo ? 'local' : gr ? 'grok' : 'none';
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
        label="How much Grok to use"
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
