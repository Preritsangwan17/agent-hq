/**
 * Hold-to-confirm button (pointer or Space/Enter held for `holdMs`, default 1.2 s). The fill is a scaleX
 * transform driven by motion; releasing early cancels. Used for RESUME and other dangerous confirmations.
 */
import { animate, motion, useMotionValue, useReducedMotion } from 'motion/react';
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { withAlpha } from '@/theme/tokens';

export interface HoldButtonProps {
  onConfirm: () => void | Promise<void>;
  children: ReactNode;
  holdMs?: number;
  color?: string;
  disabled?: boolean;
  className?: string;
  /** text shown while holding, e.g. "Keep holding…" */
  holdingLabel?: ReactNode;
  title?: string;
  'aria-label'?: string;
}

export function HoldButton({
  onConfirm,
  children,
  holdMs = 1200,
  color = '#34D399',
  disabled,
  className,
  holdingLabel,
  title,
  ...aria
}: HoldButtonProps) {
  const progress = useMotionValue(0);
  const reduce = useReducedMotion();
  const [holding, setHolding] = useState(false);
  const [busy, setBusy] = useState(false);
  const ctrl = useRef<ReturnType<typeof animate> | null>(null);

  const cancel = useCallback(() => {
    ctrl.current?.stop();
    setHolding(false);
    ctrl.current = animate(progress, 0, { duration: reduce ? 0 : 0.25, ease: 'easeOut' });
  }, [progress, reduce]);

  const start = useCallback(() => {
    if (disabled || busy) return;
    setHolding(true);
    ctrl.current?.stop();
    ctrl.current = animate(progress, 1, {
      duration: (holdMs / 1000) * (1 - progress.get()),
      ease: 'linear',
      onComplete: async () => {
        setHolding(false);
        setBusy(true);
        try {
          await onConfirm();
        } finally {
          setBusy(false);
          progress.set(0);
        }
      },
    });
  }, [disabled, busy, holdMs, onConfirm, progress]);

  useEffect(() => () => ctrl.current?.stop(), []);

  return (
    <button
      type="button"
      title={title}
      aria-label={aria['aria-label']}
      disabled={disabled || busy}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        start();
      }}
      onPointerUp={cancel}
      onPointerCancel={cancel}
      onPointerLeave={() => holding && cancel()}
      onKeyDown={(e) => {
        if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) {
          e.preventDefault();
          start();
        }
      }}
      onKeyUp={(e) => {
        if (e.key === ' ' || e.key === 'Enter') cancel();
      }}
      onContextMenu={(e) => e.preventDefault()}
      className={cn(
        'relative inline-flex select-none items-center justify-center gap-2 overflow-hidden rounded-xl border font-semibold touch-none disabled:opacity-60',
        className,
      )}
      style={{ borderColor: withAlpha(color, 0.5), color, backgroundColor: withAlpha(color, 0.08) }}
    >
      <motion.span
        aria-hidden
        className="absolute inset-0 origin-left"
        style={{ scaleX: progress, backgroundColor: withAlpha(color, 0.28) }}
      />
      <span className="relative inline-flex items-center gap-2">{holding && holdingLabel ? holdingLabel : children}</span>
    </button>
  );
}
