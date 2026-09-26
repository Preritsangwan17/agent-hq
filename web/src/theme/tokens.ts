/**
 * Design tokens for JS consumers (React Flow nodes, Recharts, canvas/SVG). The same values are exposed to Tailwind
 * as CSS variables in src/index.css (`bg-bg`, `text-ink`, `text-muted`, `text-agent-scout`, `text-gold` …).
 * Rules: red (`danger`) only for errors and the kill switch; gold only for pay; animate only transform/opacity.
 */
import type { AgentStatus, Mode, Stage } from '@/lib/types';

export const colors = {
  bg: '#070B14',
  surface1: '#0D1422',
  surface2: '#121826',
  ink: '#E6EAF2',
  muted: '#8B95A7',
  faint: '#5B6577',
  line: 'rgba(255,255,255,0.10)',
  danger: '#EF4444',
  gold: '#F5C451',
  goldDeep: '#E3A33B',
  /** pay ratio bands */
  ratioGood: '#34D399',
  ratioOk: '#FBBF24',
  ratioLow: '#F87171',
  ok: '#34D399',
  warn: '#FBBF24',
} as const;

export const goldGradient = 'linear-gradient(135deg, #FFE08A 0%, #F5C451 45%, #E3A33B 100%)';

export const fonts = {
  display: '"Space Grotesk Variable", ui-sans-serif, system-ui, sans-serif',
  sans: '"Inter Variable", ui-sans-serif, system-ui, sans-serif',
  mono: '"JetBrains Mono Variable", ui-monospace, SFMono-Regular, Menlo, monospace',
} as const;

export interface AgentPreset {
  id: string;
  name: string;
  color: string;
  emoji: string;
}

/** Starting team (CONTRACT §6). Agents from the API carry their own color/avatar; these are fallbacks. */
export const AGENT_PRESETS: readonly AgentPreset[] = [
  { id: 'scout', name: 'Scout', color: '#22D3EE', emoji: '🛰️' },
  { id: 'verifier', name: 'Verifier', color: '#2DD4BF', emoji: '🔎' },
  { id: 'writer', name: 'Writer', color: '#A78BFA', emoji: '✍️' },
  { id: 'factchecker', name: 'Fact-Checker', color: '#F59E0B', emoji: '🧪' },
  { id: 'reviewer', name: 'Reviewer (Claude)', color: '#FB7185', emoji: '🧠' },
  { id: 'resume', name: 'Résumé Builder', color: '#60A5FA', emoji: '📄' },
  { id: 'applicant', name: 'Applicant', color: '#F472B6', emoji: '🚀' },
  { id: 'inbox', name: 'Inbox Watcher', color: '#A3E635', emoji: '📬' },
  { id: 'followup', name: 'Follow-up', color: '#FB923C', emoji: '⏰' },
  { id: 'strategist', name: 'Strategist (Claude)', color: '#E879F9', emoji: '🧭' },
];

export const AGENT_COLORS: Readonly<Record<string, string>> = Object.fromEntries(
  AGENT_PRESETS.map((a) => [a.id, a.color]),
);

/** Palette offered for user-created agents (distinct from red/gold). */
export const AGENT_PALETTE: readonly string[] = [
  '#22D3EE', '#2DD4BF', '#A78BFA', '#F59E0B', '#FB7185', '#60A5FA', '#F472B6', '#A3E635', '#FB923C', '#E879F9',
  '#38BDF8', '#818CF8', '#4ADE80', '#C084FC',
];

export function agentColor(id: string | null | undefined, fallback = '#94A3B8'): string {
  return (id && AGENT_COLORS[id]) || fallback;
}

/** `#RRGGBB` (or `#RGB`) → `rgba(r,g,b,a)`. Non-hex input is returned unchanged. */
export function withAlpha(hex: string, alpha: number): string {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return hex;
  let h = m[1];
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  const n = parseInt(h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}

export interface StageMeta {
  label: string;
  color: string;
  /** position in the main flow; terminal/side stages are >= 100 */
  order: number;
  terminal: boolean;
}

export const STAGE_META: Readonly<Record<Stage, StageMeta>> = {
  found: { label: 'Found', color: '#22D3EE', order: 0, terminal: false },
  verified: { label: 'Verified', color: '#2DD4BF', order: 1, terminal: false },
  drafted: { label: 'Drafted', color: '#A78BFA', order: 2, terminal: false },
  checked: { label: 'Checked', color: '#818CF8', order: 3, terminal: false },
  applied: { label: 'Applied', color: '#F472B6', order: 4, terminal: false },
  replied: { label: 'Replied', color: '#A3E635', order: 5, terminal: false },
  interview: { label: 'Interview', color: '#E879F9', order: 6, terminal: false },
  offer: { label: 'Offer', color: '#4ADE80', order: 7, terminal: true },
  rejected: { label: 'Rejected', color: '#64748B', order: 100, terminal: true },
  filtered: { label: 'Filtered', color: '#526077', order: 101, terminal: true },
  frozen: { label: 'Frozen', color: '#93C5FD', order: 102, terminal: true },
  skipped: { label: 'Skipped', color: '#6B7280', order: 103, terminal: true },
};

/** Main kanban flow, left → right. */
export const PIPELINE_STAGES: readonly Stage[] = [
  'found', 'verified', 'drafted', 'checked', 'applied', 'replied', 'interview', 'offer',
];
/** Side lanes (collapsed "Filtered" column etc.). */
export const SIDE_STAGES: readonly Stage[] = ['filtered', 'rejected', 'frozen', 'skipped'];

export const AGENT_STATUS_META: Readonly<Record<AgentStatus, { label: string; color: string }>> = {
  idle: { label: 'Idle', color: '#8B95A7' },
  working: { label: 'Working', color: '#34D399' },
  paused: { label: 'Paused', color: '#FBBF24' },
  error: { label: 'Error', color: '#EF4444' },
  stuck: { label: 'Stuck', color: '#FB923C' },
  offline: { label: 'Offline', color: '#5B6577' },
  disabled: { label: 'Disabled', color: '#5B6577' },
};

export const MODE_META: Readonly<Record<Mode, { label: string; color: string; hint: string }>> = {
  dry_run: { label: 'DRY RUN', color: '#22D3EE', hint: 'Nothing leaves this Mac — mock mailer and mock ATS only.' },
  self_test: { label: 'SELF-TEST', color: '#FBBF24', hint: 'Real sends only to your own address.' },
  live: { label: 'LIVE', color: '#4ADE80', hint: 'Gated applications are sent for real.' },
};

export const KIND_LABEL: Readonly<Record<string, string>> = {
  internship: 'Internship',
  research_internship: 'Research internship',
  job: 'Job',
  part_time: 'Part-time',
  contract: 'Contract',
  freelance: 'Freelance',
  fellowship: 'Fellowship',
  program: 'Program',
};
