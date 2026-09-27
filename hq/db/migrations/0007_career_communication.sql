-- Evidence-backed company communication, separate from the application submission state.
ALTER TABLE email_messages ADD COLUMN auth_results TEXT;
ALTER TABLE email_messages ADD COLUMN sender_name TEXT;
ALTER TABLE email_messages ADD COLUMN body_text TEXT;
ALTER TABLE email_threads ADD COLUMN verification TEXT;
ALTER TABLE email_threads ADD COLUMN verification_reasons_json TEXT NOT NULL DEFAULT '[]';
CREATE TABLE IF NOT EXISTS career_profiles (
  opportunity_id TEXT PRIMARY KEY REFERENCES opportunities(id) ON DELETE CASCADE,
  communication_stage TEXT NOT NULL DEFAULT 'applied',
  verification TEXT NOT NULL DEFAULT 'Needs Review',
  verification_reasons_json TEXT NOT NULL DEFAULT '[]',
  verification_sources_json TEXT NOT NULL DEFAULT '[]',
  recruiter_name TEXT,
  recruiter_email TEXT,
  offer_details_json TEXT NOT NULL DEFAULT '{}',
  last_message_id TEXT,
  last_message_at TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS career_events (
  id TEXT PRIMARY KEY,
  opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
  application_id TEXT,
  message_id TEXT REFERENCES email_messages(id),
  stage TEXT NOT NULL,
  action TEXT NOT NULL,
  source TEXT NOT NULL,
  model_id TEXT,
  detail TEXT,
  occurred_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(message_id, action)
);
CREATE INDEX IF NOT EXISTS idx_career_events_opp ON career_events(opportunity_id, occurred_at);
CREATE TABLE IF NOT EXISTS onboarding_items (
  id TEXT PRIMARY KEY,
  opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
  item_key TEXT NOT NULL,
  title TEXT NOT NULL,
  detail TEXT,
  source_message_id TEXT REFERENCES email_messages(id),
  due_text TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  completed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(opportunity_id, item_key)
);
