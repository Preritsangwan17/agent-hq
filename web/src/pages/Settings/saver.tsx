/**
 * Optimistic settings writes for the Settings page.
 * `save(patch, debounceMs)` merges the patch into the live store immediately, batches keys into one
 * PATCH /api/settings (debounced for sliders / typing), keeps keys that changed again while a request was in
 * flight, and on failure rolls every key of the failed batch back to its pre-edit value.
 * Freeze-outbound goes through POST /api/control/freeze-outbound (same optimistic pattern).
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { api } from '@/lib/api';
import { useHQ } from '@/lib/store';
import type { Settings } from '@/lib/types';
import type { SaveStatus } from './controls';

export interface SaveState {
  status: SaveStatus;
  at: number | null;
  error: string | null;
}

interface SaverApi {
  state: SaveState;
  save: (patch: Partial<Settings>, debounceMs?: number) => void;
  setFreeze: (on: boolean) => Promise<void>;
}

const SaverContext = createContext<SaverApi | null>(null);

export function useSaver(): SaverApi {
  const ctx = useContext(SaverContext);
  if (!ctx) throw new Error('useSaver must be used inside <SettingsSaverProvider>');
  return ctx;
}

function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function SettingsSaverProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SaveState>({ status: 'idle', at: null, error: null });
  const pending = useRef<Partial<Settings>>({});
  const rollback = useRef<Partial<Settings>>({});
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const inflight = useRef(0);

  const flush = useCallback(async () => {
    clearTimeout(timer.current);
    timer.current = undefined;
    const patch = pending.current;
    const before = rollback.current;
    if (!Object.keys(patch).length) return;
    pending.current = {};
    rollback.current = {};
    inflight.current += 1;
    setState((s) => ({ ...s, status: 'saving', error: null }));
    try {
      const r = await api.patchSettings(patch);
      // don't clobber keys the user changed again while this request was in flight
      const fresh: Record<string, unknown> = { ...r.settings };
      for (const k of Object.keys(pending.current)) delete fresh[k];
      useHQ.getState().mergeSettings(fresh as Partial<Settings>);
      inflight.current -= 1;
      if (inflight.current === 0 && !timer.current) setState({ status: 'saved', at: Date.now(), error: null });
    } catch (e) {
      inflight.current -= 1;
      const restore: Record<string, unknown> = { ...before };
      for (const k of Object.keys(pending.current)) delete restore[k];
      useHQ.getState().mergeSettings(restore as Partial<Settings>);
      setState({ status: 'error', at: Date.now(), error: errMessage(e) });
    }
  }, []);

  const save = useCallback(
    (patch: Partial<Settings>, debounceMs = 0) => {
      const st = useHQ.getState();
      const rb = rollback.current as Record<string, unknown>;
      for (const k of Object.keys(patch)) if (!(k in rb)) rb[k] = st.settings[k];
      st.mergeSettings(patch);
      Object.assign(pending.current, patch);
      clearTimeout(timer.current);
      timer.current = undefined;
      if (debounceMs > 0) {
        setState((s) => ({ ...s, status: 'saving', error: null }));
        timer.current = setTimeout(() => void flush(), debounceMs);
      } else {
        void flush();
      }
    },
    [flush],
  );

  const setFreeze = useCallback(async (on: boolean) => {
    const st = useHQ.getState();
    const prev = st.settings.freeze_outbound;
    st.mergeSettings({ freeze_outbound: on });
    setState((s) => ({ ...s, status: 'saving', error: null }));
    try {
      const r = await api.freezeOutbound(on);
      useHQ.getState().mergeSettings({ freeze_outbound: r.freeze_outbound });
      setState({ status: 'saved', at: Date.now(), error: null });
    } catch (e) {
      useHQ.getState().mergeSettings({ freeze_outbound: prev });
      setState({ status: 'error', at: Date.now(), error: errMessage(e) });
    }
  }, []);

  // flush a pending debounced edit when leaving the page
  useEffect(() => () => void flush(), [flush]);

  const value = useMemo(() => ({ state, save, setFreeze }), [state, save, setFreeze]);
  return <SaverContext.Provider value={value}>{children}</SaverContext.Provider>;
}
