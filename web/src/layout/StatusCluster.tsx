/** Header status widgets: mode badge, SIM indicator, Claude budget gauge, worker/SSE connection dot. */
import { FlaskConical, ShieldCheck, Snowflake, UserCheck } from 'lucide-react';
import { Badge } from '@/components/Badge';
import { StatusDot } from '@/components/StatusDot';
import { Tooltip } from '@/components/Tooltip';
import { cn } from '@/lib/cn';
import { formatCompact, formatRelative, formatUSD } from '@/lib/format';
import { useNow } from '@/lib/hooks';
import { useHQ } from '@/lib/store';
import { hqStream } from '@/lib/stream';
import { MODE_META, colors } from '@/theme/tokens';

export function ModeBadge({ compact }: { compact?: boolean }) {
  const mode = useHQ((s) => s.settings.mode);
  const autonomy = useHQ((s) => s.settings.autonomy);
  const frozen = useHQ((s) => s.settings.freeze_outbound);
  const meta = MODE_META[mode] ?? MODE_META.dry_run;
  return (
    <div className="flex items-center gap-1.5">
      <Tooltip content={<><b>{meta.label}</b> — {meta.hint}<div className="mt-1 text-muted">Changed only through the go-live checklist (Settings › Autonomy &amp; Mode).</div></>} side="bottom">
        <Badge color={meta.color} icon={ShieldCheck} size={compact ? 'sm' : 'md'} mono>
          {meta.label}
        </Badge>
      </Tooltip>
      {autonomy === 'approve_first' && !compact && (
        <Tooltip content="Every application waits for your approval in Needs Prerit." side="bottom">
          <Badge color="#A78BFA" icon={UserCheck} size="md" mono>
            APPROVE-FIRST
          </Badge>
        </Tooltip>
      )}
      {frozen && (
        <Tooltip content="Outbound frozen: nothing is sent or submitted until unfrozen." side="bottom">
          <Badge color="#93C5FD" icon={Snowflake} size={compact ? 'sm' : 'md'} mono>
            {compact ? 'FROZEN' : 'OUTBOUND FROZEN'}
          </Badge>
        </Tooltip>
      )}
    </div>
  );
}

export function SimIndicator() {
  const on = useHQ((s) => !!s.settings.sim_enabled);
  const speed = useHQ((s) => Number(s.settings.sim_speed) || 1);
  if (!on) return null;
  return (
    <Tooltip content={`Simulation running at ${speed}× — simulated rows carry a SIM tag and are fictional.`} side="bottom">
      <span className="inline-flex h-6 items-center gap-1 rounded-md border border-dashed border-cyan-300/40 bg-cyan-300/[.06] px-1.5 font-mono text-[11px] font-semibold tracking-wider text-cyan-200/90">
        <FlaskConical className="size-3" aria-hidden />
        SIM {speed}×
      </span>
    </Tooltip>
  );
}

export function BudgetGauge({ compact }: { compact?: boolean }) {
  const stats = useHQ((s) => s.stats);
  const cap = useHQ((s) => s.settings.claude_daily_call_cap);
  const settingsBudget = useHQ((s) => s.settings.claude_daily_budget_usd);
  const spent = stats?.claude_cost_today_usd ?? 0;
  const budget = stats?.claude_budget_usd || settingsBudget || 5;
  const frac = Math.max(0, Math.min(1, spent / budget));
  const color = frac >= 0.85 ? colors.warn : '#E879F9';
  const r = 9;
  const circ = 2 * Math.PI * r;
  return (
    <Tooltip
      side="bottom"
      content={
        <div className="space-y-0.5">
          <div className="font-medium">Claude today</div>
          <div>
            {formatUSD(spent)} of {formatUSD(budget)} budget ({Math.round(frac * 100)}%)
          </div>
          <div className="text-muted">
            {stats?.claude_calls_today ?? 0} of {cap} calls · local tokens {formatCompact(stats?.local_tokens_today ?? 0)}
          </div>
          <div className="text-muted">Over budget → Claude tasks defer to midnight IST; local work continues.</div>
        </div>
      }
    >
      <span className="inline-flex items-center gap-2">
        <svg width="24" height="24" viewBox="0 0 24 24" className="-rotate-90" aria-hidden>
          <circle cx="12" cy="12" r={r} fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="3" />
          <circle
            cx="12"
            cy="12"
            r={r}
            fill="none"
            stroke={color}
            strokeWidth="3"
            strokeLinecap="round"
            strokeDasharray={`${circ * frac} ${circ}`}
            style={{ filter: `drop-shadow(0 0 4px ${color})` }}
          />
        </svg>
        {!compact && (
          <span className="leading-tight">
            <span className="block font-display text-[13px] font-semibold tabular text-ink">
              {formatUSD(spent)}
              <span className="font-normal text-muted"> / {formatUSD(budget, 0)}</span>
            </span>
            <span className="block text-[10px] uppercase tracking-[0.12em] text-muted">Claude today</span>
          </span>
        )}
      </span>
    </Tooltip>
  );
}

export function ConnectionIndicator({ showLabel = true }: { showLabel?: boolean }) {
  const conn = useHQ((s) => s.conn);
  const worker = useHQ((s) => s.worker);
  const now = useNow(5000);
  const hbAge = worker.heartbeatAt ? now - Date.parse(worker.heartbeatAt) : null;
  const workerOk = worker.alive !== false && (hbAge == null || hbAge < 45_000);

  let color: string = colors.ok;
  let label = 'Live';
  let pulse = false;
  if (conn.sse === 'connecting' || conn.sse === 'idle') {
    color = colors.warn;
    label = 'Connecting';
    pulse = true;
  } else if (conn.sse === 'reconnecting') {
    color = colors.warn;
    label = conn.attempts > 1 ? `Reconnecting · ${conn.attempts}` : 'Reconnecting';
    pulse = true;
  } else if (conn.sse === 'closed') {
    color = colors.faint;
    label = 'Offline';
  } else if (!workerOk) {
    color = colors.danger;
    label = 'Worker down';
    pulse = true;
  }

  return (
    <Tooltip
      side="bottom"
      content={
        <div className="space-y-0.5">
          <div>
            Stream: <b>{conn.sse}</b>
            {conn.lastMessageAt ? ` · last event ${formatRelative(new Date(conn.lastMessageAt).toISOString(), now)}` : ''}
          </div>
          <div>
            Worker: <b>{worker.alive === false ? 'down' : worker.alive ? 'alive' : 'unknown'}</b>
            {worker.heartbeatAt ? ` · heartbeat ${formatRelative(worker.heartbeatAt, now)}` : ''}
          </div>
          {worker.version && <div className="text-muted">v{worker.version}</div>}
          {conn.lastError && conn.sse !== 'open' && <div className="text-muted">Last error: {conn.lastError}</div>}
          <div className="text-muted">Click to reconnect now.</div>
        </div>
      }
    >
      <button
        type="button"
        onClick={() => hqStream.reconnect()}
        className={cn('inline-flex h-8 items-center gap-2 rounded-lg px-2 text-xs text-muted transition-colors hover:bg-white/[.05] hover:text-ink')}
        aria-label={`Connection: ${label}`}
      >
        <StatusDot color={color} pulse={pulse || label === 'Live'} />
        {showLabel && <span className="font-medium">{label}</span>}
      </button>
    </Tooltip>
  );
}
