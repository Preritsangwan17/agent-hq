/** Route guard: GET /api/auth/me → render children, 401 → /login?next=…, network failure → retry screen. */
import { useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router';
import { ApiError, api } from '@/lib/api';
import { qk } from '@/lib/queries';
import { BootScreen } from './BootScreen';

export function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation();
  const me = useQuery({
    queryKey: qk.me,
    queryFn: api.auth.me,
    retry: false,
    staleTime: 60_000,
    refetchInterval: (q) => (q.state.status === 'error' && (q.state.error as ApiError)?.status !== 401 ? 5_000 : false),
  });

  if (me.isPending) return <BootScreen label="Checking session…" />;
  if (me.isError) {
    const err = me.error as ApiError;
    if (err.status === 401) {
      const next = location.pathname + location.search;
      return <Navigate to={`/login${next && next !== '/' ? `?next=${encodeURIComponent(next)}` : ''}`} replace />;
    }
    return <BootScreen error={err.message} onRetry={() => void me.refetch()} />;
  }
  return <>{children}</>;
}
