/** Schedules: quiet hours (24 h dial in IST), keep-awake, and a read-only overview of agent schedules. */
import { ArrowRight, BatteryCharging, CalendarClock, Clock3, MoonStar, Sunrise, Sunset } from 'lucide-react';
import { Link } from 'react-router';
import { AgentAvatar } from '@/components/AgentAvatar';
import { Badge } from '@/components/Badge';
import { cn } from '@/lib/cn';
import { useNow } from '@/lib/hooks';
import { useAgentsList, useSettings } from '@/lib/store';
import type { QuietHours } from '@/lib/types';
import { withAlpha } from '@/theme/tokens';
import { describeSchedule } from '@/pages/Agents/schedule';
import { SettingRow, Toggle } from '../controls';
import { Section } from '../parts';
import { useSaver } from '../saver';

const QUIET = '#818CF8';
const IST_OFFSET_MIN = 330;

const toMin = (hhmm: string) => {
  const [h, m] = hhmm.split(':').map(Number);
  return (h || 0) * 60 + (m || 0);
};
const validHHMM = (v: string) => /^([01]\d|2[0-3]):[0-5]\d$/.test(v);

function span(q: QuietHours): number {
  const a = toMin(q.start);
  const b = toMin(q.end);
  return b > a ? b - a : b + 1440 - a;
}

function inWindow(q: QuietHours, m: number): boolean {
  const a = toMin(q.start);
  const b = toMin(q.end);
  return a <= b ? m >= a && m < b : m >= a || m < b;
}

export function SchedulesTab() {
  const s = useSettings();
  const { save } = useSaver();
  const q: QuietHours = { enabled: false, start: '23:00', end: '07:00', ...(s.quiet_hours as Partial<QuietHours> | undefined) };
  const now = useNow(30_000);
  const nowMin = Math.floor((now / 60000 + IST_OFFSET_MIN) % 1440);
  const quietNow = q.enabled && inWindow(q, nowMin);
  const setQ = (p: Partial<QuietHours>) => save({ quiet_hours: { ...q, ...p } });
  const len = span(q);

  return (
    <div className="space-y-5">
      <Section
        kicker="Usability"
        title="Quiet hours"
        icon={MoonStar}
        color={QUIET}
        rows={false}
        right={
          quietNow ? (
            <Badge color={QUIET} icon={MoonStar} size="md">
              Quiet now
            </Badge>
          ) : undefined
        }
        description="A nightly window when the Mac should stay calm. From phase (b) the model manager uses it to drop to a small memory pool and hold non-urgent work. Times are IST."
      >
        <div className="grid items-center gap-6 md:grid-cols-[auto_minmax(0,1fr)]">
          <QuietDial q={q} nowMin={nowMin} />
          <div className="min-w-0 divide-y divide-white/[.06]">
            <SettingRow
              title="Enable quiet hours"
              phase="b"
              htmlFor="quiet-on"
              description={q.enabled ? `${Math.floor(len / 60)} h ${len % 60 ? `${len % 60} min ` : ''}every night.` : 'Off — agents work around the clock.'}
              control={<Toggle id="quiet-on" checked={q.enabled} onChange={(v) => setQ({ enabled: v })} color={QUIET} size="lg" />}
            />
            <div className="grid gap-3 py-4 sm:grid-cols-2">
              <TimeInput label="Starts" icon={Sunset} value={q.start} onCommit={(v) => setQ({ start: v })} disabled={!q.enabled} />
              <TimeInput label="Ends" icon={Sunrise} value={q.end} onCommit={(v) => setQ({ end: v })} disabled={!q.enabled} />
            </div>
          </div>
        </div>
      </Section>

      <Section kicker="Power" title="Keep this Mac awake" icon={BatteryCharging} color="#A3E635">
        <SettingRow
          title="Hold caffeinate while HQ runs"
          phase="live"
          htmlFor="keep-awake"
          description="Stops idle sleep so agents keep working with the lid open; the display can still sleep. Released when HQ stops."
          control={
            <Toggle id="keep-awake" checked={!!s.keep_awake} onChange={(v) => save({ keep_awake: v })} color="#A3E635" size="lg" />
          }
        />
      </Section>

      <AgentSchedules />
    </div>
  );
}

function TimeInput({
  label,
  icon: Icon,
  value,
  onCommit,
  disabled,
}: {
  label: string;
  icon: typeof Sunset;
  value: string;
  onCommit: (v: string) => void;
  disabled?: boolean;
}) {
  return (
    <label className={cn('flex min-w-0 items-center gap-3 rounded-xl border border-white/10 bg-white/[.03] px-3 py-2', disabled && 'opacity-50')}>
      <Icon className="size-4 shrink-0" style={{ color: QUIET }} aria-hidden />
      <span className="text-[13px] text-muted">{label}</span>
      <input
        type="time"
        value={value}
        disabled={disabled}
        onChange={(e) => {
          if (validHHMM(e.target.value)) onCommit(e.target.value);
        }}
        className="ml-auto min-w-0 bg-transparent text-right font-display text-lg font-semibold text-ink tabular outline-none"
        aria-label={`Quiet hours ${label.toLowerCase()} (IST)`}
      />
      <span className="text-[10px] font-medium uppercase tracking-wider text-faint">IST</span>
    </label>
  );
}

/** 24 h dial: midnight at the top, quiet window as a glowing arc, current IST time as a dot. */
function QuietDial({ q, nowMin }: { q: QuietHours; nowMin: number }) {
  const size = 188;
  const c = size / 2;
  const r = 72;
  const pt = (m: number, rr = r) => {
    const a = (m / 1440) * Math.PI * 2 - Math.PI / 2;
    return [c + rr * Math.cos(a), c + rr * Math.sin(a)] as const;
  };
  const a = toMin(q.start);
  const len = span(q);
  const [sx, sy] = pt(a);
  const [ex, ey] = pt(a + len);
  const arc = `M ${sx} ${sy} A ${r} ${r} 0 ${len > 720 ? 1 : 0} 1 ${ex} ${ey}`;
  const [nx, ny] = pt(nowMin);
  const color = q.enabled ? QUIET : 'rgba(255,255,255,0.22)';
  const hours = Math.floor(len / 60);
  const mins = len % 60;
  return (
    <div className="relative mx-auto size-[188px] md:mx-0" role="img" aria-label={`Quiet hours ${q.enabled ? `${q.start} to ${q.end} IST` : 'off'}`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden>
        <defs>
          <radialGradient id="dial-bg" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor={withAlpha(QUIET, 0.1)} />
            <stop offset="100%" stopColor="transparent" />
          </radialGradient>
        </defs>
        <circle cx={c} cy={c} r={r + 16} fill="url(#dial-bg)" />
        <circle cx={c} cy={c} r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="12" />
        {Array.from({ length: 24 }, (_, h) => {
          const [x1, y1] = pt(h * 60, r + 10);
          const [x2, y2] = pt(h * 60, r + (h % 6 === 0 ? 15 : 12));
          return <line key={h} x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgba(255,255,255,0.18)" strokeWidth={h % 6 === 0 ? 1.5 : 1} />;
        })}
        {len > 0 && (
          <path d={arc} fill="none" stroke={color} strokeWidth="12" strokeLinecap="round" style={q.enabled ? { filter: `drop-shadow(0 0 8px ${withAlpha(QUIET, 0.8)})` } : undefined} />
        )}
        {[0, 6, 12, 18].map((h) => {
          const [x, y] = pt(h * 60, r - 22);
          return (
            <text key={h} x={x} y={y} textAnchor="middle" dominantBaseline="central" className="fill-[#5B6577] font-mono text-[10px]">
              {String(h).padStart(2, '0')}
            </text>
          );
        })}
        <circle cx={nx} cy={ny} r="5" fill="#fff" style={{ filter: 'drop-shadow(0 0 6px rgba(255,255,255,0.9))' }} />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">
        <div>
          <div className="font-display text-2xl font-semibold text-ink tabular">{q.enabled ? `${hours}h${mins ? ` ${mins}m` : ''}` : 'Off'}</div>
          <div className="text-[11px] text-muted">{q.enabled ? `${q.start} → ${q.end}` : 'no quiet window'}</div>
        </div>
      </div>
    </div>
  );
}

function AgentSchedules() {
  const agents = useAgentsList();
  const scheduled = agents.filter((a) => a.schedule?.mode !== 'on_demand');
  return (
    <Section
      kicker="Agents"
      title="Agent schedules"
      icon={CalendarClock}
      color="#22D3EE"
      right={
        <Link to="/agents" className="inline-flex items-center gap-1 text-xs font-medium text-cyan-300 hover:text-cyan-200">
          Edit in Agents <ArrowRight className="size-3.5" aria-hidden />
        </Link>
      }
      description={`${scheduled.length} of ${agents.length} agents run on a timer; the rest wake up when work arrives. Missed runs are coalesced, never replayed in a burst.`}
      rows={false}
    >
      <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {agents.map((a) => {
          const timed = a.schedule?.mode !== 'on_demand';
          return (
            <li key={a.id} className="flex min-w-0 items-center gap-3 rounded-xl border border-white/[.06] bg-white/[.02] px-3 py-2.5">
              <AgentAvatar agent={a} size="sm" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] font-medium text-ink">{a.name}</div>
                <div className={cn('flex items-center gap-1 truncate text-xs', timed ? 'text-ink/80' : 'text-faint')}>
                  {timed && <Clock3 className="size-3 shrink-0" style={{ color: a.color }} aria-hidden />}
                  <span className="truncate">{describeSchedule(a.schedule)}</span>
                </div>
              </div>
              {!a.enabled && (
                <Badge color="#5B6577" size="xs">
                  off
                </Badge>
              )}
            </li>
          );
        })}
      </ul>
    </Section>
  );
}
