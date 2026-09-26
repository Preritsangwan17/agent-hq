/** Navigation model shared by the sidebar, the mobile tab bar and page titles. */
import {
  Bot,
  ChartColumn,
  Cpu,
  Earth,
  HandHelping,
  Inbox,
  Radar,
  Settings,
  SquareKanban,
  SquareTerminal,
  Sparkles,
  type LucideIcon,
} from 'lucide-react';

export interface NavItem {
  to: string;
  label: string;
  /** short label for the mobile tab bar */
  short?: string;
  icon: LucideIcon;
  group: 'Operate' | 'Observe' | 'System';
  /** mobile placement: bottom tab or inside "More" */
  mobile: 'tab' | 'more';
  badge?: 'needs';
  /** accent used for the active icon glow */
  color: string;
}

export const NAV: readonly NavItem[] = [
  { to: '/', label: 'Command Center', short: 'Home', icon: Radar, group: 'Operate', mobile: 'tab', color: '#22D3EE' },
  { to: '/pipeline', label: 'Pipeline', icon: SquareKanban, group: 'Operate', mobile: 'tab', color: '#A78BFA' },
  { to: '/map', label: 'Map', icon: Earth, group: 'Operate', mobile: 'more', color: '#2DD4BF' },
  { to: '/needs', label: 'Needs Prerit', short: 'Needs', icon: HandHelping, group: 'Operate', mobile: 'tab', badge: 'needs', color: '#FB923C' },
  { to: '/activity', label: 'Activity', icon: SquareTerminal, group: 'Observe', mobile: 'tab', color: '#A3E635' },
  { to: '/inbox', label: 'Inbox', icon: Inbox, group: 'Observe', mobile: 'more', color: '#60A5FA' },
  { to: '/analytics', label: 'Analytics', icon: ChartColumn, group: 'Observe', mobile: 'more', color: '#F472B6' },
  { to: '/usage', label: 'AI usage & limits', short: 'AI usage', icon: Sparkles, group: 'System', mobile: 'more', color: '#E879F9' },
  { to: '/models', label: 'Models', icon: Cpu, group: 'System', mobile: 'more', color: '#F59E0B' },
  { to: '/agents', label: 'Agents', icon: Bot, group: 'System', mobile: 'more', color: '#E879F9' },
  { to: '/settings', label: 'Settings', icon: Settings, group: 'System', mobile: 'more', color: '#8B95A7' },
];

export const NAV_GROUPS: readonly NavItem['group'][] = ['Operate', 'Observe', 'System'];

export function navFor(pathname: string): NavItem | undefined {
  if (pathname.startsWith('/o/')) return undefined;
  return NAV.find((n) => (n.to === '/' ? pathname === '/' : pathname === n.to || pathname.startsWith(`${n.to}/`)));
}

export function titleFor(pathname: string): string {
  if (pathname.startsWith('/o/')) return 'Opportunity';
  return navFor(pathname)?.label ?? 'Agent HQ';
}
