/**
 * Tooltip: hover/focus (and tap on touch) popover rendered in a portal with fixed positioning, so it is never
 * clipped by scroll containers (kanban columns, virtualised lists). Flips below when there's no room above.
 */
import { AnimatePresence, motion } from 'motion/react';
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { cn } from '@/lib/cn';

export interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  side?: 'top' | 'bottom';
  /** ms before showing on hover (default 120) */
  delay?: number;
  maxWidth?: number;
  className?: string;
  /** className for the trigger wrapper span */
  triggerClassName?: string;
  disabled?: boolean;
}

interface Pos {
  x: number;
  y: number;
  side: 'top' | 'bottom';
}

export function Tooltip({
  content,
  children,
  side = 'top',
  delay = 120,
  maxWidth = 300,
  className,
  triggerClassName,
  disabled,
}: TooltipProps) {
  const id = useId();
  const triggerRef = useRef<HTMLSpanElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<Pos | null>(null);

  const show = useCallback(() => {
    if (disabled) return;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setOpen(true), delay);
  }, [delay, disabled]);
  const hide = useCallback(() => {
    clearTimeout(timer.current);
    setOpen(false);
  }, []);

  useEffect(() => () => clearTimeout(timer.current), []);

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return;
    const place = () => {
      const r = triggerRef.current!.getBoundingClientRect();
      const tip = tipRef.current?.getBoundingClientRect();
      const h = tip?.height ?? 60;
      const w = tip?.width ?? maxWidth;
      let s = side;
      if (s === 'top' && r.top - h - 10 < 4) s = 'bottom';
      if (s === 'bottom' && r.bottom + h + 10 > window.innerHeight - 4) s = 'top';
      const cx = r.left + r.width / 2;
      const x = Math.min(window.innerWidth - w / 2 - 8, Math.max(w / 2 + 8, cx));
      const y = s === 'top' ? r.top - 8 : r.bottom + 8;
      setPos({ x, y, side: s });
    };
    place();
    const raf = requestAnimationFrame(place);
    window.addEventListener('scroll', hide, true);
    window.addEventListener('resize', hide);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('scroll', hide, true);
      window.removeEventListener('resize', hide);
    };
  }, [open, side, maxWidth, hide]);

  return (
    <>
      <span
        ref={triggerRef}
        className={cn('inline-flex', triggerClassName)}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        onTouchStart={() => (open ? hide() : setOpen(true))}
        aria-describedby={open ? id : undefined}
      >
        {children}
      </span>
      {createPortal(
        <AnimatePresence>
          {open && content != null && (
            <motion.div
              ref={tipRef}
              id={id}
              role="tooltip"
              initial={{ opacity: 0, y: pos?.side === 'bottom' ? -4 : 4, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, transition: { duration: 0.08 } }}
              transition={{ duration: 0.14, ease: 'easeOut' }}
              style={{
                position: 'fixed',
                left: pos?.x ?? -9999,
                top: pos?.y ?? -9999,
                maxWidth,
                translate: pos?.side === 'bottom' ? '-50% 0' : '-50% -100%',
                visibility: pos ? 'visible' : 'hidden',
              }}
              className={cn(
                'pointer-events-none z-[100] rounded-xl border border-white/10 bg-[#0B111D]/95 px-3 py-2 text-xs leading-relaxed text-ink shadow-[0_18px_40px_-12px_rgba(0,0,0,0.8)] backdrop-blur-xl',
                className,
              )}
            >
              {content}
            </motion.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
}
