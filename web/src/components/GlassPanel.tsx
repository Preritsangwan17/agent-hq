/**
 * GlassPanel: the base surface. Translucent white/4% + backdrop blur + white/10 hairline + soft outer glow.
 * `glow` tints the glow (e.g. an agent color); `interactive` adds a hover lift (transform only).
 */
import { forwardRef, type CSSProperties, type HTMLAttributes } from 'react';
import { cn } from '@/lib/cn';
import { withAlpha } from '@/theme/tokens';

export interface GlassPanelProps extends HTMLAttributes<HTMLDivElement> {
  as?: 'div' | 'section' | 'article' | 'aside';
  /** hex color for the outer glow + top highlight */
  glow?: string;
  /** glow strength 0..1 (default 0.35) */
  glowStrength?: number;
  padding?: 'none' | 'sm' | 'md' | 'lg';
  interactive?: boolean;
  /** thin gradient line along the top edge in the glow color */
  accentTop?: boolean;
}

const PAD = { none: '', sm: 'p-3', md: 'p-4 md:p-5', lg: 'p-5 md:p-7' } as const;

export const GlassPanel = forwardRef<HTMLDivElement, GlassPanelProps>(function GlassPanel(
  { as = 'div', glow, glowStrength = 0.35, padding = 'md', interactive, accentTop, className, style, children, ...rest },
  ref,
) {
  const s: CSSProperties & Record<string, string> = { ...(style as Record<string, string>) };
  if (glow) s['--glow'] = withAlpha(glow, glowStrength);
  const Tag = as as 'div';
  return (
    <Tag
      ref={ref}
      className={cn(
        'glass relative min-w-0 rounded-2xl',
        PAD[padding],
        interactive &&
          'transition-transform duration-200 ease-out will-change-transform hover:-translate-y-0.5 active:translate-y-0',
        className,
      )}
      style={s}
      {...rest}
    >
      {accentTop && (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-x-6 top-0 h-px"
          style={{ background: `linear-gradient(90deg, transparent, ${withAlpha(glow ?? '#22D3EE', 0.8)}, transparent)` }}
        />
      )}
      {children}
    </Tag>
  );
});
