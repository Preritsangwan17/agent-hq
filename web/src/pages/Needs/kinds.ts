/**
 * Presentation metadata per `Need.kind`: icon, label, accent and the wording of the "Done" action.
 * Alert kinds (interview/offer/legal/money) are notify-only: agents never act on them.
 */
import {
  Banknote,
  CircleCheck,
  CircleQuestionMark,
  ClockArrowLeft,
  FileInput,
  FileText,
  Gavel,
  Handshake,
  KeyRound,
  ListChecks,
  Scale,
  ShieldAlert,
  Sparkles,
  Trophy,
  Reply,
  type LucideIcon,
} from 'lucide-react';
import type { NeedKind } from '@/lib/types';

export type AlertTone = 'gold' | 'red';

export interface KindMeta {
  label: string;
  icon: LucideIcon;
  color: string;
  /** label of the "done" action */
  done: string;
  /** notify-only alert styling */
  alert?: AlertTone;
  /** short safety note shown on the card */
  note?: string;
}

export const GOLD = '#F5C451';
export const ALERT_RED = '#F87171';

const KINDS: Record<string, KindMeta> = {
  submit_form: { label: 'Submit form', icon: FileInput, color: '#22D3EE', done: 'I submitted it' },
  approve: { label: 'Approve', icon: CircleCheck, color: '#A78BFA', done: 'Approve & queue' },
  missing_info: { label: 'Missing info', icon: CircleQuestionMark, color: '#60A5FA', done: 'Done' },
  review_letter: { label: 'Review letter', icon: FileText, color: '#A78BFA', done: 'Looks good' },
  decision: { label: 'Decision', icon: Scale, color: '#2DD4BF', done: 'Keep it' },
  captcha: {
    label: 'CAPTCHA',
    icon: ShieldAlert,
    color: '#FB923C',
    done: 'Done',
    note: 'Agents never solve CAPTCHAs or bypass bot checks.',
  },
  login: {
    label: 'Login needed',
    icon: KeyRound,
    color: '#FB923C',
    done: 'Done',
    note: 'Agents never enter passwords or create accounts.',
  },
  assessment: {
    label: 'Assessment',
    icon: ListChecks,
    color: '#F472B6',
    done: 'I handled it',
    note: 'Agents never attempt assessments or tests — the thread is notify-only.',
    alert: 'red',
  },
  confirm_legacy: { label: 'Confirm legacy', icon: ClockArrowLeft, color: '#93C5FD', done: 'Done' },
  approve_reply: { label: 'Reply draft', icon: Reply, color: '#22D3EE', done: 'Send reply' },
  interview: { label: 'Interview', icon: Handshake, color: ALERT_RED, done: 'I handled it', alert: 'red' },
  offer: { label: 'Offer', icon: Trophy, color: GOLD, done: 'I handled it', alert: 'gold' },
  legal: { label: 'Legal', icon: Gavel, color: ALERT_RED, done: 'I handled it', alert: 'red' },
  money: { label: 'Money', icon: Banknote, color: GOLD, done: 'I handled it', alert: 'gold' },
};

const FALLBACK: KindMeta = { label: 'Task', icon: Sparkles, color: '#8B95A7', done: 'Done' };

export function kindMeta(kind: NeedKind | string): KindMeta {
  return KINDS[kind] ?? { ...FALLBACK, label: kind.replace(/[_-]+/g, ' ').replace(/^\w/, (c) => c.toUpperCase()) };
}

export function isAlertKind(kind: string): boolean {
  return !!KINDS[kind]?.alert;
}

/** Filter groups for the lane toolbar. */
export type NeedFilter = 'all' | 'alerts' | 'forms' | 'decisions' | 'other';

export function filterOf(kind: string): Exclude<NeedFilter, 'all'> {
  if (isAlertKind(kind)) return 'alerts';
  if (kind === 'submit_form' || kind === 'captcha' || kind === 'login' || kind === 'assessment') return 'forms';
  if (kind === 'decision' || kind === 'approve' || kind === 'approve_reply' || kind === 'review_letter' || kind === 'confirm_legacy') return 'decisions';
  return 'other';
}
