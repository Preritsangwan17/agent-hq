/**
 * TanStack Query client + shared hooks for request/response data that is NOT pushed over SSE
 * (opportunity detail, paged events, agents meta, health). Live state lives in the zustand store (store.ts).
 */
import { QueryClient, useQuery } from '@tanstack/react-query';
import { useEffect } from 'react';
import { ApiError, api } from './api';
import { useHQ } from './store';
import type { EventsQuery, OppQuery } from './types';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      refetchOnWindowFocus: false,
      retry: (count, err) => !(err instanceof ApiError && [400, 401, 403, 404, 421].includes(err.status)) && count < 2,
    },
  },
});

export const qk = {
  health: ['health'] as const,
  authStatus: ['auth', 'status'] as const,
  me: ['auth', 'me'] as const,
  opp: (id: string) => ['opp', id] as const,
  opps: (q: OppQuery) => ['opps', q] as const,
  events: (q: EventsQuery) => ['events', q] as const,
  agentsMeta: ['agents', 'meta'] as const,
  needs: (status: string) => ['needs', status] as const,
};

/** GET /api/health every 10 s; mirrors worker liveness into the store. */
export function useHealth() {
  const q = useQuery({ queryKey: qk.health, queryFn: api.health, refetchInterval: 10_000, retry: false });
  const setWorker = useHQ((s) => s.setWorker);
  useEffect(() => {
    if (q.data) {
      setWorker({ alive: q.data.worker_alive, heartbeatAt: q.data.worker_heartbeat_at, version: q.data.version });
    } else if (q.isError) {
      setWorker({ alive: false });
    }
  }, [q.data, q.isError, setWorker]);
  return q;
}

export function useAuthStatus() {
  return useQuery({ queryKey: qk.authStatus, queryFn: api.auth.status, staleTime: 0, retry: 1 });
}

/** Full detail for /o/:id; refetches when the live summary for that id changes (stage/updated_at). */
export function useOpportunityDetail(id: string | undefined) {
  const updatedAt = useHQ((s) => (id ? s.opportunities[id]?.updated_at : undefined));
  const q = useQuery({
    queryKey: qk.opp(id ?? ''),
    queryFn: () => api.opportunity(id!),
    enabled: !!id,
  });
  const { refetch } = q;
  useEffect(() => {
    if (id && updatedAt) void refetch();
  }, [id, updatedAt, refetch]);
  return q;
}

export function useOpportunitiesQuery(query: OppQuery = {}, enabled = true) {
  return useQuery({ queryKey: qk.opps(query), queryFn: () => api.opportunities(query), enabled });
}

export function useEventsQuery(query: EventsQuery = {}, enabled = true) {
  return useQuery({ queryKey: qk.events(query), queryFn: () => api.events(query), enabled });
}

export function useAgentsMeta() {
  return useQuery({ queryKey: qk.agentsMeta, queryFn: api.agentsMeta, staleTime: 5 * 60_000 });
}
