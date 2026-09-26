/**
 * Command Center: count-up hero stats (pipeline, pay, Grok $ vs free local tokens), the live Agent Network graph,
 * agent cards with their typing now-lines, pay highlights, the Needs Prerit queue, the Strategist's latest report
 * and a compact live feed. Everything updates from the zustand store (snapshot + SSE).
 */
import './commandCenter.css';
import { Activity, ArrowRight, Coins, Compass, HandHelping, Radar, Send, ShieldCheck, Sparkles, Trophy } from 'lucide-react';
import { Link } from 'react-router';
import {
  AgentAvatar,
  Countdown,
  EmptyState,
  GlassPanel,
  PayBadge,
  SectionHeader,
  SimTag,
  StageChip,
  StatCounter,
} from '@/components';
import { formatClockIST, formatCompact, formatINRCompact, formatUSD } from '@/lib/format';
import { useHQ, useOpenNeeds, useOppList, useStats } from '@/lib/store';
import type { HQEvent } from '@/lib/types';
import { colors } from '@/theme/tokens';
import { AgentCards } from './AgentCards';
import { AgentNetwork } from './network/AgentNetwork';
import { StrategistCard } from './StrategistCard';

export default function CommandCenter() {
  const stats = useStats();
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
            sub={stats?.success_rate != null ? `${Math.round(stats.success_rate * 100)}% of applied · ${stats.offers} offers` : `${stats?.offers ?? 0} offers`}
          />
        </GlassPanel>
        <GlassPanel glow={colors.gold} padding="md">
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
            value={stats?.cloud_cost_today_usd}
            label="Grok today"
            icon={Sparkles}
            accent="#E879F9"
            format={(n) => formatUSD(n)}
            sub={`${stats?.cloud_calls_today ?? 0} calls · ${formatCompact(stats?.local_tokens_today)} local tok (free)`}
          />
        </GlassPanel>
      </div>

      <AgentNetwork />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <AgentCards />
        <div className="space-y-5">
          <PayPanel />
          <NeedsPanel />
          <StrategistCard />
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <LatestOpps />
        <LiveFeed />
      </div>
    </div>
  );
}

function PayPanel() {
  const stats = useStats();
  const pay = stats?.pay;
  const rows = [
    { label: 'Best offer', value: pay?.best_offer_inr, hint: 'highest ₹/mo among offers' },
    { label: 'Median stipend applied', value: pay?.median_applied_inr, hint: 'across applications sent' },
    { label: 'Pipeline max', value: pay?.pipeline_max_inr, hint: 'highest ₹/mo still in play' },
  ];
  return (
    <GlassPanel padding="lg" glow={colors.gold} glowStrength={0.25}>
      <SectionHeader kicker="How much they pay" title="Pay" icon={Coins} color={colors.gold} />
      <dl className="mt-3 divide-y divide-white/[.06]">
        {rows.map((r) => (
          <div key={r.label} className="flex items-baseline justify-between gap-3 py-2.5">
            <dt className="min-w-0">
              <div className="text-[13px] text-ink/90">{r.label}</div>
              <div className="text-[11px] text-faint">{r.hint}</div>
            </dt>
            <dd className="font-display text-lg font-semibold text-money tabular">{r.value != null ? `${formatINRCompact(r.value)}/mo` : '—'}</dd>
          </div>
        ))}
      </dl>
    </GlassPanel>
  );
}

function NeedsPanel() {
  const needs = useOpenNeeds();
  const top = needs.slice(0, 4);
  return (
    <GlassPanel padding="lg" glow="#FB923C" glowStrength={0.25}>
      <SectionHeader
        kicker="Your queue"
        title="Needs Prerit"
        icon={HandHelping}
        color="#FB923C"
        right={
          <Link to="/needs" className="inline-flex items-center gap-1 text-xs font-medium text-cyan-300 hover:text-cyan-200">
            {needs.length} open <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        }
      />
      {top.length === 0 ? (
        <EmptyState compact title="Nothing waiting on you" hint="Forms, approvals and decisions land here." color="#FB923C" />
      ) : (
        <ul className="mt-3 space-y-1.5">
          {top.map((n) => (
            <li key={n.id}>
              <Link to="/needs" className="-mx-2 flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-white/[.04]">
                <span className="min-w-0 flex-1 truncate text-[13px] text-ink/90">{n.title}</span>
                {n.est_minutes != null && <span className="shrink-0 text-[11px] text-faint tabular">~{Math.round(n.est_minutes)} min</span>}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </GlassPanel>
  );
}

function LatestOpps() {
  const opps = useOppList();
  const recent = opps.filter((o) => o.stage !== 'filtered').slice(0, 8);
  return (
    <GlassPanel padding="lg" glow="#22D3EE" glowStrength={0.2}>
      <SectionHeader
        kicker="Latest"
        title="Opportunities"
        icon={Compass}
        color="#22D3EE"
        right={
          <Link to="/pipeline" className="inline-flex items-center gap-1 text-xs font-medium text-cyan-300 hover:text-cyan-200">
            Pipeline <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        }
      />
      {recent.length === 0 ? (
        <EmptyState compact title="Nothing found yet" hint="Scout checks the boards on its schedule." />
      ) : (
        <ul className="mt-2 divide-y divide-white/[.06]">
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
  );
}

const FEED_HIDE = new Set(['worker.heartbeat', 'task.leased', 'task.created']);

function LiveFeed() {
  const events = useHQ((s) => s.events);
  const agents = useHQ((s) => s.agents);
  const feed: HQEvent[] = [];
  for (let i = events.length - 1; i >= 0 && feed.length < 12; i--) {
    const e = events[i];
    if (e.level !== 'debug' && !FEED_HIDE.has(e.type)) feed.push(e);
  }
  return (
    <GlassPanel padding="lg" glow="#A3E635" glowStrength={0.18}>
      <SectionHeader
        kicker="Live"
        title="Activity"
        icon={Activity}
        color="#A3E635"
        right={
          <Link to="/activity" className="inline-flex items-center gap-1 text-xs font-medium text-cyan-300 hover:text-cyan-200">
            Terminal <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        }
      />
      {feed.length === 0 ? (
        <EmptyState compact title="Quiet so far" hint="Events stream in as agents work." color="#A3E635" />
      ) : (
        <ul className="mt-3 space-y-1">
          {feed.map((e) => {
            const a = e.agent_id ? agents[e.agent_id] : undefined;
            const tone = e.level === 'error' ? 'text-red-300' : e.level === 'warn' || e.level === 'alert' ? 'text-amber-200' : 'text-ink/85';
            return (
              <li key={e.id} className="flex items-start gap-2.5 py-1">
                <span className="mt-0.5 w-11 shrink-0 font-mono text-[10.5px] text-faint tabular">{formatClockIST(e.ts, false)}</span>
                {a ? <AgentAvatar agent={a} size="xs" /> : <span className="size-5 shrink-0" />}
                <span className={`min-w-0 flex-1 text-[12.5px] leading-snug ${tone}`}>{e.message}</span>
              </li>
            );
          })}
        </ul>
      )}
    </GlassPanel>
  );
}
