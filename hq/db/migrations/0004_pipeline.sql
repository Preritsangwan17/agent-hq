-- Phase (c): the real pipeline (dry run).
-- Every network request the fetcher makes (or refuses) is logged; acceptance checks assert GET-only traffic to
-- allowed sources and zero manual-lane domains.
CREATE TABLE IF NOT EXISTS fetch_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, method TEXT NOT NULL, url TEXT NOT NULL,
  domain TEXT NOT NULL, status INTEGER, bytes INTEGER, from_cache INTEGER NOT NULL DEFAULT 0, source_id TEXT,
  blocked_reason TEXT, duration_ms INTEGER
);
CREATE INDEX IF NOT EXISTS idx_fetch_domain ON fetch_log(domain, ts);

ALTER TABLE opportunities ADD COLUMN parse_json TEXT;                          -- JobParse from parse.job
ALTER TABLE opportunities ADD COLUMN job_quotes_json TEXT NOT NULL DEFAULT '[]';  -- verified exact quotes
ALTER TABLE opportunities ADD COLUMN automation TEXT NOT NULL DEFAULT 'auto';  -- auto|discover_only|manual_lane
ALTER TABLE opportunities ADD COLUMN company_domain TEXT;
ALTER TABLE opportunities ADD COLUMN requirements_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE applications ADD COLUMN pack_need_id TEXT;
ALTER TABLE applications ADD COLUMN doc_kind TEXT;
ALTER TABLE documents ADD COLUMN subject TEXT;

CREATE INDEX IF NOT EXISTS idx_docs_opp ON documents(opportunity_id, kind, version);
CREATE INDEX IF NOT EXISTS idx_factchecks_doc ON fact_checks(document_id);
CREATE INDEX IF NOT EXISTS idx_gates_app ON gate_results(application_id, gate);
CREATE INDEX IF NOT EXISTS idx_outbound_domain ON outbound_log(recipient_domain, ts);
