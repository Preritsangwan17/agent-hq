/**
 * Authenticated app shell (layout route): backdrop, sidebar / mobile tab bar, header with kill switch,
 * paused banner + vignette, and the routed page. Boots the live connection (snapshot → SSE) and health polling;
 * pages render once the first snapshot has loaded.
 */
import { motion } from 'motion/react';
import { Suspense, useCallback, useEffect } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router';
import { api, setUnauthorizedHandler } from '@/lib/api';
import { usePersistentState } from '@/lib/hooks';
import { queryClient, useHealth } from '@/lib/queries';
import { loadSnapshot, useHQ } from '@/lib/store';
import { hqStream, useLiveConnection } from '@/lib/stream';
import { BootScreen, PageFallback } from './BootScreen';
import { Header, PausedBanner, PausedVignette } from './Header';
import { MobileTabBar } from './MobileTabBar';
import { titleFor } from './nav';
import { Sidebar } from './Sidebar';

export function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = usePersistentState('hq.sidebar.collapsed', false);
  const ready = useHQ((s) => s.ready);
  const loadError = useHQ((s) => s.loadError);

  useLiveConnection();
  useHealth();

  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (window.location.pathname.startsWith('/login')) return;
      hqStream.stop();
      queryClient.removeQueries({ queryKey: ['auth'] });
      const next = window.location.pathname + window.location.search;
      navigate(`/login?next=${encodeURIComponent(next)}`, { replace: true });
    });
  }, [navigate]);

  useEffect(() => {
    document.title = `${titleFor(location.pathname)} · Agent HQ`;
  }, [location.pathname]);

  const logout = useCallback(async () => {
    try {
      await api.auth.logout();
    } finally {
      hqStream.stop();
      queryClient.clear();
      navigate('/login', { replace: true });
    }
  }, [navigate]);

  return (
    <div className="relative min-h-dvh overflow-x-clip">
      <div className="hq-backdrop" aria-hidden />
      <div className="relative z-10 flex min-h-dvh">
        <Sidebar
          className="hidden md:flex"
          collapsed={collapsed}
          onToggle={() => setCollapsed((c) => !c)}
          onLogout={logout}
        />
        <div className="flex min-w-0 flex-1 flex-col">
          <Header />
          <PausedBanner />
          <main className="mx-auto w-full max-w-[1680px] flex-1 px-4 pb-28 pt-4 md:px-6 md:pb-12 md:pt-6 lg:px-8">
            {ready ? (
              <motion.div
                key={location.pathname}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.2, ease: 'easeOut' }}
              >
                <Suspense fallback={<PageFallback />}>
                  <Outlet />
                </Suspense>
              </motion.div>
            ) : (
              <BootScreen
                inline
                label="Syncing with HQ…"
                error={loadError ? `Can't load the snapshot: ${loadError}` : null}
                onRetry={() => void loadSnapshot().catch(() => undefined)}
              />
            )}
          </main>
        </div>
      </div>
      <MobileTabBar className="md:hidden" onLogout={logout} />
      <PausedVignette />
    </div>
  );
}
