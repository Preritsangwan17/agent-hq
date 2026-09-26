-- Phase (d): Gmail inbox, locks, follow-ups, notifications, go-live.
ALTER TABLE email_threads ADD COLUMN counterpart_addr TEXT;
ALTER TABLE email_threads ADD COLUMN locked_at TEXT;
ALTER TABLE email_threads ADD COLUMN unlocked_at TEXT;
ALTER TABLE email_threads ADD COLUMN alert_ack_at TEXT;
ALTER TABLE email_threads ADD COLUMN created_at TEXT;
ALTER TABLE email_messages ADD COLUMN rfc822_message_id TEXT;
ALTER TABLE email_messages ADD COLUMN in_reply_to TEXT;
ALTER TABLE email_messages ADD COLUMN lock_terms_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE email_messages ADD COLUMN reason TEXT;
ALTER TABLE documents ADD COLUMN email_thread_id TEXT;
ALTER TABLE outbound_log ADD COLUMN thread_id TEXT;
ALTER TABLE outbound_log ADD COLUMN gmail_id TEXT;
ALTER TABLE outbound_log ADD COLUMN error TEXT;
ALTER TABLE outbound_log ADD COLUMN subject TEXT;
ALTER TABLE applications ADD COLUMN reviewed_at TEXT;

-- Exactly one follow-up per application (CONTRACT_D §4).
CREATE TABLE IF NOT EXISTS followups (
  id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL UNIQUE REFERENCES applications(id) ON DELETE CASCADE,
  opportunity_id TEXT, to_addr TEXT, due_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'scheduled',   -- scheduled|sent|skipped|blocked|failed
  reason TEXT, document_id TEXT, outbound_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_followups_due ON followups(status, due_at);
CREATE INDEX IF NOT EXISTS idx_msgs_thread ON email_messages(thread_id, date);
CREATE INDEX IF NOT EXISTS idx_msgs_rfc822 ON email_messages(rfc822_message_id);
CREATE INDEX IF NOT EXISTS idx_outbound_msgid ON outbound_log(message_id);
CREATE INDEX IF NOT EXISTS idx_notifications_pending ON notifications(mac_delivered, created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_ack ON notifications(acknowledged_at, created_at);
