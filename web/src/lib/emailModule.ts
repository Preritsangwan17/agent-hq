import { http } from './api';

export type EmailMode = 'sandbox' | 'live';
export interface EmailApplication {
  id: string; source_opportunity_id: string | null; company: string; role: string; contact_name: string;
  email: string; status: string; research: string; job_description: string; profile: Record<string, string>;
  last_email_sent: string | null; reply_received: boolean; next_followup_at: string | null;
  followup_count: number; links: string[]; deadlines: string[]; gmail_thread_id: string | null;
  updated_at: string;
}
export interface EmailDraft {
  id: string; kind: string; subject: string; body: string; status: string; approved: boolean;
  message_id: string | null; error: string | null; created_at: string; sent_at: string | null;
}
export interface EmailDetail {
  application: EmailApplication;
  drafts: EmailDraft[];
  messages: { gmail_id: string; direction: string; subject: string; body: string; from_addr: string; received_at: string; classification: string }[];
  events: { id: number; kind: string; detail: string; at: string }[];
}
export interface EmailDashboard {
  mode: EmailMode; connected: boolean; gmail_configured: boolean; live_send_enabled: boolean;
  applications: EmailApplication[];
  counts: { applications: number; waiting: number; replies: number; followups_due: number };
  policy: { per_day: number; minimum_gap_seconds: number; followup_after_days: number; maximum_followups: number; approval_required: boolean };
}

const q = (mode: EmailMode) => ({ mode });
const enc = encodeURIComponent;
const base = '/api/email-module';

export const emailModuleApi = {
  dashboard: (mode: EmailMode) => http.get<EmailDashboard>(base, q(mode)),
  detail: (id: string, mode: EmailMode) => http.get<EmailDetail>(`${base}/applications/${enc(id)}`, q(mode)),
  create: (body: { company: string; role: string; contact_name: string; email: string; research: string; job_description: string; profile: Record<string, string> }, mode: EmailMode) =>
    http.post<EmailApplication>(`${base}/applications?mode=${mode}`, body),
  importOpportunity: (id: string, mode: EmailMode) => http.post<EmailApplication>(`${base}/import/${enc(id)}?mode=${mode}`),
  update: (id: string, body: Partial<EmailApplication>, mode: EmailMode) => http.patch<EmailApplication>(`${base}/applications/${enc(id)}?mode=${mode}`, body),
  draft: (id: string, kind: 'application' | 'followup' | 'reply', mode: EmailMode) =>
    http.post<EmailDraft>(`${base}/applications/${enc(id)}/draft?mode=${mode}`, { kind }),
  approve: (id: string, mode: EmailMode) => http.post<EmailDraft>(`${base}/drafts/${enc(id)}/approve?mode=${mode}`),
  send: (id: string, mode: EmailMode) => http.post<EmailDraft>(`${base}/drafts/${enc(id)}/send?mode=${mode}`),
  reconcile: (id: string, mode: EmailMode) => http.post<EmailDraft>(`${base}/drafts/${enc(id)}/reconcile?mode=${mode}`),
  sync: (mode: EmailMode) => http.post<{ fetched: number; imported: number }>(`${base}/sync?mode=${mode}`),
  search: (query: string, mode: EmailMode) => http.get<{ messages: { id: string; from: string; subject: string; snippet: string; date: string }[] }>(`${base}/search`, { q: query, mode }),
  simulateReply: (application_id: string, subject: string, body: string) =>
    http.post<{ gmail_message_id: string }>(`${base}/sandbox/reply`, { application_id, subject, body }),
};
