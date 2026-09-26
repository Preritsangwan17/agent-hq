/**
 * /settings — Autonomy & Mode, Rules, Budget, Schedules, Simulation, Profile & Facts, Security.
 * Every editable value is PATCHed to /api/settings optimistically (see saver.tsx); the active tab lives in
 * `?tab=` so it survives reloads and can be linked.
 */
import {
  FlaskConical,
  Gauge,
  LockKeyhole,
  MoonStar,
  ShieldCheck,
  SlidersHorizontal,
  UserRound,
  type LucideIcon,
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import type { ComponentType } from 'react';
import { useSearchParams } from 'react-router';
import { GlassPanel } from '@/components/GlassPanel';
import { SectionHeader } from '@/components/SectionHeader';
import { cn } from '@/lib/cn';
import { withAlpha } from '@/theme/tokens';
import { SaveIndicator } from './controls';
import { SettingsSaverProvider, useSaver } from './saver';
import { AutonomyTab } from './tabs/AutonomyTab';
import { BudgetTab } from './tabs/BudgetTab';
import { ProfileTab } from './tabs/ProfileTab';
import { RulesTab } from './tabs/RulesTab';
import { SchedulesTab } from './tabs/SchedulesTab';
import { SecurityTab } from './tabs/SecurityTab';
import { SimulationTab } from './tabs/SimulationTab';

interface TabDef {
  id: string;
  label: string;
  short?: string;
  icon: LucideIcon;
  color: string;
  blurb: string;
  Component: ComponentType;
}

const TABS: readonly TabDef[] = [
  { id: 'autonomy', label: 'Autonomy & Mode', short: 'Autonomy', icon: ShieldCheck, color: '#22D3EE', blurb: 'Mode, approvals, outbound, kill switch', Component: AutonomyTab },
  { id: 'rules', label: 'Rules', icon: SlidersHorizontal, color: '#2DD4BF', blurb: 'Gates, pay floor, fit, daily caps', Component: RulesTab },
  { id: 'budget', label: 'Budget', icon: Gauge, color: '#E879F9', blurb: 'Claude spend and call cap', Component: BudgetTab },
  { id: 'schedules', label: 'Schedules', icon: MoonStar, color: '#818CF8', blurb: 'Quiet hours, keep awake', Component: SchedulesTab },
  { id: 'simulation', label: 'Simulation', icon: FlaskConical, color: '#38BDF8', blurb: 'Sim on/off, speed, reset', Component: SimulationTab },
  { id: 'profile', label: 'Profile & Facts', short: 'Profile', icon: UserRound, color: '#60A5FA', blurb: 'Fields needed before go-live', Component: ProfileTab },
  { id: 'security', label: 'Security', icon: LockKeyhole, color: '#A3E635', blurb: 'Passcode, LAN, secrets', Component: SecurityTab },
];

export default function Settings() {
  return (
    <SettingsSaverProvider>
      <SettingsPage />
    </SettingsSaverProvider>
  );
}

function SettingsPage() {
  const [params, setParams] = useSearchParams();
  const active = TABS.find((t) => t.id === params.get('tab')) ?? TABS[0];
  const { state } = useSaver();
  const select = (id: string) =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p);
        next.set('tab', id);
        return next;
      },
      { replace: true },
    );

  return (
    <div className="space-y-5 md:space-y-6">
      <SectionHeader
        as="h1"
        size="lg"
        kicker="Rules & safety"
        title="Settings"
        right={<SaveIndicator status={state.status} at={state.at} error={state.error} />}
      />

      {/* mobile / tablet: horizontal pills */}
      <nav aria-label="Settings sections" className="-mx-4 overflow-x-auto px-4 scrollbar-none lg:hidden">
        <div className="flex w-max gap-1.5 pb-1">
          {TABS.map((t) => {
            const on = t.id === active.id;
            const Icon = t.icon;
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => select(t.id)}
                aria-current={on ? 'page' : undefined}
                className={cn(
                  'inline-flex h-9 items-center gap-1.5 rounded-full border px-3.5 text-[13px] font-medium transition-colors',
                  on ? 'text-ink' : 'border-white/10 bg-white/[.03] text-muted',
                )}
                style={on ? { borderColor: withAlpha(t.color, 0.5), backgroundColor: withAlpha(t.color, 0.12), boxShadow: `0 0 18px -8px ${t.color}` } : undefined}
              >
                <Icon className="size-3.5" style={{ color: on ? t.color : undefined }} aria-hidden />
                {t.short ?? t.label}
              </button>
            );
          })}
        </div>
      </nav>

      <div className="grid gap-6 lg:grid-cols-[248px_minmax(0,1fr)]">
        <aside className="hidden lg:block">
          <GlassPanel padding="sm" className="sticky top-24">
            <nav aria-label="Settings sections" className="space-y-0.5">
              {TABS.map((t) => {
                const on = t.id === active.id;
                const Icon = t.icon;
                return (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => select(t.id)}
                    aria-current={on ? 'page' : undefined}
                    className={cn(
                      'group relative flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors',
                      on ? 'text-ink' : 'text-muted hover:bg-white/[.04] hover:text-ink',
                    )}
                  >
                    {on && (
                      <motion.span
                        layoutId="settings-tab"
                        aria-hidden
                        className="absolute inset-0 rounded-xl border"
                        style={{ borderColor: withAlpha(t.color, 0.35), backgroundColor: withAlpha(t.color, 0.09), boxShadow: `0 0 24px -12px ${t.color}` }}
                        transition={{ type: 'spring', stiffness: 480, damping: 40 }}
                      />
                    )}
                    <span
                      className="relative grid size-8 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/[.03]"
                      style={on ? { boxShadow: `0 0 16px -6px ${t.color}` } : undefined}
                    >
                      <Icon className="size-4" style={{ color: on ? t.color : undefined }} aria-hidden />
                    </span>
                    <span className="relative min-w-0">
                      <span className="block truncate text-[13.5px] font-medium">{t.label}</span>
                      <span className="block truncate text-[11px] text-faint">{t.blurb}</span>
                    </span>
                  </button>
                );
              })}
            </nav>
          </GlassPanel>
        </aside>

        <div className="min-w-0">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={active.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.18, ease: 'easeOut' }}
            >
              <active.Component />
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
