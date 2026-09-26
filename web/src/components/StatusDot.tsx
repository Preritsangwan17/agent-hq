/** Status dot with optional pulse halo (transform/opacity animation only). */
import { cn } from '@/lib/cn';

export interface StatusDotProps {
  color: string;
  pulse?: boolean;
  size?: number;
  className?: string;
  label?: string;
}

export function StatusDot({ color, pulse, size = 8, className, label }: StatusDotProps) {
  return (
    <span className={cn('relative inline-flex shrink-0', className)} style={{ width: size, height: size }} aria-label={label} role={label ? 'img' : undefined}>
      {pulse && <span className="absolute inset-0 animate-pulse-ring rounded-full" style={{ backgroundColor: color }} />}
      <span className="relative inline-block size-full rounded-full" style={{ backgroundColor: color, boxShadow: `0 0 8px ${color}` }} />
    </span>
  );
}
