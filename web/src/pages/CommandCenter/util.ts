/** Small display helpers shared by the Command Center widgets. */
import type { Agent, HQEvent } from '@/lib/types';
import { AGENT_STATUS_META, agentColor } from '@/theme/tokens';

/** Visual state of an agent on this page (global pause wins over everything). */
export type VisualState = 'working' | 'idle' | 'error' | 'paused' | 'off';

export function visualState(agent: Agent | undefined, globalPause: boolean): VisualState {
  if (!agent) return 'off';
  if (globalPause) return 'paused';
  if (agent.status === 'error' || agent.status === 'stuck') return 'error';
  if (agent.paused || agent.status === 'paused') return 'paused';
  if (!agent.enabled || agent.status === 'disabled' || agent.status === 'offline') return 'off';
  if (agent.status === 'working') return 'working';
  return 'idle';
}

export const STATE_META: Record<VisualState, { label: string; color: string }> = {
  working: { label: 'Working', color: AGENT_STATUS_META.working.color },
  idle: { label: 'Idle', color: AGENT_STATUS_META.idle.color },
  error: { label: 'Error', color: AGENT_STATUS_META.error.color },
  paused: { label: 'Paused', color: AGENT_STATUS_META.paused.color },
  off: { label: 'Offline', color: AGENT_STATUS_META.offline.color },
};

export function stateLabel(agent: Agent | undefined, state: VisualState): string {
  if (state === 'error' && agent?.status === 'stuck') return 'Stuck';
  if (state === 'off' && agent && (!agent.enabled || agent.status === 'disabled')) return 'Disabled';
  return STATE_META[state].label;
}

/** "Scout (local)" → "Scout" (the model line already names the model). */
export function shortName(name: string): string {
  return name.replace(/\s*\([^)]*\)\s*$/, '') || name;
}

/**
 * Compact model label: "mlx:mlx-community/Qwen3-4B-Instruct-2507-4bit" → "Qwen3-4B",
 * "xai:grok-4-fast" → "Grok 4 Fast", null → "no LLM".
 */
export function modelLabel(model: string | null | undefined): string {
  if (!model) return 'no LLM';
  if (model === 'auto') return 'auto-assigned';
  const i = model.indexOf(':');
  const provider = i > 0 ? model.slice(0, i) : '';
  const rest = i > 0 ? model.slice(i + 1) : model;
  if (provider === 'xai') return grokLabel(rest);
  const name = (rest.split('/').pop() ?? rest)
    .replace(/-(\d+bit|bf16|fp16|mxfp4|q\d\w*)$/i, '')
    .replace(/-(instruct|chat|it)\b.*$/i, '');
  return name || rest;
}

/** "grok-4-fast" → "Grok 4 Fast" */
export function grokLabel(name: string): string {
  return name
    .replace(/^xai:/, '')
    .split('-')
    .map((w) => (w ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(' ');
}

export function eventAgentColor(e: HQEvent, colorOf: (id: string) => string | undefined): string {
  if (e.agent_id) return colorOf(e.agent_id) ?? agentColor(e.agent_id);
  return '#8B95A7';
}
