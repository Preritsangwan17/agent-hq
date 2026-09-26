/**
 * Countdown to a deadline (UTC ISO → shown relative, exact IST time in the tooltip).
 * Ticks every second under 1 h, otherwise every 30 s. Colors: ≥ 7 d muted, < 7 d ink, < 48 h amber;
 * past → "Closed"; no deadline / rolling → "Rolling".
 */
import { CalendarClock, Hourglass } from 'lucide-react';
import { cn } from '@/lib/cn';
import { formatDateTimeIST, formatDuration, formatRelative, toDate } from '@/lib/format';
import { useNow } from '@/lib/hooks';
import { colors } from '@/theme/tokens';
import { Tooltip } from './Tooltip';

export interface CountdownProps {
  deadline: string | null | undefined;
  confidence?: string | null;
  /** "12d" instead of "12d 4h left" */
  compact?: boolean;
  showIcon?: boolean;
  className?: string;
}

export function Countdown({ deadline, confidence, compact, showIcon = true, className }: CountdownProps) {
  const d = toDate(deadline);
  const initialLeft = d ? d.getTime() - Date.now() : null;
  const now = useNow(initialLeft != null && initialLeft > 0 && initialLeft < 3600_000 ? 1000 : 30_000);

  if (!d || confidence === 'rolling') {
    return (
      <Tooltip content="No fixed deadline — re-verified every 3 days.">
        <span className={cn('inline-flex items-center gap-1 text-xs text-muted', className)}>
          {showIcon && <CalendarClock className="size-3.5" aria-hidden />}
          Rolling
        </span>
      </Tooltip>
    );
  }

  const left = d.getTime() - now;
  const past = left <= 0;
  const color = past ? colors.faint : left < 48 * 3600_000 ? colors.warn : left < 7 * 86400_000 ? colors.ink : colors.muted;
  let text: string;
  if (past) text = compact ? 'Closed' : `Closed ${formatRelative(deadline, now)}`;
  else if (compact) text = formatDuration(left).split(' ')[0];
  else text = `${formatDuration(left)} left`;

  return (
    <Tooltip
      content={
        <div>
          <div>Deadline {formatDateTimeIST(deadline)} IST</div>
          {confidence && <div className="text-muted">Confidence: {confidence} · applied 1 day early</div>}
        </div>
      }
    >
      <span className={cn('inline-flex items-center gap-1 text-xs font-medium tabular', past && 'line-through decoration-white/20', className)} style={{ color }}>
        {showIcon && <Hourglass className="size-3.5" aria-hidden />}
        {text}
      </span>
    </Tooltip>
  );
}
