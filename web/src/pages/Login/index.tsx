/**
 * /login — passcode login, or first-run "Set your passcode" (only accepted from this Mac / loopback).
 * On success returns to `?next=` (default /).
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, Eye, EyeOff, KeyRound, LockKeyhole, ShieldCheck } from 'lucide-react';
import { motion, useAnimationControls } from 'motion/react';
import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router';
import { AgentAvatar } from '@/components/AgentAvatar';
import { Button } from '@/components/Button';
import { ApiError, api } from '@/lib/api';
import { cn } from '@/lib/cn';
import { qk, useAuthStatus } from '@/lib/queries';
import { LogoMark } from '@/layout/Logo';
import { AGENT_PRESETS } from '@/theme/tokens';

function safeNext(raw: string | null): string {
  if (!raw || !raw.startsWith('/') || raw.startsWith('//') || raw.startsWith('/login')) return '/';
  return raw;
}

export default function Login() {
  const [params] = useSearchParams();
  const next = safeNext(params.get('next'));
  const status = useAuthStatus();
  const me = useQuery({ queryKey: qk.me, queryFn: api.auth.me, retry: false });

  useEffect(() => {
    document.title = 'Sign in · Agent HQ';
  }, []);

  if (me.isSuccess) return <Navigate to={next} replace />;

  return (
    <div className="relative min-h-dvh overflow-hidden">
      <div className="hq-backdrop" aria-hidden />
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-[38%] size-[900px] -translate-x-1/2 -translate-y-1/2 rounded-full opacity-60"
        style={{ background: 'radial-gradient(circle, rgba(34,211,238,0.10), rgba(167,139,250,0.06) 40%, transparent 70%)' }}
      />
      <div className="relative z-10 mx-auto grid min-h-dvh max-w-6xl items-center gap-6 px-4 py-6 md:grid-cols-[1.1fr_1fr] md:gap-12 md:px-8 md:py-10">
        <Hero />
        <div className="w-full max-w-md justify-self-center md:justify-self-end">
          {status.isPending ? (
            <CardShell>
              <div className="h-40 animate-breathe rounded-xl bg-white/[.04]" />
            </CardShell>
          ) : status.isError ? (
            <CardShell>
              <div className="space-y-2 text-center">
                <div className="font-display text-lg font-semibold">Can't reach the HQ server</div>
                <p className="text-sm text-muted">{(status.error as Error).message}</p>
                <Button size="sm" onClick={() => void status.refetch()}>
                  Retry
                </Button>
              </div>
            </CardShell>
          ) : status.data.configured ? (
            <LoginForm next={next} />
          ) : (
            <SetupForm next={next} loopback={status.data.loopback} />
          )}
        </div>
      </div>
    </div>
  );
}

function Hero() {
  const radius = 132;
  return (
    <div className="flex flex-col items-center text-center md:items-start md:text-left">
      <div className="relative mb-2 hidden size-[340px] md:block" aria-hidden>
        <Orbit radius={radius} />
      </div>
      <div className="relative mb-3 size-[176px] md:hidden" aria-hidden>
        <Orbit radius={66} small />
      </div>
      <div className="font-mono text-[10.5px] uppercase tracking-[0.28em] text-cyan-300/80">Local-first mission control</div>
      <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight text-ink md:mt-3 md:text-5xl">
        Agent <span className="bg-gradient-to-r from-cyan-300 via-sky-300 to-violet-300 bg-clip-text text-transparent">HQ</span>
      </h1>
      <p className="mt-3 max-w-md text-sm leading-relaxed text-muted md:text-[15px]">
        Ten agents find, verify and apply to AI/ML roles around the clock — only when the fact, eligibility, quality
        and scam gates pass.
      </p>
    </div>
  );
}

function Orbit({ radius, small }: { radius: number; small?: boolean }) {
  const n = AGENT_PRESETS.length;
  return (
    <div className="absolute inset-0 grid place-items-center">
      <div className="absolute rounded-full border border-white/[.07]" style={{ width: radius * 2, height: radius * 2 }} />
      <div
        className="absolute rounded-full border border-dashed border-cyan-300/15"
        style={{ width: radius * 1.35, height: radius * 1.35 }}
      />
      <div className="absolute animate-spin-slow" style={{ width: radius * 2, height: radius * 2 }}>
        {AGENT_PRESETS.map((a, i) => {
          const ang = (i / n) * Math.PI * 2 - Math.PI / 2;
          const x = radius + Math.cos(ang) * radius;
          const y = radius + Math.sin(ang) * radius;
          return (
            <div key={a.id} className="absolute" style={{ left: x, top: y, transform: 'translate(-50%, -50%)' }}>
              <div className="animate-spin-slow [animation-direction:reverse]">
                <AgentAvatar
                  agent={{ id: a.id, name: a.name, avatar: a.emoji, color: a.color }}
                  size={small ? 24 : 38}
                  working={i % 3 === 0}
                />
              </div>
            </div>
          );
        })}
      </div>
      <div className="relative">
        <span className="absolute inset-0 animate-pulse-ring rounded-2xl bg-cyan-400/25" />
        <LogoMark size={small ? 44 : 76} className="relative drop-shadow-[0_0_30px_rgba(34,211,238,0.5)]" />
      </div>
    </div>
  );
}

function CardShell({ children, title, subtitle, icon: Icon }: { children: ReactNode; title?: string; subtitle?: string; icon?: typeof KeyRound }) {
  return (
    <div className="glass relative rounded-3xl p-6 md:p-8" style={{ ['--glow' as string]: 'rgba(34,211,238,0.28)' }}>
      <span aria-hidden className="pointer-events-none absolute inset-x-10 top-0 h-px bg-gradient-to-r from-transparent via-cyan-300/70 to-transparent" />
      {title && (
        <div className="mb-6">
          {Icon && (
            <div className="mb-4 grid size-11 place-items-center rounded-xl border border-white/10 bg-white/[.05] shadow-[0_0_24px_-6px_rgba(34,211,238,0.6)]">
              <Icon className="size-5 text-cyan-300" aria-hidden />
            </div>
          )}
          <h2 className="font-display text-2xl font-semibold tracking-tight">{title}</h2>
          {subtitle && <p className="mt-1.5 text-sm text-muted">{subtitle}</p>}
        </div>
      )}
      {children}
      <div className="mt-6 flex items-center gap-2 border-t border-white/[.06] pt-4 text-[11px] text-faint">
        <ShieldCheck className="size-3.5 shrink-0" aria-hidden />
        scrypt-hashed passcode in .env · HttpOnly SameSite=Strict session · 30 days
      </div>
    </div>
  );
}

function PasscodeInput({
  value,
  onChange,
  label,
  autoFocus,
  autoComplete,
  invalid,
  id,
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  autoFocus?: boolean;
  autoComplete: string;
  invalid?: boolean;
  id: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <label className="block" htmlFor={id}>
      <span className="mb-1.5 block text-xs font-medium text-muted">{label}</span>
      <span
        className={cn(
          'flex h-12 items-center gap-2 rounded-xl border bg-black/20 px-3.5 transition-colors focus-within:border-cyan-300/60 focus-within:bg-black/30',
          invalid ? 'border-red-400/60' : 'border-white/10',
        )}
      >
        <LockKeyhole className="size-4 shrink-0 text-faint" aria-hidden />
        <input
          id={id}
          type={show ? 'text' : 'password'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoFocus={autoFocus}
          autoComplete={autoComplete}
          spellCheck={false}
          className="h-full min-w-0 flex-1 bg-transparent font-mono text-[15px] tracking-[0.12em] text-ink outline-none placeholder:text-faint"
          placeholder="••••••"
        />
        <button
          type="button"
          onClick={() => setShow((s) => !s)}
          className="grid size-8 place-items-center rounded-lg text-faint hover:text-ink"
          aria-label={show ? 'Hide passcode' : 'Show passcode'}
        >
          {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
        </button>
      </span>
    </label>
  );
}

function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 401) return 'Wrong passcode.';
    if (e.status === 429) return 'Too many attempts — wait a minute and try again.';
    if (e.status === 403) return 'Setup only works from this Mac. Open http://localhost:8765 on the Mac itself.';
    return e.message;
  }
  return e instanceof Error ? e.message : 'Something went wrong.';
}

function useFinish(next: string) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  return () => {
    qc.setQueryData(qk.me, { ok: true });
    navigate(next, { replace: true });
  };
}

function LoginForm({ next }: { next: string }) {
  const [pass, setPass] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const shake = useAnimationControls();
  const finish = useFinish(next);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!pass || busy) return;
    setBusy(true);
    setErr(null);
    try {
      await api.auth.login(pass);
      finish();
    } catch (ex) {
      setErr(errorText(ex));
      setPass('');
      void shake.start({ x: [0, -10, 9, -6, 4, 0], transition: { duration: 0.4 } });
    } finally {
      setBusy(false);
    }
  };

  return (
    <motion.div animate={shake}>
      <CardShell title="Welcome back" subtitle="Enter your passcode to open mission control." icon={KeyRound}>
        <form onSubmit={submit} className="space-y-4">
          <PasscodeInput id="passcode" value={pass} onChange={setPass} label="Passcode" autoFocus autoComplete="current-password" invalid={!!err} />
          {err && (
            <p role="alert" className="text-sm text-red-300">
              {err}
            </p>
          )}
          <Button type="submit" variant="primary" size="lg" className="w-full" loading={busy} iconRight={ArrowRight} disabled={!pass}>
            Unlock
          </Button>
        </form>
      </CardShell>
    </motion.div>
  );
}

function SetupForm({ next, loopback }: { next: string; loopback?: boolean }) {
  const [pass, setPass] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const finish = useFinish(next);
  const tooShort = pass.length > 0 && pass.length < 6;
  const mismatch = confirm.length > 0 && confirm !== pass;
  const remote = loopback === false;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy || pass.length < 6 || pass !== confirm) return;
    setBusy(true);
    setErr(null);
    try {
      await api.auth.setup(pass);
      await api.auth.login(pass);
      finish();
    } catch (ex) {
      setErr(errorText(ex));
    } finally {
      setBusy(false);
    }
  };

  return (
    <CardShell
      title="Set your passcode"
      subtitle="First run: choose a passcode (6+ characters). It's stored only as a scrypt hash in .env."
      icon={KeyRound}
    >
      {remote && (
        <div className="mb-4 rounded-xl border border-amber-300/25 bg-amber-300/[.06] px-3 py-2.5 text-sm text-amber-100/90">
          Setup only works from this Mac. Open <span className="font-mono">http://localhost:8765</span> on the Mac itself.
        </div>
      )}
      <form onSubmit={submit} className="space-y-4">
        <PasscodeInput
          id="new-passcode"
          value={pass}
          onChange={setPass}
          label="New passcode"
          autoFocus
          autoComplete="new-password"
          invalid={tooShort}
        />
        <PasscodeInput id="confirm-passcode" value={confirm} onChange={setConfirm} label="Confirm passcode" autoComplete="new-password" invalid={mismatch} />
        <div className="min-h-5 text-sm">
          {err ? (
            <span role="alert" className="text-red-300">
              {err}
            </span>
          ) : tooShort ? (
            <span className="text-amber-200/90">At least 6 characters.</span>
          ) : mismatch ? (
            <span className="text-amber-200/90">Passcodes don't match yet.</span>
          ) : null}
        </div>
        <Button
          type="submit"
          variant="primary"
          size="lg"
          className="w-full"
          loading={busy}
          iconRight={ArrowRight}
          disabled={remote || pass.length < 6 || pass !== confirm}
        >
          Set passcode & enter
        </Button>
      </form>
    </CardShell>
  );
}
