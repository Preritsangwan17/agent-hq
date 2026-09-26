/** Desktop sidebar: grouped nav with icons + labels, Needs badge, team status strip, collapse toggle (persisted). */
import { LogOut, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { NavLink } from 'react-router';
import { Tooltip } from '@/components/Tooltip';
import { cn } from '@/lib/cn';
import { useAgentsList, useOpenNeedsCount } from '@/lib/store';
import { withAlpha } from '@/theme/tokens';
import { Logo } from './Logo';
import { NAV, NAV_GROUPS, type NavItem } from './nav';

export interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  onLogout: () => void;
  className?: string;
}

export function Sidebar({ collapsed, onToggle, onLogout, className }: SidebarProps) {
  const needs = useOpenNeedsCount();
  return (
    <aside
      className={cn(
        'sticky top-0 z-30 h-dvh shrink-0 flex-col border-r border-white/[.07] bg-[#080D18]/70 backdrop-blur-xl transition-[width] duration-200',
        collapsed ? 'w-[72px]' : 'w-[232px]',
        className,
      )}
    >
      <div className={cn('flex h-16 items-center', collapsed ? 'justify-center' : 'px-5')}>
        <NavLink to="/" aria-label="Agent HQ home">
          <Logo collapsed={collapsed} />
        </NavLink>
      </div>

      <nav className="flex-1 space-y-5 overflow-y-auto px-3 pt-2 scrollbar-none" aria-label="Main">
        {NAV_GROUPS.map((g) => (
          <div key={g}>
            {!collapsed && (
              <div className="mb-1.5 px-2.5 font-mono text-[9.5px] font-medium uppercase tracking-[0.2em] text-faint">{g}</div>
            )}
            {collapsed && <div className="mx-auto mb-2 h-px w-6 bg-white/[.07]" aria-hidden />}
            <ul className="space-y-0.5">
              {NAV.filter((n) => n.group === g).map((item) => (
                <li key={item.to}>
                  <SideLink item={item} collapsed={collapsed} count={item.badge === 'needs' ? needs : 0} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <TeamStrip collapsed={collapsed} />

      <div className={cn('flex gap-1 border-t border-white/[.06] p-3', collapsed ? 'flex-col items-center' : 'items-center')}>
        <Tooltip content={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} side="top">
          <button
            type="button"
            onClick={onToggle}
            className="grid size-9 place-items-center rounded-lg text-muted transition-colors hover:bg-white/[.06] hover:text-ink"
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? <PanelLeftOpen className="size-[18px]" /> : <PanelLeftClose className="size-[18px]" />}
          </button>
        </Tooltip>
        <Tooltip content="Log out" side="top">
          <button
            type="button"
            onClick={onLogout}
            className="grid size-9 place-items-center rounded-lg text-muted transition-colors hover:bg-white/[.06] hover:text-ink"
            aria-label="Log out"
          >
            <LogOut className="size-[18px]" />
          </button>
        </Tooltip>
      </div>
    </aside>
  );
}

function SideLink({ item, collapsed, count }: { item: NavItem; collapsed: boolean; count: number }) {
  const Icon = item.icon;
  const link = (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      className={({ isActive }) =>
        cn(
          'group relative flex h-10 items-center gap-3 rounded-xl text-sm font-medium transition-colors',
          collapsed ? 'justify-center' : 'px-2.5',
          isActive ? 'bg-white/[.07] text-ink' : 'text-muted hover:bg-white/[.04] hover:text-ink',
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span
              aria-hidden
              className="absolute -left-3 top-2 bottom-2 w-[3px] rounded-r-full"
              style={{ backgroundColor: item.color, boxShadow: `0 0 12px ${item.color}` }}
            />
          )}
          <span className="relative grid size-5 place-items-center">
            <Icon
              className="size-[18px] transition-colors"
              style={isActive ? { color: item.color, filter: `drop-shadow(0 0 6px ${withAlpha(item.color, 0.7)})` } : undefined}
              aria-hidden
            />
            {collapsed && count > 0 && (
              <span className="absolute -right-2 -top-1.5 grid h-4 min-w-4 place-items-center rounded-full bg-[#FB923C] px-1 text-[9px] font-bold text-[#140a02]">
                {count}
              </span>
            )}
          </span>
          {!collapsed && <span className="flex-1 truncate">{item.label}</span>}
          {!collapsed && count > 0 && (
            <span className="grid h-5 min-w-5 place-items-center rounded-full bg-[#FB923C] px-1.5 text-[10.5px] font-bold tabular text-[#140a02] shadow-[0_0_12px_-2px_rgba(251,146,60,0.8)]">
              {count}
            </span>
          )}
        </>
      )}
    </NavLink>
  );
  return collapsed ? (
    <Tooltip content={item.label} side="top" triggerClassName="w-full">
      <div className="w-full">{link}</div>
    </Tooltip>
  ) : (
    link
  );
}

/** Ten dots, one per agent, lit while working. */
function TeamStrip({ collapsed }: { collapsed: boolean }) {
  const agents = useAgentsList();
  if (!agents.length) return null;
  const working = agents.filter((a) => a.status === 'working').length;
  return (
    <div className={cn('mx-3 mb-2 rounded-xl border border-white/[.06] bg-white/[.02] p-2.5', collapsed && 'mx-2 px-1.5')}>
      {!collapsed && (
        <div className="mb-2 flex items-center justify-between text-[10.5px] text-muted">
          <span className="font-mono uppercase tracking-[0.16em]">Team</span>
          <span className="tabular">
            <span className="text-ink">{working}</span>/{agents.length} working
          </span>
        </div>
      )}
      <div className={cn('flex flex-wrap gap-1.5', collapsed && 'justify-center')}>
        {agents.map((a) => {
          const on = a.status === 'working';
          return (
            <Tooltip key={a.id} content={`${a.avatar} ${a.name} — ${a.status}`} side="top">
              <span
                className={cn('block size-2.5 rounded-full transition-opacity duration-300', on ? 'opacity-100' : 'opacity-30')}
                style={{ backgroundColor: a.color, boxShadow: on ? `0 0 8px ${a.color}` : undefined }}
              />
            </Tooltip>
          );
        })}
      </div>
    </div>
  );
}
