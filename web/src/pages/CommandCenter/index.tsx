/**
 * Command Center (foundation placeholder). A page agent replaces this with the full layout (AgentNetwork graph,
 * strategist card …). It already exercises the shared kit against live store data so the shell can be verified.
 */
import { Activity, Bot, Coins, Radar, Send, ShieldCheck, Sparkles, Trophy } from 'lucide-react';
import { Link } from 'react-router';
import {
  AgentAvatar,
  Countdown,
  EmptyState,
  GlassPanel,
  PayBadge,
  ProgressBar,
  SectionHeader,
  SimTag,
  StageChip,
  StatCounter,
} from '@/components';
import { formatCompact, formatINRCompact, formatUSD } from '@/lib/format';
import { useAgentsList, useHQ, useOppList, useStats } from '@/lib/store';
import type { Agent } from '@/lib/types';

export default function CommandCenter() {
  const stats = useStats();
  const agents = useAgentsList();
  const opps = useOppList();
  const recent = opps.filter((o) => o.stage !== 'filtered').slice(0, 8);

  return (
    <div className="space-y-5 md:space-y-6">
      <div className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-3 xl:grid-cols-6">
        <GlassPanel glow="#22D3EE" padding="md">
          <StatCounter value={stats?.found} label="Found" icon={Radar} accent="#22D3EE" sub={`${stats?.filtered ?? 0} filtered out`} />
        </GlassPanel>
        <GlassPanel glow="#2DD4BF" padding="md">
          <StatCounter value={stats?.verified} label="Verified" icon={ShieldCheck} accent="#2DD4BF" sub={`${stats?.drafted ?? 0} drafted`} />
        </GlassPanel>
        <GlassPanel glow="#F472B6" padding="md">
          <StatCounter value={stats?.applied} label="Applied" icon={Send} accent="#F472B6" sub={`${stats?.replies ?? 0} replies`} />
        </GlassPanel>
        <GlassPanel glow="#E879F9" padding="md">
          <StatCounter
            value={stats?.interviews}
            label="Interviews"
            icon={Trophy}
            accent="#E879F9"
            sub={stats?.success_rate != null ? `${Math.round(stats.success_rate * 100)}% of applied` : '—'}
          />
        </GlassPanel>
        <GlassPanel glow="#F5C451" padding="md">
          <StatCounter
            value={stats?.pay.pipeline_median_inr}
            label="Pipeline pay"
            icon={Coins}
            money
            format={(n) => formatINRCompact(n)}
            sub={`median/mo · max ${formatINRCompact(stats?.pay.pipeline_max_inr)}`}
          />
        </GlassPanel>
        <GlassPanel glow="#E879F9" padding="md">
          <StatCounter
            value={stats?.claude_cost_today_usd}
            label="Claude today"
            icon={Sparkles}
            accent="#E879F9"
            format={(n) => formatUSD(n)}
            sub={`${formatCompact(stats?.local_tokens_today)} local tokens`}
          />
        </GlassPanel>
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.35fr_1fr]">
        <GlassPanel padding="lg" glow="#A78BFA">
          <SectionHeader kicker="Live" title="Agent team" icon={Bot} color="#A78BFA" className="mb-4" right={<WorkingCount />} />
          <div className="grid gap-2.5 sm:grid-cols-2">
            {agents.map((a) => (
              <AgentRow key={a.id} agent={a} />
            ))}
          </div>
        </GlassPanel>

        <GlassPanel padding="lg" glow="#F5C451">
          <SectionHeader kicker="Latest" title="Opportunities" icon={Activity} color="#22D3EE" className="mb-3" />
          {recent.length === 0 ? (
            <EmptyState compact title="Nothing found yet" hint="Scout checks the boards every minute." />
          ) : (
            <ul className="divide-y divide-white/[.06]">
              {recent.map((o) => (
                <li key={o.id}>
                  <Link to={`/o/${o.id}`} className="-mx-2 flex items-start gap-3 rounded-xl px-2 py-3 transition-colors hover:bg-white/[.03]">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-sm font-medium text-ink">{o.company_name}</span>
                        <SimTag show={o.is_simulated} />
                      </div>
                      <div className="truncate text-xs text-muted">{o.title}</div>
                      <div className="mt-1.5 flex flex-wrap items-center gap-2">
                        <StageChip stage={o.stage} />
                        <Countdown deadline={o.deadline_at} confidence={o.deadline_confidence} compact />
                      </div>
                    </div>
                    <PayBadge pay={o.pay} size="sm" compact align="right" className="max-w-[46%] shrink-0" />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </GlassPanel>
      </div>
    </div>
  );
}

function WorkingCount() {
  const n = useHQ((s) => Object.values(s.agents).filter((a) => a.status === 'working').length);
  return <span className="text-xs text-muted tabular">{n} working</span>;
}

function AgentRow({ agent }: { agent: Agent }) {
  const live = useHQ((s) => s.live[agent.id]);
  const working = agent.status === 'working';
  return (
    <div className="flex items-center gap-3 rounded-xl border border-white/[.06] bg-white/[.02] p-3">
      <AgentAvatar agent={agent} size="md" showStatus />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-sm font-medium text-ink">{agent.name}</span>
          <span className="shrink-0 font-mono text-[10.5px] text-muted tabular">
            {live?.tok_s ? `${live.tok_s} tok/s` : `${agent.tasks_today} today`}
          </span>
        </div>
        <div className="mt-0.5 truncate font-mono text-[11px] text-muted">
          {working ? live?.now_line ?? '…' : agent.status === 'paused' ? 'paused' : 'idle'}
        </div>
        <ProgressBar className="mt-2" value={working ? live?.progress ?? null : 0} color={agent.color} height={3} />
      </div>
    </div>
  );
}
