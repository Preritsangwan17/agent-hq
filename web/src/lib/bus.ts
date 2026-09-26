/**
 * Tiny typed pub/sub used for fire-and-forget visual effects that should not live in React state —
 * e.g. `task.handoff` particles on the agent graph. Emitted by the store after each animation-frame flush.
 */
import type { HandoffData, HQEvent } from './types';

export type Listener<T> = (payload: T) => void;

export interface Emitter<T> {
  on(fn: Listener<T>): () => void;
  emit(payload: T): void;
  readonly size: number;
}

export function createEmitter<T>(): Emitter<T> {
  const listeners = new Set<Listener<T>>();
  return {
    on(fn) {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
    emit(payload) {
      for (const fn of listeners) {
        try {
          fn(payload);
        } catch (err) {
          console.error('[bus] listener failed', err);
        }
      }
    },
    get size() {
      return listeners.size;
    },
  };
}

export interface HandoffPulse extends HandoffData {
  /** event id (unique key for the particle) */
  id: number;
  ts: string;
}

/** `task.handoff` events → edge particles (source agent color). */
export const handoffBus = createEmitter<HandoffPulse>();

/** Every persisted event after it has been applied to the store (e.g. Activity terminal auto-scroll, toasts). */
export const eventBus = createEmitter<HQEvent>();
