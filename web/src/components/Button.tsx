/** Button: primary (cyan), secondary (glass), ghost, danger (kill-switch red — errors/destructive only). */
import type { LucideIcon } from 'lucide-react';
import { LoaderCircle } from 'lucide-react';
import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  icon?: LucideIcon;
  iconRight?: LucideIcon;
  loading?: boolean;
}

const VARIANT = {
  primary:
    'bg-cyan-400/90 text-[#041018] border-cyan-300/60 hover:bg-cyan-300 shadow-[0_0_24px_-6px_rgba(34,211,238,0.6)]',
  secondary: 'bg-white/[.05] text-ink border-white/10 hover:bg-white/[.09] hover:border-white/20',
  ghost: 'bg-transparent text-muted border-transparent hover:bg-white/[.06] hover:text-ink',
  danger: 'bg-danger text-white border-red-400/60 hover:bg-red-500 shadow-[0_0_24px_-6px_rgba(239,68,68,0.7)]',
} as const;

const SIZE = {
  sm: 'h-8 px-3 text-xs gap-1.5 rounded-lg',
  md: 'h-10 px-4 text-sm gap-2 rounded-xl',
  lg: 'h-12 px-5 text-base gap-2 rounded-xl',
} as const;

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', icon: Icon, iconRight: IconRight, loading, className, children, disabled, type = 'button', ...rest },
  ref,
) {
  const iconCls = size === 'lg' ? 'size-5' : size === 'sm' ? 'size-3.5' : 'size-4';
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      className={cn(
        'inline-flex select-none items-center justify-center border font-medium transition-[background-color,border-color,color,transform] duration-150 active:scale-[0.98] disabled:opacity-50 disabled:active:scale-100',
        VARIANT[variant],
        SIZE[size],
        className,
      )}
      {...rest}
    >
      {loading ? <LoaderCircle className={cn(iconCls, 'animate-spin')} aria-hidden /> : Icon && <Icon className={iconCls} aria-hidden />}
      {children}
      {IconRight && !loading && <IconRight className={iconCls} aria-hidden />}
    </button>
  );
});
