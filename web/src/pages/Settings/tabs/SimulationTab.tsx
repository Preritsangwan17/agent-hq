/** Simulation: sim on/off, speed, and a reset that purges simulated opportunities (legacy rows are never touched). */
import { FlaskConical, Gauge, RotateCcw, Sparkles, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { api } from '@/lib/api';
import { loadSnapshot, useOppList, useSettings } from '@/lib/store';
import { ConfirmButton } from '@/pages/Agents/formKit';
import { SettingRow, Slider, Toggle } from '../controls';
import { Callout, Section } from '../parts';
import { useSaver } from '../saver';

const SIM = '#38BDF8';
const SPEEDS = [0.25, 0.5, 1, 2, 4];

export function SimulationTab() {
  const s = useSettings();
  const { save } = useSaver();
  const opps = useOppList();
  const simCount = opps.filter((o) => o.is_simulated).length;
  const realCount = opps.length - simCount;
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const speed = Number(s.sim_speed) || 1;

  return (
    <div className="space-y-5">
      <Section
        kicker="Phase (a)"
        title="Simulated agents"
        icon={FlaskConical}
        color={SIM}
        description="The simulator drives agents whose adapter is `sim` with plausible, clearly tagged work so the dashboard can be exercised without touching the internet. Simulated items carry a SIM tag and only ever reach the mock mailbox."
      >
        <SettingRow
          title="Run the simulator"
          htmlFor="sim-on"
          description={s.sim_enabled ? 'Scout invents a few plausible roles every minute; the rest of the team works them.' : 'Off — sim-adapter agents stay idle. Real pipeline agents are unaffected.'}
          control={<Toggle id="sim-on" label="Run the simulator" checked={!!s.sim_enabled} onChange={(v) => save({ sim_enabled: v })} color={SIM} size="lg" />}
        />
        <SettingRow icon={Gauge} color={SIM} title="Speed" control={<span className="font-display text-xl font-semibold text-ink tabular">{speed}×</span>}>
          <Slider
            aria-label="Simulation speed"
            value={SPEEDS.indexOf(speed) >= 0 ? SPEEDS.indexOf(speed) : 2}
            min={0}
            max={SPEEDS.length - 1}
            step={1}
            color={SIM}
            format={(i) => `${SPEEDS[i]}×`}
            onChange={(i) => save({ sim_speed: SPEEDS[i] }, 250)}
            marks={SPEEDS.map((v, i) => ({ value: i, label: `${v}×` }))}
          />
        </SettingRow>
      </Section>

      <Section kicker="Clean up" title="Reset simulation" icon={RotateCcw} color="#FB923C" rows={false}>
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <p className="max-w-lg text-[13px] leading-relaxed text-muted">
            Deletes the <b className="text-ink">{simCount}</b> simulated opportunities with their tasks, needs and mock mail. The{' '}
            <b className="text-ink">{realCount}</b> real and legacy items stay exactly as they are.
          </p>
          <ConfirmButton
            icon={Trash2}
            color="#FB923C"
            confirmLabel={`Delete ${simCount} simulated items?`}
            disabled={simCount === 0}
            onConfirm={async () => {
              setError(null);
              try {
                const r = await api.simReset();
                setResult(`Purged ${r.purged ?? 0} simulated opportunities.`);
                await loadSnapshot();
              } catch (e) {
                setError(e instanceof Error ? e.message : 'Reset failed');
              }
            }}
          >
            Reset simulation
          </ConfirmButton>
        </div>
        {result && <p className="mt-3 text-xs text-emerald-300">{result}</p>}
        {error && <p className="mt-3 text-xs text-red-300">{error}</p>}
      </Section>

      <Callout icon={Sparkles} color={SIM} title="Real work is never simulated">
        Agents on real adapters (local models, Claude, scripts) ignore this switch, and legacy applications stay frozen until you
        confirm what was sent.
      </Callout>
    </div>
  );
}
