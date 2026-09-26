-- Structured payload for Needs Prerit items (probation reviews, decisions with options, go-live items).
ALTER TABLE needs_prerit ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_needs_kind ON needs_prerit(kind, status);
