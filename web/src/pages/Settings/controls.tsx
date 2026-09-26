/**
 * Form controls shared by the Settings and Agents pages: switch, segmented control, slider, stepper, text input,
 * field label, modal and drawer shells, copy button and a two-step confirm button. They live here (page-local)
 * rather than in src/components; promote them there once another page needs them.
 * Motion is transform/opacity only; `MotionConfig reducedMotion="user"` (main.tsx) handles reduced motion.
 */
import { AnimatePresence, motion } from 'motion/react';
import { Check, Copy, LoaderCircle, Minus, Plus, X, type LucideIcon } from 'lucide-react';
import {
  forwardRef,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type InputHTMLAttributes,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type RefObject,
} from 'react';
import { createPortal } from 'react-dom';
import { cn } from '@/lib/cn';
import { useIsMobile } from '@/lib/hooks';
import { withAlpha } from '@/theme/tokens';

// ── switch ────────────────────────────────────────────────────────────

export interface SwitchProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  /** accessible name */
  label: string;
  disabled?: boolean;
  color?: string;
  size?: 'sm' | 'md' | 'lg';
  id?: string;
  title?: string;
}

const SWITCH_DIMS = { sm: { w: 32, h: 18, k: 12 }, md: { w: 40, h: 22, k: 16 }, lg: { w: 52, h: 28, k: 22 } } as const;

export function Switch({ checked, onChange, label, disabled, color = '#22D3EE', size = 'md', id, title }: SwitchProps) {
  const d = SWITCH_DIMS[size];
  const travel = d.w - d.k - 6;
  return (
    <button
      type="button"
      role="switch"
      id={id}
      title={title}
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="relative inline-block shrink-0 rounded-full border transition-[background-color,border-color,box-shadow] duration-200 disabled:opacity-40"
      style={{
        width: d.w,
        height: d.h,
        borderColor: checked ? withAlpha(color, 0.55) : 'rgba(255,255,255,0.14)',
        backgroundColor: checked ? withAlpha(color, 0.22) : 'rgba(255,255,255,0.06)',
        boxShadow: checked ? `0 0 16px -4px ${withAlpha(color, 0.75)}` : 'none',
      }}
    >
      <span
        aria-hidden
        className="absolute top-1/2 left-[2px] rounded-full transition-transform duration-200 ease-out"
        style={{
          width: d.k,
          height: d.k,
          transform: `translate(${checked ? travel : 0}px, -50%)`,
          backgroundColor: checked ? color : '#8B95A7',
          boxShadow: checked ? `0 0 10px ${withAlpha(color, 0.8)}` : 'none',
        }}
      />
    </button>
  );
}

// ── segmented ─────────────────────────────────────────────────────────

export interface SegOption<T extends string | number> {
  value: T;
  label: ReactNode;
  icon?: LucideIcon;
  title?: string;
  disabled?: boolean;
}

export interface SegmentedProps<T extends string | number> {
  value: T;
  options: readonly SegOption<T>[];
  onChange: (v: T) => void;
  /** accessible name of the group */
  label: string;
  color?: string;
  size?: 'sm' | 'md';
  full?: boolean;
  className?: string;
}

export function Segmented<T extends string | number>({
  value,
  options,
  onChange,
  label,
  color = '#22D3EE',
  size = 'md',
  full,
  className,
}: SegmentedProps<T>) {
  const uid = useId();
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn(
        'relative max-w-full gap-0.5 overflow-x-auto rounded-xl border border-white/10 bg-white/[.03] p-1 scrollbar-none',
        full ? 'flex w-full' : 'inline-flex',
        className,
      )}
    >
      {options.map((o) => {
        const active = o.value === value;
        const Icon = o.icon;
        return (
          <button
            key={String(o.value)}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={o.disabled}
            title={o.title}
            onClick={() => onChange(o.value)}
            className={cn(
              'relative z-0 inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg font-medium whitespace-nowrap transition-colors duration-150 disabled:opacity-40',
              size === 'sm' ? 'h-7 px-2.5 text-xs' : 'h-8 px-3 text-[13px]',
              full && 'flex-1',
              active ? 'text-ink' : 'text-muted hover:text-ink',
            )}
          >
            {active && (
              <motion.span
                layoutId={`seg-${uid}`}
                aria-hidden
                className="absolute inset-0 -z-10 rounded-lg border"
                style={{
                  borderColor: withAlpha(color, 0.45),
                  backgroundColor: withAlpha(color, 0.14),
                  boxShadow: `0 0 18px -6px ${withAlpha(color, 0.8)}`,
                }}
                transition={{ type: 'spring', stiffness: 520, damping: 40 }}
              />
            )}
            {Icon && <Icon className="size-3.5" style={active ? { color } : undefined} aria-hidden />}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

// ── slider ────────────────────────────────────────────────────────────

export interface SliderProps {
  value: number;
  min: number;
  max: number;
  step?: number;
  /** live value while dragging / pressing keys */
  onChange: (v: number) => void;
  /** final value (pointer up, key up) — save here */
  onCommit?: (v: number) => void;
  label: string;
  color?: string;
  /** formatter for aria-valuetext */
  format?: (v: number) => string;
  /** tick marks under the track */
  marks?: readonly { value: number; label?: string }[];
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
  onCommit,
  label,
  color = '#22D3EE',
  format,
  marks,
  disabled,
  className,
}: SliderProps) {
  const track = useRef<HTMLDivElement>(null);
  const latest = useRef(value);
  const [dragging, setDragging] = useState(false);
  latest.current = value;
  const span = max - min || 1;
  const frac = Math.max(0, Math.min(1, (value - min) / span));
  const dec = decimalsOf(step);

  const snap = useCallback(
    (v: number) => Number(Math.max(min, Math.min(max, Math.round((v - min) / step) * step + min)).toFixed(dec)),
    [min, max, step, dec],
  );

  const fromPointer = (clientX: number) => {
    const r = track.current?.getBoundingClientRect();
    if (!r || r.width === 0) return latest.current;
    return snap(min + ((clientX - r.left) / r.width) * span);
  };

  const set = (v: number) => {
    if (v !== latest.current) {
      latest.current = v;
      onChange(v);
    }
  };

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (disabled) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    setDragging(true);
    set(fromPointer(e.clientX));
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (dragging) set(fromPointer(e.clientX));
  };
  const end = () => {
    if (!dragging) return;
    setDragging(false);
    onCommit?.(latest.current);
  };

  const onKeyDown = (e: ReactKeyboardEvent) => {
    if (disabled) return;
    const big = Math.max(step, (max - min) / 10);
    const map: Record<string, number> = {
      ArrowRight: step, ArrowUp: step, ArrowLeft: -step, ArrowDown: -step, PageUp: big, PageDown: -big,
    };
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
        aria-label={label}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuenow={value}
        aria-valuetext={format ? format(value) : undefined}
        aria-disabled={disabled}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={end}
        onPointerCancel={end}
        onKeyDown={onKeyDown}
        onKeyUp={(e) => {
          if (['ArrowRight', 'ArrowUp', 'ArrowLeft', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End'].includes(e.key)) {
            onCommit?.(latest.current);
          }
        }}
        className={cn('group relative flex h-7 touch-none items-center', disabled ? 'cursor-not-allowed' : 'cursor-pointer')}
      >
        <div className="relative h-1.5 w-full overflow-hidden rounded-full" style={{ backgroundColor: 'rgba(255,255,255,0.08)' }}>
          <div
            className="absolute inset-0 origin-left rounded-full"
            style={{
              transform: `scaleX(${frac})`,
              background: `linear-gradient(90deg, ${withAlpha(color, 0.35)}, ${color})`,
            }}
          />
        </div>
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
          {marks.map((m) => (
            <span
              key={m.value}
              className="absolute -translate-x-1/2 whitespace-nowrap first:translate-x-0 last:-translate-x-full"
              style={{ left: `${((m.value - min) / span) * 100}%` }}
            >
              {m.label ?? m.value}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── stepper ───────────────────────────────────────────────────────────

export interface StepperProps {
  value: number;
  min: number;
  max: number;
  step?: number;
  onCommit: (v: number) => void;
  label: string;
  prefix?: ReactNode;
  suffix?: ReactNode;
  color?: string;
  disabled?: boolean;
  /** input width in ch (default 5) */
  width?: number;
  /** gold pay styling for ₹ amounts */
  money?: boolean;
}

export function Stepper({
  value,
  min,
  max,
  step = 1,
  onCommit,
  label,
  prefix,
  suffix,
  color = '#22D3EE',
  disabled,
  width = 5,
  money,
}: StepperProps) {
  const [text, setText] = useState(String(value));
  const [focused, setFocused] = useState(false);
  useEffect(() => {
    if (!focused) setText(String(value));
  }, [value, focused]);
  const dec = decimalsOf(step);
  const clamp = (v: number) => Number(Math.max(min, Math.min(max, v)).toFixed(dec));
  const commitText = () => {
    const n = Number(text.replace(/[,\s₹$]/g, ''));
    if (!Number.isFinite(n) || text.trim() === '') {
      setText(String(value));
      return;
    }
    const v = clamp(n);
    setText(String(v));
    if (v !== value) onCommit(v);
  };
  const bump = (dir: 1 | -1) => {
    const v = clamp(value + dir * step);
    if (v !== value) onCommit(v);
  };
  const btn =
    'grid size-8 shrink-0 place-items-center rounded-lg text-muted transition-colors hover:bg-white/[.08] hover:text-ink disabled:opacity-30 disabled:hover:bg-transparent';
  return (
    <div
      className={cn(
        'inline-flex h-10 items-center gap-0.5 rounded-xl border border-white/10 bg-white/[.04] px-1 transition-[border-color,box-shadow]',
        disabled && 'opacity-50',
      )}
      style={focused ? { borderColor: withAlpha(color, 0.5), boxShadow: `0 0 0 3px ${withAlpha(color, 0.12)}` } : undefined}
    >
      <button type="button" className={btn} onClick={() => bump(-1)} disabled={disabled || value <= min} aria-label={`Decrease ${label}`}>
        <Minus className="size-3.5" aria-hidden />
      </button>
      <label className="flex items-baseline gap-0.5 px-1">
        {prefix && <span className={cn('text-sm', money ? 'text-gold' : 'text-muted')}>{prefix}</span>}
        <input
          value={text}
          inputMode="decimal"
          aria-label={label}
          disabled={disabled}
          onFocus={() => setFocused(true)}
          onBlur={() => {
            setFocused(false);
            commitText();
          }}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
            if (e.key === 'Escape') {
              setText(String(value));
              (e.target as HTMLInputElement).blur();
            }
            if (e.key === 'ArrowUp') {
              e.preventDefault();
              bump(1);
            }
            if (e.key === 'ArrowDown') {
              e.preventDefault();
              bump(-1);
            }
          }}
          className={cn(
            'bg-transparent text-center font-display text-[15px] font-semibold tabular outline-none focus-visible:outline-none',
            money ? 'text-money' : 'text-ink',
          )}
          style={{ width: `${width}ch` }}
        />
        {suffix && <span className="text-xs text-muted">{suffix}</span>}
      </label>
      <button type="button" className={btn} onClick={() => bump(1)} disabled={disabled || value >= max} aria-label={`Increase ${label}`}>
        <Plus className="size-3.5" aria-hidden />
      </button>
    </div>
  );
}

// ── text input / field ────────────────────────────────────────────────

export interface TextInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'prefix'> {
  invalid?: boolean;
  mono?: boolean;
  leading?: ReactNode;
  trailing?: ReactNode;
  wrapperClassName?: string;
}

export const TextInput = forwardRef<HTMLInputElement, TextInputProps>(function TextInput(
  { invalid, mono, leading, trailing, className, wrapperClassName, ...rest },
  ref,
) {
  return (
    <div
      className={cn(
        'flex h-10 min-w-0 items-center gap-2 rounded-xl border bg-white/[.04] px-3 transition-[border-color,box-shadow,background-color] duration-150',
        'focus-within:bg-white/[.06]',
        invalid
          ? 'border-red-400/50 focus-within:shadow-[0_0_0_3px_rgba(248,113,113,0.14)]'
          : 'border-white/10 focus-within:border-cyan-300/50 focus-within:shadow-[0_0_0_3px_rgba(34,211,238,0.12)]',
        rest.disabled && 'opacity-50',
        wrapperClassName,
      )}
    >
      {leading && <span className="flex shrink-0 items-center text-sm text-faint">{leading}</span>}
      <input
        ref={ref}
        spellCheck={false}
        {...rest}
        aria-invalid={invalid || undefined}
        className={cn(
          'h-full min-w-0 flex-1 bg-transparent text-sm text-ink placeholder:text-faint outline-none focus-visible:outline-none',
          mono && 'font-mono text-[13px]',
          className,
        )}
      />
      {trailing && <span className="flex shrink-0 items-center">{trailing}</span>}
    </div>
  );
});

export interface FieldProps {
  label: ReactNode;
  htmlFor?: string;
  hint?: ReactNode;
  error?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Field({ label, htmlFor, hint, error, right, children, className }: FieldProps) {
  return (
    <div className={cn('min-w-0', className)}>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <label htmlFor={htmlFor} className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted">
          {label}
        </label>
        {right}
      </div>
      {children}
      <AnimatePresence initial={false} mode="wait">
        {error ? (
          <motion.p
            key="err"
            initial={{ opacity: 0, y: -3 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="mt-1.5 text-xs text-red-300"
            role="alert"
          >
            {error}
          </motion.p>
        ) : hint ? (
          <motion.p key="hint" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="mt-1.5 text-xs leading-relaxed text-faint">
            {hint}
          </motion.p>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

// ── overlays ──────────────────────────────────────────────────────────

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

/** Escape to close, Tab focus trap, body scroll lock, focus restore. */
function useDialogBehaviour(open: boolean, onClose: () => void, panel: RefObject<HTMLDivElement | null>) {
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    if (!open) return;
    const prevFocus = document.activeElement as HTMLElement | null;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const t = setTimeout(() => {
      const el = panel.current;
      if (!el || el.contains(document.activeElement)) return;
      const auto = el.querySelector<HTMLElement>('[data-autofocus]') ?? el.querySelector<HTMLElement>(FOCUSABLE);
      (auto ?? el).focus({ preventScroll: true });
    }, 60);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        closeRef.current();
        return;
      }
      if (e.key !== 'Tab' || !panel.current) return;
      const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((n) => n.offsetParent !== null);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      clearTimeout(t);
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
      prevFocus?.focus?.({ preventScroll: true });
    };
  }, [open, panel]);
}

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  labelledBy?: string;
  children: ReactNode;
  /** desktop max width class (default max-w-5xl) */
  widthClass?: string;
  className?: string;
}

/** Centered dialog on desktop, full-height sheet on mobile. */
export function Modal({ open, onClose, labelledBy, children, widthClass = 'max-w-5xl', className }: ModalProps) {
  const mobile = useIsMobile();
  const panel = useRef<HTMLDivElement>(null);
  useDialogBehaviour(open, onClose, panel);
  return createPortal(
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-[80] flex items-end justify-center md:items-center md:p-6">
          <motion.div
            className="absolute inset-0 bg-[#02050b]/75 backdrop-blur-[6px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
            aria-hidden
          />
          <motion.div
            ref={panel}
            role="dialog"
            aria-modal="true"
            aria-labelledby={labelledBy}
            tabIndex={-1}
            initial={mobile ? { y: '100%' } : { opacity: 0, scale: 0.965, y: 14 }}
            animate={mobile ? { y: 0 } : { opacity: 1, scale: 1, y: 0 }}
            exit={mobile ? { y: '100%' } : { opacity: 0, scale: 0.98, y: 8 }}
            transition={{ type: 'spring', stiffness: 380, damping: 36 }}
            className={cn(
              'relative flex w-full flex-col overflow-hidden border border-white/10 bg-[#0A101C]/95 shadow-[0_40px_120px_-30px_rgba(0,0,0,0.9)] outline-none backdrop-blur-2xl',
              mobile ? 'h-[100dvh] rounded-none' : cn('max-h-[min(880px,92dvh)] rounded-3xl', widthClass),
              className,
            )}
          >
            {children}
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body,
  );
}

export interface DrawerProps {
  open: boolean;
  onClose: () => void;
  labelledBy?: string;
  children: ReactNode;
  glow?: string;
}

/** Right-side drawer on desktop, bottom sheet on mobile. */
export function Drawer({ open, onClose, labelledBy, children, glow = '#22D3EE' }: DrawerProps) {
  const mobile = useIsMobile();
  const panel = useRef<HTMLDivElement>(null);
  useDialogBehaviour(open, onClose, panel);
  return createPortal(
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-[80] flex items-end justify-end md:items-stretch">
          <motion.div
            className="absolute inset-0 bg-[#02050b]/65 backdrop-blur-[3px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
            aria-hidden
          />
          <motion.div
            ref={panel}
            role="dialog"
            aria-modal="true"
            aria-labelledby={labelledBy}
            tabIndex={-1}
            initial={mobile ? { y: '100%' } : { x: '100%' }}
            animate={mobile ? { y: 0 } : { x: 0 }}
            exit={mobile ? { y: '100%' } : { x: '100%' }}
            transition={{ type: 'spring', stiffness: 360, damping: 38 }}
            className={cn(
              'relative flex flex-col overflow-hidden border-white/10 bg-[#0A101C]/95 outline-none backdrop-blur-2xl',
              mobile ? 'max-h-[92dvh] w-full rounded-t-3xl border-t' : 'h-full w-[460px] border-l',
            )}
            style={{ boxShadow: `-30px 0 90px -40px ${withAlpha(glow, 0.45)}` }}
          >
            <span
              aria-hidden
              className="pointer-events-none absolute inset-x-0 top-0 h-px"
              style={{ background: `linear-gradient(90deg, transparent, ${withAlpha(glow, 0.8)}, transparent)` }}
            />
            {children}
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body,
  );
}

export function CloseButton({ onClick, label = 'Close' }: { onClick: () => void; label?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="grid size-9 shrink-0 place-items-center rounded-xl border border-white/10 bg-white/[.04] text-muted transition-colors hover:bg-white/[.08] hover:text-ink"
    >
      <X className="size-4" aria-hidden />
    </button>
  );
}

// ── copy / confirm ────────────────────────────────────────────────────

export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to the textarea fallback */
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    ta.remove();
    return ok;
  } catch {
    return false;
  }
}

export interface CopyButtonProps {
  value: string;
  /** what is being copied, for the accessible name ("Copy Full name") */
  what?: string;
  label?: string;
  iconOnly?: boolean;
  className?: string;
}

export function CopyButton({ value, what, label = 'Copy', iconOnly, className }: CopyButtonProps) {
  const [state, setState] = useState<'idle' | 'ok' | 'fail'>('idle');
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const ok = state === 'ok';
  return (
    <button
      type="button"
      onClick={async () => {
        const res = await copyText(value);
        setState(res ? 'ok' : 'fail');
        clearTimeout(timer.current);
        timer.current = setTimeout(() => setState('idle'), 1600);
      }}
      aria-label={`${label}${what ? ` ${what}` : ''}`}
      className={cn(
        'relative inline-flex h-8 shrink-0 items-center justify-center gap-1.5 overflow-hidden rounded-lg border text-xs font-medium transition-colors duration-150',
        iconOnly ? 'w-8' : 'px-2.5',
        ok
          ? 'border-emerald-400/40 bg-emerald-400/10 text-emerald-300'
          : state === 'fail'
            ? 'border-red-400/40 bg-red-400/10 text-red-300'
            : 'border-white/10 bg-white/[.04] text-muted hover:border-white/20 hover:bg-white/[.08] hover:text-ink',
        className,
      )}
    >
      <AnimatePresence initial={false} mode="popLayout">
        <motion.span
          key={state}
          initial={{ opacity: 0, scale: 0.6 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.6 }}
          transition={{ duration: 0.14 }}
          className="inline-flex"
        >
          {ok ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
        </motion.span>
      </AnimatePresence>
      {!iconOnly && <span>{ok ? 'Copied' : state === 'fail' ? 'Failed' : label}</span>}
      <span className="sr-only" aria-live="polite">
        {ok ? 'Copied' : ''}
      </span>
    </button>
  );
}

export interface ConfirmButtonProps {
  onConfirm: () => void | Promise<void>;
  children: ReactNode;
  confirmLabel?: ReactNode;
  icon?: LucideIcon;
  /** tint while armed (default amber) */
  color?: string;
  disabled?: boolean;
  className?: string;
}

/** Two-step button: the first click arms it for 4 s, the second confirms. */
export function ConfirmButton({
  onConfirm,
  children,
  confirmLabel = 'Click again to confirm',
  icon: Icon,
  color = '#FBBF24',
  disabled,
  className,
}: ConfirmButtonProps) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  return (
    <button
      type="button"
      disabled={disabled || busy}
      onClick={async () => {
        if (!armed) {
          setArmed(true);
          clearTimeout(timer.current);
          timer.current = setTimeout(() => setArmed(false), 4000);
          return;
        }
        clearTimeout(timer.current);
        setArmed(false);
        setBusy(true);
        try {
          await onConfirm();
        } finally {
          setBusy(false);
        }
      }}
      className={cn(
        'inline-flex h-10 items-center justify-center gap-2 rounded-xl border px-4 text-sm font-medium transition-[background-color,border-color,color] duration-150 disabled:opacity-50',
        !armed && 'border-white/10 bg-white/[.05] text-ink hover:border-white/20 hover:bg-white/[.09]',
        className,
      )}
      style={armed ? { borderColor: withAlpha(color, 0.55), backgroundColor: withAlpha(color, 0.14), color } : undefined}
    >
      {busy ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : Icon && <Icon className="size-4" aria-hidden />}
      {armed ? confirmLabel : children}
    </button>
  );
}
