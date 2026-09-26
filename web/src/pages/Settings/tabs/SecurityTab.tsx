/** Security: passcode change (loopback only), network exposure, secrets held in .env (names only), audit log. */
import { useMutation, useQuery } from '@tanstack/react-query';
import { History, KeyRound, LogOut, Network, ShieldAlert, ShieldCheck, Wifi, WifiOff } from 'lucide-react';
import { useState } from 'react';
import { Badge } from '@/components/Badge';
import { Button } from '@/components/Button';
import { ApiError, api } from '@/lib/api';
import { formatDateTimeIST } from '@/lib/format';
import { Field, TextInput } from '@/pages/Agents/formKit';
import { SettingRow } from '../controls';
import { Callout, Code, Section } from '../parts';

const SEC = '#A3E635';

export function SecurityTab() {
  const sec = useQuery({ queryKey: ['security'], queryFn: api.security });
  const s = sec.data;
  return (
    <div className="space-y-5">
      <PasscodeSection loopback={s?.loopback ?? false} />

      <Section kicker="Exposure" title="Network" icon={Network} color={SEC}>
        <SettingRow
          icon={s?.lan ? Wifi : WifiOff}
          color={s?.lan ? '#FBBF24' : SEC}
          title={s?.lan ? 'Reachable on your Wi-Fi (HQ_LAN=1)' : 'This Mac only (127.0.0.1)'}
          description={
            s?.lan
              ? 'Phones on the same network can open HQ after logging in. Allowed host names are listed below; anything else gets 421.'
              : 'Set HQ_LAN=1 and HQ_ALLOWED_HOSTS in .env and restart to reach HQ from your phone. Go-live and setup stay loopback-only either way.'
          }
          control={<Badge color={s?.lan ? '#FBBF24' : SEC}>{s?.lan ? 'LAN' : 'loopback'}</Badge>}
        />
        <SettingRow
          icon={ShieldCheck}
          color={SEC}
          title="Every request is authenticated"
          description={`Session cookie is HttpOnly, SameSite=Strict and lasts ${s?.session_days ?? 30} days. Changes also need an allowed Origin and the X-HQ header, which blocks DNS rebinding and cross-site requests. Login is limited to 5 tries a minute.`}
        >
          <div className="flex flex-wrap gap-1.5">
            {(s?.allowed_hosts ?? []).map((h) => (
              <Badge key={h} mono size="sm" color="#8B95A7">
                {h}
              </Badge>
            ))}
          </div>
        </SettingRow>
        <SettingRow
          icon={ShieldAlert}
          color="#22D3EE"
          title="Forced dry run"
          description="While HQ_FORCE_DRY_RUN is on, the worker refuses to start if a Gmail token with send permission exists."
          control={<Badge color={s?.force_dry_run ? '#22D3EE' : '#FBBF24'}>{s?.force_dry_run ? 'on' : 'off'}</Badge>}
        />
      </Section>

      <Section kicker=".env" title="Secrets on this Mac" icon={KeyRound} color="#FBBF24" rows={false}
        description="Secrets live only in .env (mode 600, git-ignored). The UI shows which ones exist, never their values; logs and anything sent to Claude pass through a redaction filter.">
        <div className="flex flex-wrap gap-1.5">
          {['HQ_PASSCODE_HASH', 'HQ_SESSION_SECRET', 'HQ_GMAIL_CLIENT_ID', 'HQ_GMAIL_CLIENT_SECRET', 'HQ_GMAIL_REFRESH_TOKEN'].map((k) => {
            const on = s?.secrets_present.includes(k);
            return (
              <Badge key={k} mono color={on ? '#34D399' : '#5B6577'}>
                {k} {on ? '✓' : '—'}
              </Badge>
            );
          })}
        </div>
      </Section>

      <AuditSection />

      <Section kicker="This browser" title="Session" icon={LogOut} color="#8B95A7" rows={false}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-[13px] text-muted">Log out here. Other devices stay logged in until their cookie expires or the session secret changes.</p>
          <Button
            icon={LogOut}
            onClick={async () => {
              await api.auth.logout();
              window.location.assign('/login');
            }}
          >
            Log out
          </Button>
        </div>
      </Section>
    </div>
  );
}

function PasscodeSection({ loopback }: { loopback: boolean }) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [again, setAgain] = useState('');
  const m = useMutation({ mutationFn: () => api.changePasscode(current, next) });
  const mismatch = again.length > 0 && again !== next;
  const tooShort = next.length > 0 && next.length < 6;
  const err = m.error instanceof ApiError ? m.error.message : m.error ? String(m.error) : null;
  return (
    <Section kicker="Access" title="Passcode" icon={KeyRound} color={SEC} rows={false}
      description="Stored only as an scrypt hash in .env. Changing it works from this Mac only.">
      {!loopback ? (
        <Callout icon={ShieldAlert} color="#FBBF24">
          Open HQ at <Code>http://localhost:8765</Code> on the Mac to change the passcode.
        </Callout>
      ) : (
        <form
          className="grid gap-3 md:grid-cols-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!mismatch && !tooShort && current && next) {
              m.mutate(undefined, {
                onSuccess: () => {
                  setCurrent('');
                  setNext('');
                  setAgain('');
                },
              });
            }
          }}
        >
          <Field label="Current" htmlFor="pc-current">
            <TextInput id="pc-current" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
          </Field>
          <Field label="New" htmlFor="pc-new" error={tooShort ? 'At least 6 characters' : undefined}>
            <TextInput id="pc-new" type="password" autoComplete="new-password" value={next} invalid={tooShort} onChange={(e) => setNext(e.target.value)} />
          </Field>
          <Field label="Repeat" htmlFor="pc-again" error={mismatch ? "Doesn't match" : undefined}>
            <TextInput id="pc-again" type="password" autoComplete="new-password" value={again} invalid={mismatch} onChange={(e) => setAgain(e.target.value)} />
          </Field>
          <div className="flex items-center gap-3 md:col-span-3">
            <Button type="submit" variant="primary" loading={m.isPending} disabled={!current || !next || mismatch || tooShort}>
              Change passcode
            </Button>
            {m.isSuccess && <span className="text-xs text-emerald-300">Passcode changed.</span>}
            {err && <span className="text-xs text-red-300">{err}</span>}
          </div>
        </form>
      )}
    </Section>
  );
}

function AuditSection() {
  const q = useQuery({ queryKey: ['audit'], queryFn: () => api.audit({ limit: 40 }), refetchInterval: 30_000 });
  const items = q.data?.items ?? [];
  return (
    <Section kicker="Who did what" title="Audit log" icon={History} color="#818CF8" rows={false}
      description="Every change you make (settings, pauses, stage overrides, profile edits, logins) is recorded with the time and address. Personal values are never written here.">
      {items.length === 0 ? (
        <p className="text-xs text-faint">{q.isLoading ? 'Loading…' : 'Nothing recorded yet.'}</p>
      ) : (
        <div className="-mx-2 max-h-[360px] overflow-y-auto">
          <table className="w-full min-w-[520px] text-left text-[12.5px]">
            <thead className="sticky top-0 bg-[#0D1422] text-[10.5px] uppercase tracking-[0.12em] text-faint">
              <tr>
                <th className="px-2 py-1.5 font-medium">When (IST)</th>
                <th className="px-2 py-1.5 font-medium">Action</th>
                <th className="px-2 py-1.5 font-medium">Target</th>
                <th className="px-2 py-1.5 font-medium">From</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[.05]">
              {items.map((a) => (
                <tr key={a.id}>
                  <td className="px-2 py-1.5 whitespace-nowrap text-muted tabular">{formatDateTimeIST(a.ts)}</td>
                  <td className="px-2 py-1.5 font-mono text-[11.5px] text-ink/90">{a.action}</td>
                  <td className="max-w-[200px] truncate px-2 py-1.5 text-muted">{a.target ?? '—'}</td>
                  <td className="px-2 py-1.5 font-mono text-[11px] text-faint">{a.remote_addr ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}
