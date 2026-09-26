/** Boot / loading / unreachable-server screens and the lazy-page fallback. */
import { RefreshCw, ServerCrash } from 'lucide-react';
import { Button } from '@/components/Button';
import { cn } from '@/lib/cn';
import { LogoMark } from './Logo';

export interface BootScreenProps {
  label?: string;
  error?: string | null;
  /** the server answered but failed (vs. not answering at all) */
  serverError?: boolean;
  onRetry?: () => void;
  /** render inside the shell instead of full-screen */
  inline?: boolean;
}

export function BootScreen({ label = 'Starting Agent HQ…', error, serverError, onRetry, inline }: BootScreenProps) {
  return (
    <div className={cn('grid place-items-center', inline ? 'min-h-[60vh]' : 'min-h-dvh')}>
      {!inline && <div className="hq-backdrop" aria-hidden />}
      <div className="relative flex flex-col items-center gap-5 text-center">
        <div className="relative">
          <span className="absolute inset-0 animate-pulse-ring rounded-2xl bg-cyan-400/30" aria-hidden />
          <LogoMark size={56} className="relative drop-shadow-[0_0_24px_rgba(34,211,238,0.45)]" />
        </div>
        {error ? (
          <>
            <div className="flex items-center gap-2 font-display text-lg font-semibold text-ink">
              <ServerCrash className="size-5 text-danger" aria-hidden />
              {serverError ? 'HQ hit an error' : 'HQ server unreachable'}
            </div>
            <p className="max-w-sm text-sm text-muted">{error}</p>
            {serverError ? (
              <p className="max-w-sm text-xs text-faint">
                The server is running but this failed. Details are in{' '}
                <code className="rounded bg-white/5 px-1 font-mono text-ink/80">data/logs/api.log</code> — this page retries
                automatically.
              </p>
            ) : (
              <p className="max-w-sm text-xs text-faint">
                Start it with <code className="rounded bg-white/5 px-1 font-mono text-ink/80">./start.sh</code> — this page
                retries automatically.
              </p>
            )}
            {onRetry && (
              <Button icon={RefreshCw} onClick={onRetry} size="sm">
                Retry now
              </Button>
            )}
          </>
        ) : (
          <div className="font-mono text-xs uppercase tracking-[0.2em] text-muted">{label}</div>
        )}
      </div>
    </div>
  );
}

export function PageFallback() {
  return (
    <div className="space-y-4" aria-busy>
      <div className="h-8 w-56 animate-breathe rounded-lg bg-white/[.05]" />
      <div className="grid gap-4 md:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-28 animate-breathe rounded-2xl bg-white/[.04]" style={{ animationDelay: `${i * 0.15}s` }} />
        ))}
      </div>
      <div className="h-72 animate-breathe rounded-2xl bg-white/[.03]" />
    </div>
  );
}
