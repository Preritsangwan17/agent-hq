/**
 * /agents — the agent manager: every agent with live state, model, capabilities and schedule; pause/enable
 * switches, an edit drawer (rewrites the YAML, hot-reloaded) and the Add Agent wizard. Built-in agents can be
 * disabled but not deleted; side-effect capabilities stay with the built-in Applicant, Inbox and Follow-up.
 */
import { Bot, Plus, ShieldCheck } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Badge, Button, SectionHeader } from '@/components';
import { useAgentsMeta } from '@/lib/queries';
import { useAgentsList, useHQ } from '@/lib/store';
import type { Capability } from '@/lib/types';
import { AgentManagerCard } from './AgentManagerCard';
import { EditDrawer } from './EditDrawer';
import { Wizard } from './Wizard';

export default function Agents() {
  const agents = useAgentsList();
  const meta = useAgentsMeta();
  const [editing, setEditing] = useState<string | null>(null);
  const [wizard, setWizard] = useState(false);
  const editingAgent = useHQ((s) => (editing ? s.agents[editing] ?? null : null));
  const capMeta = useMemo(() => Object.fromEntries((meta.data?.capabilities ?? []).map((c) => [c.id, c])) as Record<string, Capability>, [meta.data]);

  const working = agents.filter((a) => a.status === 'working').length;
  const custom = agents.filter((a) => !a.builtin).length;
  const probation = agents.filter((a) => (a.probation_runs_left ?? 0) > 0).length;

  return (
    <div className="space-y-5">
      <SectionHeader
        as="h1"
        size="lg"
        kicker="Manager"
        title="Agents"
        right={
          <Button variant="primary" icon={Plus} onClick={() => setWizard(true)}>
            Add agent
          </Button>
        }
      />
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge color="#34D399" size="md">
          {working} working
        </Badge>
        <Badge color="#8B95A7" size="md" icon={Bot}>
          {agents.length} agents · {custom} yours
        </Badge>
        {probation > 0 && (
          <Badge color="#FBBF24" size="md">
            {probation} on probation
          </Badge>
        )}
        <Badge color="#F472B6" size="md" icon={ShieldCheck}>
          Sending stays with Applicant, Inbox Watcher and Follow-up
        </Badge>
      </div>

      <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
        {agents.map((a) => (
          <AgentManagerCard key={a.id} agent={a} capMeta={capMeta} onEdit={setEditing} />
        ))}
      </div>

      <EditDrawer agent={editingAgent} onClose={() => setEditing(null)} />
      <Wizard open={wizard} onClose={() => setWizard(false)} />
    </div>
  );
}
