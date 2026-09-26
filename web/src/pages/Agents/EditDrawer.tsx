/** Edit an agent's identity, model, concurrency and schedule (rewrites its YAML; hot reload applies it). */
import { Save } from 'lucide-react';
import { useEffect, useId, useState } from 'react';
import { AgentAvatar, Button } from '@/components';
import { patchAgent } from '@/lib/store';
import type { Agent, AgentSchedule } from '@/lib/types';
import { AGENT_PALETTE } from '@/theme/tokens';
import { CloseButton, Drawer, Field, Stepper, TextInput } from './formKit';
import { ScheduleEditor } from './ScheduleEditor';
import { SCHEDULABLE_FALLBACK } from './schedule';

export function EditDrawer({ agent, onClose }: { agent: Agent | null; onClose: () => void }) {
  const titleId = useId();
  return (
    <Drawer open={!!agent} onClose={onClose} labelledBy={titleId} glow={agent?.color}>
      {agent && <EditBody key={agent.id} agent={agent} onClose={onClose} titleId={titleId} />}
    </Drawer>
  );
}

function EditBody({ agent, onClose, titleId }: { agent: Agent; onClose: () => void; titleId: string }) {
  const [name, setName] = useState(agent.name);
  const [avatar, setAvatar] = useState(agent.avatar);
  const [color, setColor] = useState(agent.color);
  const [model, setModel] = useState(agent.model ?? '');
  const [concurrency, setConcurrency] = useState(agent.concurrency);
  const [schedule, setSchedule] = useState<AgentSchedule>(agent.schedule);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => setErr(null), [name, avatar, color, model, concurrency, schedule]);

  const schedulable = agent.capabilities.some((c) => SCHEDULABLE_FALLBACK.includes(c));
  const modelOk = model === '' || /^(auto|(mlx|ollama|lmstudio|llamacpp|xai|sim|openai):.+)$/.test(model);
  const preview = { ...agent, name, avatar, color };

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      const patch: Parameters<typeof patchAgent>[1] = {};
      if (name !== agent.name) patch.name = name;
      if (avatar !== agent.avatar) patch.avatar = avatar;
      if (color !== agent.color) patch.color = color;
      if ((model || null) !== agent.model) patch.model = model || null;
      if (concurrency !== agent.concurrency) patch.concurrency = concurrency;
      if (JSON.stringify(schedule) !== JSON.stringify(agent.schedule)) patch.schedule = schedule;
      if (Object.keys(patch).length) await patchAgent(agent.id, patch);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="flex items-center gap-3 border-b border-white/[.06] px-5 py-4">
        <AgentAvatar agent={preview} size="md" />
        <div className="min-w-0 flex-1">
          <h2 id={titleId} className="truncate font-display text-lg font-semibold text-ink">
            Edit {agent.name}
          </h2>
          <p className="font-mono text-[11px] text-faint">agents/{agent.id}.yaml</p>
        </div>
        <CloseButton onClick={onClose} />
      </div>
      <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5">
        <div className="grid grid-cols-[1fr_88px] gap-3">
          <Field label="Name" htmlFor="ed-name">
            <TextInput id="ed-name" value={name} maxLength={40} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Avatar" htmlFor="ed-avatar">
            <TextInput id="ed-avatar" value={avatar} maxLength={40} onChange={(e) => setAvatar(e.target.value)} className="text-center" />
          </Field>
        </div>
        <Field label="Colour">
          <div className="flex flex-wrap gap-1.5">
            {AGENT_PALETTE.map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setColor(c)}
                aria-label={`Colour ${c}`}
                aria-pressed={color.toLowerCase() === c.toLowerCase()}
                className="size-7 rounded-lg border-2 transition-transform hover:scale-110"
                style={{ backgroundColor: c, borderColor: color.toLowerCase() === c.toLowerCase() ? '#fff' : 'transparent', boxShadow: `0 0 10px -2px ${c}` }}
              />
            ))}
          </div>
        </Field>
        <Field
          label="Model"
          htmlFor="ed-model"
          error={modelOk ? undefined : "Use 'auto' or runtime:name, e.g. mlx:mlx-community/Qwen3-4B-Instruct-2507-4bit"}
          hint="Blank = adapter default · auto = the leaderboard winner for this agent's role."
        >
          <TextInput id="ed-model" mono value={model} invalid={!modelOk} onChange={(e) => setModel(e.target.value.trim())} placeholder="auto" />
        </Field>
        <Field label="Concurrency" hint="Tasks this agent may run at once.">
          <Stepper label="Concurrency" value={concurrency} min={1} max={8} onCommit={setConcurrency} color={color} width={3} />
        </Field>
        <Field label="Schedule">
          <ScheduleEditor value={schedule} onChange={setSchedule} schedulable={schedulable} color={color} />
        </Field>
        {agent.builtin && (
          <p className="rounded-xl border border-white/[.06] bg-white/[.02] p-3 text-xs leading-relaxed text-muted">
            Built-in agents keep their capabilities{agent.side_effects.length ? ' and side-effect ownership' : ''}; you can change how they run, not what they are allowed to do.
          </p>
        )}
      </div>
      <div className="flex items-center justify-between gap-3 border-t border-white/[.06] px-5 py-4">
        <span className="min-w-0 truncate text-xs text-red-300">{err}</span>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" icon={Save} loading={busy} disabled={!modelOk || !name.trim()} onClick={save}>
            Save
          </Button>
        </div>
      </div>
    </>
  );
}
