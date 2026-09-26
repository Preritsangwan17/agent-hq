/** < 768 px: bottom tab bar (Home, Pipeline, Needs, Activity, More) + a "More" sheet for the other pages. */
import { AnimatePresence, motion } from 'motion/react';
import { Ellipsis, LogOut, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { NavLink, useLocation } from 'react-router';
import { cn } from '@/lib/cn';
import { useOpenNeedsCount } from '@/lib/store';
import { NAV } from './nav';

export function MobileTabBar({ onLogout, className }: { onLogout: () => void; className?: string }) {
  const needs = useOpenNeedsCount();
  const [more, setMore] = useState(false);
  const { pathname } = useLocation();
  const tabs = NAV.filter((n) => n.mobile === 'tab');
  const extra = NAV.filter((n) => n.mobile === 'more');
  const moreActive = extra.some((n) => pathname.startsWith(n.to));

  useEffect(() => setMore(false), [pathname]);

  return (
    <>
      <nav
        aria-label="Primary"
        className={cn(
          'pb-safe fixed inset-x-0 bottom-0 z-50 border-t border-white/[.08] bg-[#080D18]/85 backdrop-blur-2xl',
          className,
        )}
      >
        <ul className="mx-auto grid h-16 max-w-md grid-cols-5">
          {tabs.map((item) => {
            const Icon = item.icon;
            const count = item.badge === 'needs' ? needs : 0;
            return (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.to === '/'}
                  className={({ isActive }) =>
                    cn('flex h-full flex-col items-center justify-center gap-1 text-[10.5px] font-medium', isActive ? 'text-ink' : 'text-muted')
                  }
                >
                  {({ isActive }) => (
                    <>
                      <span className="relative">
                        <Icon
                          className="size-5"
                          style={isActive ? { color: item.color, filter: `drop-shadow(0 0 6px ${item.color})` } : undefined}
                          aria-hidden
                        />
                        {count > 0 && (
                          <span className="absolute -right-2.5 -top-1.5 grid h-4 min-w-4 place-items-center rounded-full bg-[#FB923C] px-1 text-[9px] font-bold text-[#140a02]">
                            {count}
                          </span>
                        )}
                      </span>
                      {item.short ?? item.label}
                    </>
                  )}
                </NavLink>
              </li>
            );
          })}
          <li>
            <button
              type="button"
              onClick={() => setMore(true)}
              className={cn('flex h-full w-full flex-col items-center justify-center gap-1 text-[10.5px] font-medium', moreActive || more ? 'text-ink' : 'text-muted')}
              aria-haspopup="dialog"
              aria-expanded={more}
            >
              <Ellipsis className="size-5" aria-hidden />
              More
            </button>
          </li>
        </ul>
      </nav>

      <AnimatePresence>
        {more && (
          <>
            <motion.div
              key="scrim"
              className="fixed inset-0 z-[60] bg-black/60"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setMore(false)}
            />
            <motion.div
              key="sheet"
              role="dialog"
              aria-label="More pages"
              className="pb-safe fixed inset-x-0 bottom-0 z-[61] rounded-t-3xl border-t border-white/10 bg-[#0B111D]/95 backdrop-blur-2xl"
              initial={{ y: '100%' }}
              animate={{ y: 0 }}
              exit={{ y: '100%' }}
              transition={{ type: 'spring', stiffness: 420, damping: 40 }}
            >
              <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-white/20" />
              <div className="flex items-center justify-between px-5 pb-2 pt-3">
                <span className="font-display text-base font-semibold">More</span>
                <button type="button" onClick={() => setMore(false)} className="grid size-9 place-items-center rounded-lg text-muted hover:bg-white/5" aria-label="Close">
                  <X className="size-5" />
                </button>
              </div>
              <ul className="grid grid-cols-3 gap-2 px-4 pb-6">
                {extra.map((item) => {
                  const Icon = item.icon;
                  return (
                    <li key={item.to}>
                      <NavLink
                        to={item.to}
                        className={({ isActive }) =>
                          cn(
                            'flex h-20 flex-col items-center justify-center gap-2 rounded-2xl border text-xs font-medium',
                            isActive ? 'border-white/15 bg-white/[.07] text-ink' : 'border-white/[.06] bg-white/[.03] text-muted',
                          )
                        }
                      >
                        <Icon className="size-5" style={{ color: item.color }} aria-hidden />
                        {item.label}
                      </NavLink>
                    </li>
                  );
                })}
                <li>
                  <button
                    type="button"
                    onClick={onLogout}
                    className="flex h-20 w-full flex-col items-center justify-center gap-2 rounded-2xl border border-white/[.06] bg-white/[.03] text-xs font-medium text-muted"
                  >
                    <LogOut className="size-5" aria-hidden />
                    Log out
                  </button>
                </li>
              </ul>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  );
}
