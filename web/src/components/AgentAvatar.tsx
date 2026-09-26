/**
 * AgentAvatar: the agent's emoji (or a known lucide icon name) in a glowing ring of its accent color.
 * Pulses while working, dims when paused/disabled/offline, turns red on error. Pass `agent`, or just `id`
 * to read it from the live store.
 */
import {
  Bot,
  Brain,
  Clock,
  Compass,
  Cpu,
  FileText,
  FlaskConical,
  Globe,
  Inbox,
  Mail,
  PenLine,
  Radar,
  Rocket,
  Satellite,
  Search,
  Shield,
  Sparkles,
  Zap,
  type LucideIcon,
} from 'lucide-react';
import { cn } from '@/lib/cn';
import { useAgent } from '@/lib/store';
import type { Agent, AgentStatus } from '@/lib/types';
import { AGENT_PRESETS, AGENT_STATUS_META, colors, withAlpha } from '@/theme/tokens';

const ICONS: Record<string, LucideIcon> = {
  bot: Bot, brain: Brain, clock: Clock, compass: Compass, cpu: Cpu, 'file-text': FileText, 'flask-conical': FlaskConical,
  globe: Globe, inbox: Inbox, mail: Mail, 'pen-line': PenLine, radar: Radar, rocket: Rocket, satellite: Satellite,
  search: Search, shield: Shield, sparkles: Sparkles, zap: Zap,
};

export type AvatarAgent = Pick<Agent, 'id' | 'name' | 'avatar' | 'color'> & { status?: AgentStatus };

export interface AgentAvatarProps {
  agent?: AvatarAgent | null;
  /** looked up in the store when `agent` isn't given */
  id?: string | null;
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl' | number;
  /** override working pulse (default: status === 'working') */
  working?: boolean;
  /** small status dot bottom-right */
  showStatus?: boolean;
  className?: string;
  title?: string;
}

const PX = { xs: 20, sm: 28, md: 36, lg: 48, xl: 72 } as const;

export function AgentAvatar({ agent, id, size = 'md', working, showStatus, className, title }: AgentAvatarProps) {
  const fromStore = useAgent(agent ? null : id);
  const preset = AGENT_PRESETS.find((p) => p.id === (agent?.id ?? id));
  const a: AvatarAgent | null =
    agent ?? fromStore ?? (preset ? { id: preset.id, name: preset.name, avatar: preset.emoji, color: preset.color } : null);
  const px = typeof size === 'number' ? size : PX[size];
  const color = a?.color ?? '#94A3B8';
  const status = a?.status;
  const isWorking = working ?? status === 'working';
  const dim = status === 'paused' || status === 'disabled' || status === 'offline';
  const ring = status === 'error' || status === 'stuck' ? colors.danger : color;
  const avatar = a?.avatar ?? '🤖';
  const Icon = ICONS[avatar.toLowerCase()];
  const glyph = Math.round(px * 0.5);

  return (
    <span
      className={cn('relative inline-grid shrink-0 place-items-center', className)}
      style={{ width: px, height: px }}
      title={title ?? a?.name}
      role="img"
      aria-label={a ? `${a.name}${status ? ` (${status})` : ''}` : 'agent'}
    >
      {isWorking && (
        <>
          <span className="absolute inset-0 animate-pulse-ring rounded-full border" style={{ borderColor: withAlpha(ring, 0.7) }} />
          <span
            className="absolute inset-0 animate-pulse-ring rounded-full border"
            style={{ borderColor: withAlpha(ring, 0.5), animationDelay: '0.9s' }}
          />
        </>
      )}
      <span
        className={cn('relative grid size-full place-items-center rounded-full border transition-opacity duration-300', dim && 'opacity-45')}
        style={{
          borderColor: withAlpha(ring, isWorking ? 0.85 : 0.5),
          background: `radial-gradient(circle at 50% 35%, ${withAlpha(color, 0.28)}, ${withAlpha(color, 0.06)} 70%)`,
          boxShadow: `0 0 ${Math.round(px * 0.45)}px -${Math.round(px * 0.12)}px ${withAlpha(ring, isWorking ? 0.75 : 0.4)}, inset 0 0 ${Math.round(px * 0.3)}px ${withAlpha(color, 0.15)}`,
        }}
      >
        {Icon ? (
          <Icon style={{ width: glyph, height: glyph, color }} aria-hidden />
        ) : (
          <span className="leading-none select-none" style={{ fontSize: glyph }} aria-hidden>
            {avatar}
          </span>
        )}
      </span>
      {showStatus && status && (
        <span
          className="absolute rounded-full border-2 border-bg"
          style={{
            width: Math.max(8, px * 0.26),
            height: Math.max(8, px * 0.26),
            right: -1,
            bottom: -1,
            backgroundColor: AGENT_STATUS_META[status]?.color ?? colors.muted,
          }}
        />
      )}
    </span>
  );
}
