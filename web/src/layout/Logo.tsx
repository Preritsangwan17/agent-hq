/** Agent HQ mark: a radar sweep in a rounded square + optional wordmark. */
import { cn } from '@/lib/cn';

export function LogoMark({ size = 32, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" className={className} aria-hidden>
      <defs>
        <linearGradient id="hq-mark-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#0E2A3A" />
          <stop offset="1" stopColor="#1B1440" />
        </linearGradient>
        <linearGradient id="hq-mark-sweep" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#22D3EE" stopOpacity="0" />
          <stop offset="1" stopColor="#22D3EE" stopOpacity="0.9" />
        </linearGradient>
      </defs>
      <rect x="0.5" y="0.5" width="31" height="31" rx="9" fill="url(#hq-mark-bg)" stroke="rgba(255,255,255,0.14)" />
      <circle cx="16" cy="16" r="9.5" fill="none" stroke="rgba(34,211,238,0.35)" />
      <circle cx="16" cy="16" r="5" fill="none" stroke="rgba(167,139,250,0.45)" />
      <path d="M16 16 L25.5 16 A9.5 9.5 0 0 0 22.7 9.3 Z" fill="url(#hq-mark-sweep)" opacity="0.8" />
      <circle cx="16" cy="16" r="1.8" fill="#E6EAF2" />
      <circle cx="22" cy="11.5" r="1.4" fill="#F5C451" />
      <circle cx="11" cy="20.5" r="1.1" fill="#F472B6" />
    </svg>
  );
}

export function Logo({ collapsed, className }: { collapsed?: boolean; className?: string }) {
  return (
    <div className={cn('flex items-center gap-2.5', className)}>
      <LogoMark size={32} className="shrink-0 drop-shadow-[0_0_14px_rgba(34,211,238,0.35)]" />
      {!collapsed && (
        <div className="leading-none">
          <div className="font-display text-[15px] font-semibold tracking-tight text-ink">Agent HQ</div>
          <div className="mt-1 font-mono text-[9px] uppercase tracking-[0.22em] text-muted">mission control</div>
        </div>
      )}
    </div>
  );
}
