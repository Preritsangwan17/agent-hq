/** Schedule + concurrency editor shared by the edit drawer and the Add Agent wizard. */
import { CalendarClock, Clock3, Hand } from 'lucide-react';
import type { AgentSchedule } from '@/lib/types';
import { Field, Segmented, Stepper, TextInput } from './formKit';
import { describeCron, isValidCron } from './schedule';

export function ScheduleEditor({
  value,
  onChange,
  schedulable,
  color = '#22D3EE',
}: {
  value: AgentSchedule;
  onChange: (s: AgentSchedule) => void;
  /** false when none of the agent's capabilities can run on a timer */
  schedulable: boolean;
  color?: string;
}) {
  const cronOk = value.mode !== 'cron' || isValidCron(value.cron ?? '');
  return (
    <div className="space-y-3">
      <Segmented<AgentSchedule['mode']>
        label="Schedule mode"
        value={value.mode}
        color={color}
        full
        onChange={(mode) =>
          onChange(mode === 'interval' ? { mode, minutes: value.minutes ?? 30 } : mode === 'cron' ? { mode, cron: value.cron ?? '30 7 * * *' } : { mode })
        }
        options={[
          { value: 'on_demand', label: 'On demand', icon: Hand },
          { value: 'interval', label: 'Every…', icon: Clock3, disabled: !schedulable },
          { value: 'cron', label: 'Cron', icon: CalendarClock, disabled: !schedulable },
        ]}
      />
      {!schedulable && (
        <p className="text-xs text-faint">Timers need a schedulable capability (discovery, inbox poll or daily review); this agent wakes up when work arrives.</p>
      )}
      {value.mode === 'interval' && (
        <Field label="Interval" hint="Missed runs are coalesced into one.">
          <Stepper label="Minutes between runs" value={value.minutes ?? 30} min={1} max={10080} step={5} onCommit={(m) => onChange({ mode: 'interval', minutes: m })} suffix="min" color={color} width={6} />
        </Field>
      )}
      {value.mode === 'cron' && (
        <Field label="Cron (IST)" htmlFor="cron-expr" error={cronOk ? undefined : 'Five fields: minute hour day month weekday'} hint={cronOk ? describeCron(value.cron) : undefined}>
          <TextInput id="cron-expr" mono value={value.cron ?? ''} invalid={!cronOk} onChange={(e) => onChange({ mode: 'cron', cron: e.target.value })} placeholder="30 7 * * *" />
        </Field>
      )}
    </div>
  );
}
