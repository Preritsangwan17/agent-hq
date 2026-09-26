/** Small "SIM" tag for simulated rows (opportunities.is_simulated = 1). Renders nothing when `show` is false. */
import { cn } from '@/lib/cn';
import { Tooltip } from './Tooltip';

export interface SimTagProps {
  show?: boolean;
  className?: string;
}

export function SimTag({ show = true, className }: SimTagProps) {
  if (!show) return null;
  return (
    <Tooltip content="Simulated by the sim adapter — fictional organisation, nothing was sent.">
      <span
        className={cn(
          'inline-flex h-[18px] items-center rounded-[5px] border border-dashed border-cyan-300/40 bg-cyan-300/[.06] px-1.5 font-mono text-[9.5px] font-semibold tracking-[0.14em] text-cyan-200/80',
          className,
        )}
      >
        SIM
      </span>
    </Tooltip>
  );
}
