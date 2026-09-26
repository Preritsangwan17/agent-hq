/**
 * Small form controls shared by the Pipeline and Activity pages: a glass search field (focus with "/") and a
 * segmented control whose active pill glides with a motion layoutId (transform only).
 * Local to the page folders; candidates for promotion to src/components.
 */
import { motion } from 'motion/react';
import { Search, X, type LucideIcon } from 'lucide-react';
import { useEffect, useId, useRef, type ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { withAlpha } from '@/theme/tokens';

export interface SearchFieldProps {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
  /** focus on "/" (default true) */
  hotkey?: boolean;
  'aria-label'?: string;
}

export function SearchField({ value, onChange, placeholder = 'Search', className, hotkey = true, ...rest }: SearchFieldProps) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!hotkey) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      e.preventDefault();
      ref.current?.focus();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [hotkey]);

  return (
    <label
      className={cn(
        'group relative flex h-9 min-w-0 items-center gap-2 rounded-xl border border-white/10 bg-white/[.04] px-3 transition-colors focus-within:border-cyan-300/40 focus-within:bg-white/[.06]',
        className,
      )}
    >
      <Search className="size-4 shrink-0 text-muted group-focus-within:text-cyan-300" aria-hidden />
      <input
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            onChange('');
            (e.target as HTMLInputElement).blur();
          }
        }}
        placeholder={placeholder}
        aria-label={rest['aria-label'] ?? placeholder}
        className="min-w-0 flex-1 bg-transparent text-sm text-ink placeholder:text-faint focus:outline-none"
        spellCheck={false}
      />
      {value ? (
        <button
          type="button"
          onClick={() => onChange('')}
          className="grid size-5 shrink-0 place-items-center rounded-md text-muted hover:bg-white/10 hover:text-ink"
          aria-label="Clear search"
        >
          <X className="size-3.5" aria-hidden />
        </button>
      ) : (
        hotkey && (
          <kbd className="hidden shrink-0 rounded border border-white/10 bg-white/[.04] px-1.5 font-mono text-[10px] text-faint md:inline">/</kbd>
        )
      )}
    </label>
  );
}

export interface SegmentOption<T extends string | number> {
  value: T;
  label: ReactNode;
  icon?: LucideIcon;
  title?: string;
}

export interface SegmentedProps<T extends string | number> {
  value: T;
  options: readonly SegmentOption<T>[];
  onChange: (v: T) => void;
  /** accent for the active pill (default cyan) */
  color?: string;
  className?: string;
  'aria-label': string;
}

export function Segmented<T extends string | number>({ value, options, onChange, color = '#22D3EE', className, ...rest }: SegmentedProps<T>) {
  const id = useId();
  return (
    <div
      role="radiogroup"
      aria-label={rest['aria-label']}
      className={cn('relative inline-flex h-9 shrink-0 items-center rounded-xl border border-white/10 bg-white/[.03] p-0.5', className)}
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
            title={o.title}
            onClick={() => onChange(o.value)}
            className={cn(
              'relative inline-flex h-full items-center gap-1.5 whitespace-nowrap rounded-[10px] px-2.5 text-xs font-medium transition-colors',
              active ? 'text-ink' : 'text-muted hover:text-ink',
            )}
          >
            {active && (
              <motion.span
                layoutId={`seg-${id}`}
                className="absolute inset-0 rounded-[10px] border"
                style={{ backgroundColor: withAlpha(color, 0.14), borderColor: withAlpha(color, 0.35), boxShadow: `0 0 16px -6px ${withAlpha(color, 0.8)}` }}
                transition={{ type: 'spring', stiffness: 500, damping: 38 }}
              />
            )}
            {Icon && <Icon className="relative size-3.5" style={active ? { color } : undefined} aria-hidden />}
            <span className="relative tabular">{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Toggle chip (filters): tinted when on, outline when off. */
export function FilterChip({
  on,
  onClick,
  color = '#8B95A7',
  children,
  title,
  className,
}: {
  on: boolean;
  onClick: () => void;
  color?: string;
  children: ReactNode;
  title?: string;
  className?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      title={title}
      onClick={onClick}
      className={cn(
        'inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg border px-2 text-[11.5px] font-medium transition-[background-color,border-color,color,opacity] duration-150',
        on ? 'text-ink' : 'border-white/[.08] bg-transparent text-faint hover:border-white/15 hover:text-muted',
        className,
      )}
      style={on ? { backgroundColor: withAlpha(color, 0.12), borderColor: withAlpha(color, 0.38) } : undefined}
    >
      {children}
    </button>
  );
}
