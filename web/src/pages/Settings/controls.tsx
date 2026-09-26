/**
 * Controls for the Settings tabs: a labelled setting row, toggle, number field, slider with colour bands and pins,
 * segmented control and the save indicator. The primitives (switch, stepper, segmented) come from the Agents form
 * kit; this module adapts them to the Settings API (`aria-label` names, optional visible labels).
 */
import { AlertCircle, Check, LoaderCircle, type LucideIcon } from 'lucide-react';
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react';
import { Badge } from '@/components/Badge';
import { cn } from '@/lib/cn';
import { formatClockIST } from '@/lib/format';
import { withAlpha } from '@/theme/tokens';
import {
  Segmented as KitSegmented,
  Stepper,
  Switch,
  type SegOption,
} from '@/pages/Agents/formKit';

export type { SegOption };

// ── save indicator ────────────────────────────────────────────────────

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

export function SaveIndicator({ status, at, error }: { status: SaveStatus; at: number | null; error: string | null }) {
  if (status === 'idle') {
    return <span className="text-xs text-faint">Changes save automatically</span>;
  }
  if (status === 'saving') {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-muted" role="status">
        <LoaderCircle className="size-3.5 animate-spin" aria-hidden /> Saving…
      </span>
    );
  }
  if (status === 'error') {
    return (
      <span className="inline-flex max-w-[22rem] items-center gap-1.5 text-xs text-red-300" role="alert" title={error ?? undefined}>
        <AlertCircle className="size-3.5 shrink-0" aria-hidden />
        <span className="truncate">Not saved{error ? ` — ${error}` : ''}</span>
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-emerald-300" role="status">
      <Check className="size-3.5" aria-hidden /> Saved{at ? ` ${formatClockIST(new Date(at).toISOString(), false)}` : ''}
    </span>
  );
}

// ── setting row ───────────────────────────────────────────────────────

/** When a setting starts to matter: `live` = now; a phase letter = once that phase ships. */
export type SettingPhase = 'live' | 'a' | 'b' | 'c' | 'd' | 'e';

const PHASE_BADGE: Record<Exclude<SettingPhase, 'live'>, string> = {
  a: 'Used from phase (a)',
  b: 'Used from phase (b)',
  c: 'Used from phase (c)',
  d: 'Used from phase (d)',
  e: 'Used from phase (e)',
};

export interface SettingRowProps {
  title: ReactNode;
  description?: ReactNode;
  icon?: LucideIcon;
  color?: string;
  phase?: SettingPhase;
  /** id of the control, so the title acts as its label */
  htmlFor?: string;
  /** the control shown to the right of the title (toggle, number field, value) */
  control?: ReactNode;
  /** full-width content under the title (sliders, notes) */
  children?: ReactNode;
  className?: string;
}

export function SettingRow({ title, description, icon: Icon, color = '#8B95A7', phase, htmlFor, control, children, className }: SettingRowProps) {
  const Title = htmlFor ? 'label' : 'div';
  return (
    <div className={cn('py-4 first:pt-0 last:pb-0', className)}>
      <div className="flex items-start gap-3">
        {Icon && (
          <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/[.03]">
            <Icon className="size-4" style={{ color }} aria-hidden />
          </span>
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Title {...(htmlFor ? { htmlFor } : {})} className="text-[14px] font-medium text-ink">
              {title}
            </Title>
            {phase && phase !== 'live' && (
              <Badge color="#5B6577" size="xs">
                {PHASE_BADGE[phase]}
              </Badge>
            )}
          </div>
          {description && <p className="mt-1 max-w-xl text-[12.5px] leading-relaxed text-muted">{description}</p>}
        </div>
        {control && <div className="shrink-0 self-center">{control}</div>}
      </div>
      {children && <div className={cn('mt-3', Icon && 'md:pl-11')}>{children}</div>}
    </div>
  );
}

// ── toggle ────────────────────────────────────────────────────────────

export interface ToggleProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  id?: string;
  /** accessible name; defaults to the row title via `htmlFor` */
  label?: string;
  color?: string;
  size?: 'sm' | 'md' | 'lg';
  disabled?: boolean;
}

export function Toggle({ checked, onChange, id, label, color, size = 'md', disabled }: ToggleProps) {
  return <Switch id={id} checked={checked} onChange={onChange} label={label ?? ''} color={color} size={size} disabled={disabled} />;
}

// ── segmented ─────────────────────────────────────────────────────────

export interface SegmentedProps<T extends string | number> {
  value: T;
  options: readonly SegOption<T>[];
  onChange: (v: T) => void;
  'aria-label'?: string;
  label?: string;
  color?: string;
  size?: 'sm' | 'md';
  full?: boolean;
  className?: string;
}

export function Segmented<T extends string | number>({ 'aria-label': ariaLabel, label, ...rest }: SegmentedProps<T>) {
  return <KitSegmented<T> {...rest} label={ariaLabel ?? label ?? ''} />;
}

// ── number field ──────────────────────────────────────────────────────

export interface NumberFieldProps {
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step?: number;
  id?: string;
  'aria-label': string;
  integer?: boolean;
  /** gold styling (₹ amounts) */
  money?: boolean;
  prefix?: ReactNode;
  suffix?: ReactNode;
  /** formatter for the resting (unfocused) value */
  display?: (v: number) => string;
  /** show −/+ buttons */
  stepper?: boolean;
  color?: string;
  disabled?: boolean;
  className?: string;
}

export function NumberField({
  value,
  onChange,
  min,
  max,
  step = 1,
  id,
  'aria-label': ariaLabel,
  integer,
  money,
  prefix,
  suffix,
  display,
  stepper,
  color = '#22D3EE',
  disabled,
  className,
}: NumberFieldProps) {
  const clamp = useCallback(
    (v: number) => {
      const c = Math.max(min, Math.min(max, v));
      return integer ? Math.round(c) : Math.round(c * 100) / 100;
    },
    [min, max, integer],
  );
  if (stepper) {
    return (
      <div className={className}>
        <Stepper
          value={value}
          min={min}
          max={max}
          step={step}
          onCommit={(v) => onChange(clamp(v))}
          label={ariaLabel}
          prefix={prefix}
          suffix={suffix}
          color={color}
          money={money}
          disabled={disabled}
        />
      </div>
    );
  }
  return (
    <PlainNumber
      id={id}
      value={value}
      clamp={clamp}
      onChange={onChange}
      ariaLabel={ariaLabel}
      money={money}
      prefix={prefix}
      suffix={suffix}
      display={display}
      color={color}
      disabled={disabled}
      className={className}
    />
  );
}

function PlainNumber({
  id,
  value,
  clamp,
  onChange,
  ariaLabel,
  money,
  prefix,
  suffix,
  display,
  color,
  disabled,
  className,
}: {
  id?: string;
  value: number;
  clamp: (v: number) => number;
  onChange: (v: number) => void;
  ariaLabel: string;
  money?: boolean;
  prefix?: ReactNode;
  suffix?: ReactNode;
  display?: (v: number) => string;
  color: string;
  disabled?: boolean;
  className?: string;
}) {
  const [focused, setFocused] = useState(false);
  const [text, setText] = useState(String(value));
  useEffect(() => {
    if (!focused) setText(String(value));
  }, [value, focused]);
  const commit = () => {
    const n = Number(text.replace(/[,\s₹$]/g, ''));
    if (text.trim() === '' || !Number.isFinite(n)) {
      setText(String(value));
      return;
    }
    const v = clamp(n);
    setText(String(v));
    if (v !== value) onChange(v);
  };
  return (
    <label
      className={cn(
        'inline-flex h-10 items-baseline gap-1 rounded-xl border border-white/10 bg-white/[.04] px-3 transition-[border-color,box-shadow]',
        disabled && 'opacity-50',
        className,
      )}
      style={focused ? { borderColor: withAlpha(color, 0.5), boxShadow: `0 0 0 3px ${withAlpha(color, 0.12)}` } : undefined}
    >
      {prefix && <span className={cn('self-center text-sm', money ? 'text-gold' : 'text-muted')}>{prefix}</span>}
      <input
        id={id}
        aria-label={ariaLabel}
        inputMode="decimal"
        disabled={disabled}
        value={focused || !display ? text : display(value)}
        onFocus={() => setFocused(true)}
        onBlur={() => {
          setFocused(false);
          commit();
        }}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
          if (e.key === 'Escape') {
            setText(String(value));
            (e.target as HTMLInputElement).blur();
          }
        }}
        className={cn(
          'min-w-0 flex-1 self-center bg-transparent text-right font-display text-[15px] font-semibold tabular outline-none',
          money ? 'text-money' : 'text-ink',
        )}
      />
      {suffix && <span className="self-center text-xs text-muted">{suffix}</span>}
    </label>
  );
}

// ── slider ────────────────────────────────────────────────────────────

export interface SliderMark {
  value: number;
  label?: string;
}

export interface SliderPin {
  value: number;
  color: string;
  label: string;
}

export interface SliderBand {
  from: number;
  to: number;
  color: string;
}

export interface SliderProps {
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (v: number) => void;
  'aria-label'?: string;
  label?: string;
  color?: string;
  format?: (v: number) => string;
  marks?: readonly SliderMark[];
  /** other values drawn as small ticks on the track (e.g. the other threshold) */
  pins?: readonly SliderPin[];
  /** coloured zones under the track (e.g. ratio bands) */
  bands?: readonly SliderBand[];
  disabled?: boolean;
  className?: string;
}

function decimalsOf(step: number): number {
  const s = String(step);
  return s.includes('.') ? s.length - s.indexOf('.') - 1 : 0;
}

export function Slider({
  value,
  min,
  max,
  step = 1,
  onChange,
  'aria-label': ariaLabel,
  label,
  color = '#22D3EE',
  format,
  marks,
  pins,
  bands,
  disabled,
  className,
}: SliderProps) {
  const track = useRef<HTMLDivElement>(null);
  const latest = useRef(value);
  const [dragging, setDragging] = useState(false);
  latest.current = value;
  const span = max - min || 1;
  const pos = (v: number) => Math.max(0, Math.min(1, (v - min) / span));
  const frac = pos(value);
  const dec = decimalsOf(step);

  const snap = useCallback(
    (v: number) => Number(Math.max(min, Math.min(max, Math.round((v - min) / step) * step + min)).toFixed(dec)),
    [min, max, step, dec],
  );
  const set = (v: number) => {
    if (v !== latest.current) {
      latest.current = v;
      onChange(v);
    }
  };
  const fromPointer = (clientX: number) => {
    const r = track.current?.getBoundingClientRect();
    if (!r || r.width === 0) return latest.current;
    return snap(min + ((clientX - r.left) / r.width) * span);
  };
  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (disabled) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    setDragging(true);
    set(fromPointer(e.clientX));
  };
  const onKeyDown = (e: ReactKeyboardEvent) => {
    if (disabled) return;
    const big = Math.max(step, span / 10);
    const map: Record<string, number> = { ArrowRight: step, ArrowUp: step, ArrowLeft: -step, ArrowDown: -step, PageUp: big, PageDown: -big };
    if (e.key in map) {
      e.preventDefault();
      set(snap(latest.current + map[e.key]));
    } else if (e.key === 'Home') {
      e.preventDefault();
      set(min);
    } else if (e.key === 'End') {
      e.preventDefault();
      set(max);
    }
  };

  return (
    <div className={cn('min-w-0 select-none', disabled && 'opacity-40', className)}>
      <div
        ref={track}
        role="slider"
        tabIndex={disabled ? -1 : 0}
        aria-label={ariaLabel ?? label}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuenow={value}
        aria-valuetext={format ? format(value) : undefined}
        aria-disabled={disabled}
        onPointerDown={onPointerDown}
        onPointerMove={(e) => dragging && set(fromPointer(e.clientX))}
        onPointerUp={() => setDragging(false)}
        onPointerCancel={() => setDragging(false)}
        onKeyDown={onKeyDown}
        className={cn('group relative flex h-8 touch-none items-center rounded-full outline-none focus-visible:ring-2 focus-visible:ring-white/20', disabled ? 'cursor-not-allowed' : 'cursor-pointer')}
      >
        <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-white/[.08]">
          {bands?.map((b) => (
            <div
              key={`${b.from}-${b.to}`}
              aria-hidden
              className="absolute inset-y-0"
              style={{ left: `${pos(b.from) * 100}%`, width: `${(pos(b.to) - pos(b.from)) * 100}%`, backgroundColor: withAlpha(b.color, 0.28) }}
            />
          ))}
          <div
            className="absolute inset-0 origin-left rounded-full"
            style={{ transform: `scaleX(${frac})`, background: `linear-gradient(90deg, ${withAlpha(color, 0.35)}, ${color})` }}
          />
        </div>
        {pins?.map((p) => (
          <span
            key={p.label}
            title={`${p.label}: ${format ? format(p.value) : p.value}`}
            aria-hidden
            className="pointer-events-none absolute top-1/2 h-4 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-full"
            style={{ left: `${pos(p.value) * 100}%`, backgroundColor: p.color, boxShadow: `0 0 8px ${withAlpha(p.color, 0.8)}` }}
          />
        ))}
        <div className="pointer-events-none absolute inset-y-0 left-0 w-full" style={{ transform: `translateX(${frac * 100}%)` }}>
          <span
            className={cn(
              'absolute top-1/2 left-0 block size-[18px] -translate-x-1/2 -translate-y-1/2 rounded-full border-2 transition-transform duration-150',
              dragging ? 'scale-110' : 'group-hover:scale-105',
            )}
            style={{ borderColor: color, backgroundColor: '#0A101C', boxShadow: `0 0 14px ${withAlpha(color, 0.7)}` }}
          />
        </div>
      </div>
      {marks && marks.length > 0 && (
        <div className="relative mt-1 h-4 text-[10px] text-faint tabular">
          {marks.map((m, i) => (
            <span
              key={m.value}
              className={cn(
                'absolute whitespace-nowrap',
                i === 0 ? 'translate-x-0' : i === marks.length - 1 ? '-translate-x-full' : '-translate-x-1/2',
              )}
              style={{ left: `${pos(m.value) * 100}%` }}
            >
              {m.label ?? m.value}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
