-- Agent HQ schema v1. SQLite (WAL). Timestamps are ISO-8601 UTC strings unless noted.
-- IDs are TEXT ULIDs unless noted. JSON columns end in _json.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);

-- ── settings / control ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL DEFAULT 'system'
);
CREATE TABLE IF NOT EXISTS audit_log (
  id TEXT PRIMARY KEY, ts TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
  target TEXT, before_json TEXT, after_json TEXT, remote_addr TEXT
);
CREATE TABLE IF NOT EXISTS commands (
  id TEXT PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}',
  consumed_at TEXT, result_json TEXT
);

-- ── profile ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS profile_facts (
  id TEXT PRIMARY KEY,                 -- e.g. F-BOOK-FILTER
  category TEXT NOT NULL,              -- edu|project|skill|not_used|preference|contact|citizenship
  project_key TEXT,                    -- book|churn|null
  text TEXT NOT NULL,
  allowed_phrasings_json TEXT NOT NULL DEFAULT '[]',
  evidence_url TEXT, evidence_quote TEXT,
  source TEXT NOT NULL DEFAULT 'fact_sheet',   -- fact_sheet|github|prerit_confirmed
  status TEXT NOT NULL DEFAULT 'verified',     -- verified|pending|retired
  verified_by TEXT, verified_at TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS profile_fields (
  key TEXT PRIMARY KEY, label TEXT NOT NULL, value TEXT,
  share_policy TEXT NOT NULL DEFAULT 'on_request',  -- forms|on_request|never
  confirmed_by_prerit INTEGER NOT NULL DEFAULT 0, required_for_live INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS answer_bank (
  id TEXT PRIMARY KEY, question_pattern TEXT NOT NULL, answer_template TEXT,
  fact_ids_json TEXT NOT NULL DEFAULT '[]', field_keys_json TEXT NOT NULL DEFAULT '[]',
  policy TEXT NOT NULL DEFAULT 'needs_prerit'       -- auto|needs_prerit|never
);

-- ── sources / fetching ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, config_json TEXT NOT NULL DEFAULT '{}',
  automation TEXT NOT NULL DEFAULT 'discover_only',  -- auto|discover_only|manual_lane
  tos_status TEXT NOT NULL DEFAULT 'unreviewed',      -- unreviewed|allowed|restricted|prohibited
  tos_url TEXT, tos_reviewed_at TEXT, poll_interval_min INTEGER NOT NULL DEFAULT 360,
  daily_call_cap INTEGER, last_polled_at TEXT, last_ok_at TEXT,
  consecutive_errors INTEGER NOT NULL DEFAULT 0, disabled_until TEXT,
  enabled INTEGER NOT NULL DEFAULT 0, added_by TEXT NOT NULL DEFAULT 'system', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS domain_policy (
  domain TEXT PRIMARY KEY, robots_txt TEXT, robots_fetched_at TEXT, crawl_delay_s REAL NOT NULL DEFAULT 5,
  allowed INTEGER NOT NULL DEFAULT 1, manual_lane INTEGER NOT NULL DEFAULT 0, last_request_at TEXT
);
CREATE TABLE IF NOT EXISTS http_cache (
  url TEXT PRIMARY KEY, etag TEXT, last_modified TEXT, status INTEGER, fetched_at TEXT, body_path TEXT, sha256 TEXT
);
CREATE TABLE IF NOT EXISTS companies (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, norm_name TEXT NOT NULL, domains_json TEXT NOT NULL DEFAULT '[]',
  ats_kind TEXT, ats_slug TEXT, known_mill INTEGER NOT NULL DEFAULT 0, notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_companies_norm ON companies(norm_name);

-- ── opportunities ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS opportunities (
  id TEXT PRIMARY KEY,
  canonical_key TEXT NOT NULL UNIQUE,
  is_simulated INTEGER NOT NULL DEFAULT 0,
  company_id TEXT REFERENCES companies(id),
  company_name TEXT NOT NULL,
  title TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'internship',   -- internship|job|part_time|contract|freelance|fellowship|program|research_internship
  role_type TEXT,                            -- ml|data|software|research|other
  description_path TEXT, desc_hash TEXT, summary TEXT,
  location_raw TEXT, city TEXT, country_iso2 TEXT, lat REAL, lon REAL,
  work_mode TEXT,                            -- remote|onsite|hybrid|unknown
  url TEXT, apply_url TEXT,
  apply_channel TEXT NOT NULL DEFAULT 'manual',  -- email|ats_form|portal|manual
  apply_email TEXT, apply_email_quote TEXT,
  deadline_at TEXT, deadline_confidence TEXT,    -- high|medium|low|rolling
  posted_at TEXT, start_date TEXT, duration_months REAL, hours_per_week REAL,
  -- pay
  pay_raw TEXT,
  pay_min REAL, pay_max REAL, pay_currency TEXT,
  pay_period TEXT,                           -- hour|day|week|month|year|lump|unknown
  pay_status TEXT NOT NULL DEFAULT 'unknown',-- listed|unknown|variable|unpaid|fee_required
  pay_monthly_local_min REAL, pay_monthly_local_max REAL,
  pay_monthly_inr_min REAL, pay_monthly_inr_mid REAL, pay_monthly_inr_max REAL,
  pay_hourly_inr_min REAL, pay_hourly_inr_max REAL,
  fx_rate REAL, fx_date TEXT,
  benefits_json TEXT NOT NULL DEFAULT '{}',  -- {housing,meals,travel,allowance_inr}
  living_cost_monthly_inr REAL, living_cost_basis TEXT, living_cost_confidence TEXT,
  pay_ratio REAL,
  -- status
  eligibility_status TEXT NOT NULL DEFAULT 'unknown',  -- unknown|eligible|eligible_gaps|ineligible|needs_info|borderline
  eligibility_confidence REAL,
  availability_status TEXT NOT NULL DEFAULT 'unknown', -- unknown|fits|conflict|needs_info
  scam_status TEXT NOT NULL DEFAULT 'unchecked',       -- unchecked|clean|suspicious|scam
  fit_score REAL, fit_breakdown_json TEXT NOT NULL DEFAULT '{}',
  stage TEXT NOT NULL DEFAULT 'found',       -- found|verified|drafted|checked|applied|replied|interview|offer|rejected|filtered|frozen|skipped
  stage_reason TEXT, stage_override INTEGER NOT NULL DEFAULT 0,
  link_status TEXT NOT NULL DEFAULT 'unchecked',       -- unchecked|live|dead|not_automatable
  source_label TEXT, notes_unverified TEXT,
  first_seen_at TEXT NOT NULL, last_verified_at TEXT, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_opp_stage ON opportunities(stage);
CREATE INDEX IF NOT EXISTS idx_opp_updated ON opportunities(updated_at);

CREATE TABLE IF NOT EXISTS opportunity_sources (
  opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
  source_id TEXT NOT NULL, external_id TEXT, source_url TEXT,
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, raw_path TEXT,
  PRIMARY KEY (opportunity_id, source_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_oppsrc_ext ON opportunity_sources(source_id, external_id);

CREATE TABLE IF NOT EXISTS eligibility_checks (
  id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
  method TEXT NOT NULL, model_id TEXT, requirements_json TEXT NOT NULL DEFAULT '{}', quotes_json TEXT NOT NULL DEFAULT '[]',
  verdict TEXT NOT NULL, confidence REAL, run_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scam_checks (
  id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
  signals_json TEXT NOT NULL DEFAULT '[]', verdict TEXT NOT NULL, run_id TEXT, created_at TEXT NOT NULL
);

-- ── applications / documents / gates ───────────────────────────────
CREATE TABLE IF NOT EXISTS applications (
  id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
  channel TEXT NOT NULL DEFAULT 'manual',
  status TEXT NOT NULL DEFAULT 'drafting',   -- drafting|checking|awaiting_approval|queued|submitted|needs_prerit|failed|withdrawn|historical_frozen|skipped
  mode TEXT NOT NULL DEFAULT 'dry_run',      -- dry_run|self_test|live
  letter_doc_id TEXT, resume_doc_id TEXT, answers_json TEXT NOT NULL DEFAULT '{}', gates_json TEXT NOT NULL DEFAULT '{}',
  approval_sha256 TEXT, approved_by TEXT, approved_at TEXT,
  submitted_at TEXT, submission_ref TEXT, gmail_thread_id TEXT, message_id TEXT,
  followup_due_at TEXT, followup_sent_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_app_opp ON applications(opportunity_id);

CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, application_id TEXT REFERENCES applications(id) ON DELETE CASCADE,
  opportunity_id TEXT REFERENCES opportunities(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,     -- cover_letter|cold_email|research_statement|profile_summary|form_answers|resume_html|resume_pdf|compact_pdf|followup|reply
  version INTEGER NOT NULL DEFAULT 1, parent_id TEXT, content_path TEXT, content_text TEXT, sha256 TEXT,
  author_agent TEXT, author_model TEXT, lineage_models_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'draft',      -- draft|checking|passed|failed|sent|historical
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_sentences (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  idx INTEGER NOT NULL, text TEXT NOT NULL, kind TEXT, fact_ids_json TEXT NOT NULL DEFAULT '[]',
  job_quote_ids_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS fact_checks (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE, sentence_id TEXT,
  layer TEXT NOT NULL, checker_model TEXT, verdict TEXT NOT NULL, rule_ids_json TEXT NOT NULL DEFAULT '[]',
  unsupported_span TEXT, explanation TEXT, run_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gate_results (
  id TEXT PRIMARY KEY, application_id TEXT, document_id TEXT, gate TEXT NOT NULL, passed INTEGER NOT NULL,
  details_json TEXT NOT NULL DEFAULT '{}', ts TEXT NOT NULL
);

-- ── agents / models ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY, config_path TEXT NOT NULL, config_hash TEXT NOT NULL, config_json TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1, paused INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'idle',       -- idle|working|paused|error|stuck|offline|disabled
  restarts INTEGER NOT NULL DEFAULT 0, tasks_today INTEGER NOT NULL DEFAULT 0, errors_today INTEGER NOT NULL DEFAULT 0,
  tokens_today INTEGER NOT NULL DEFAULT 0, counters_date TEXT, probation_runs_left INTEGER NOT NULL DEFAULT 0,
  last_error TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_live (
  agent_id TEXT PRIMARY KEY, now_line TEXT, progress REAL, current_task_id TEXT, opportunity_id TEXT,
  model_id TEXT, tok_s REAL, heartbeat_at TEXT, updated_at TEXT NOT NULL, seq INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS models (
  id TEXT PRIMARY KEY, runtime TEXT NOT NULL, name TEXT NOT NULL, path TEXT, revision TEXT, model_type TEXT, arch TEXT,
  quant TEXT, params_b REAL, size_bytes INTEGER, ctx_len INTEGER, modality TEXT NOT NULL DEFAULT 'chat',
  complete INTEGER NOT NULL DEFAULT 0, incomplete_reason TEXT, runtime_supported INTEGER NOT NULL DEFAULT 0,
  supports_json_schema INTEGER NOT NULL DEFAULT 0, est_ram_gb REAL, measured_ram_gb REAL,
  status TEXT NOT NULL DEFAULT 'available',  -- available|loaded|broken|unsupported
  pinned INTEGER NOT NULL DEFAULT 0, fingerprint TEXT, discovered_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_servers (
  id TEXT PRIMARY KEY, model_id TEXT NOT NULL, pid INTEGER, port INTEGER, started_at TEXT, last_used_at TEXT,
  footprint_gb REAL, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS benchmarks (
  id TEXT PRIMARY KEY, model_id TEXT NOT NULL, suite_version TEXT NOT NULL, task TEXT NOT NULL, n INTEGER,
  accuracy REAL, precision REAL, recall REAL, f1 REAL, json_valid_first REAL, json_valid_after_repair REAL,
  tok_s_gen REAL, tok_s_prompt REAL, ttft_ms REAL, peak_footprint_gb REAL, details_path TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS role_assignments (
  role TEXT NOT NULL, model_id TEXT NOT NULL, rank INTEGER NOT NULL, score REAL, source TEXT NOT NULL DEFAULT 'auto',
  reason TEXT, created_at TEXT NOT NULL, PRIMARY KEY (role, rank)
);

-- ── task queue / runs / events ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY, type TEXT NOT NULL, capability TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}',
  opportunity_id TEXT, application_id TEXT, priority INTEGER NOT NULL DEFAULT 50,
  status TEXT NOT NULL DEFAULT 'queued',     -- queued|leased|running|succeeded|failed|dead|deferred_budget|waiting_memory|cancelled
  escalation_level INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 4,
  not_before TEXT, lease_owner TEXT, lease_expires_at TEXT, heartbeat_at TEXT,
  idempotency_key TEXT UNIQUE, parent_task_id TEXT, source_agent TEXT,
  result_json TEXT, last_error TEXT, error_signature TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_ready ON tasks(status, not_before, priority);
CREATE INDEX IF NOT EXISTS idx_tasks_opp ON tasks(opportunity_id);

CREATE TABLE IF NOT EXISTS agent_runs (
  id TEXT PRIMARY KEY, task_id TEXT, parent_run_id TEXT, escalated_from_run_id TEXT, agent_id TEXT NOT NULL,
  adapter TEXT NOT NULL, model_id TEXT, input_path TEXT, output_path TEXT, prompt_tokens INTEGER, completion_tokens INTEGER,
  tok_s REAL, ttft_ms REAL, cost_usd REAL, duration_ms INTEGER, status TEXT NOT NULL, error TEXT,
  started_at TEXT NOT NULL, finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_task ON agent_runs(task_id);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, type TEXT NOT NULL,
  level TEXT NOT NULL DEFAULT 'info',        -- debug|info|warn|error|alert
  agent_id TEXT, opportunity_id TEXT, task_id TEXT, message TEXT NOT NULL, data_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_agent ON events(agent_id, id);

CREATE TABLE IF NOT EXISTS claude_usage (
  id TEXT PRIMARY KEY, run_id TEXT, task_type TEXT, date_local TEXT NOT NULL, model TEXT, input_tokens INTEGER,
  output_tokens INTEGER, cache_read_tokens INTEGER, cost_usd_est REAL, reserved_usd REAL, subtype TEXT, created_at TEXT NOT NULL
);

-- ── email / outbound ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS email_threads (
  id TEXT PRIMARY KEY, gmail_thread_id TEXT UNIQUE, opportunity_id TEXT, application_id TEXT, subject TEXT,
  counterpart_domain TEXT, classification TEXT, notify_only_lock INTEGER NOT NULL DEFAULT 0, lock_reason TEXT,
  status TEXT NOT NULL DEFAULT 'open', last_message_at TEXT
);
CREATE TABLE IF NOT EXISTS email_messages (
  id TEXT PRIMARY KEY, gmail_message_id TEXT UNIQUE, thread_id TEXT REFERENCES email_threads(id), direction TEXT NOT NULL,
  from_addr TEXT, to_addr TEXT, date TEXT, subject TEXT, snippet TEXT, body_path TEXT, classification TEXT,
  confidence REAL, handled_run_id TEXT
);
CREATE TABLE IF NOT EXISTS outbound_log (
  id TEXT PRIMARY KEY, channel TEXT NOT NULL, recipient_domain TEXT, recipient_hash TEXT, application_id TEXT,
  mode TEXT NOT NULL, message_id TEXT, status TEXT NOT NULL DEFAULT 'intent',  -- intent|sent|failed|ambiguous
  ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mock_mailbox (
  id TEXT PRIMARY KEY, to_addr TEXT NOT NULL, subject TEXT, body TEXT, attachments_json TEXT NOT NULL DEFAULT '[]',
  in_reply_to TEXT, application_id TEXT, created_at TEXT NOT NULL
);

-- ── human lane / notifications / strategy ──────────────────────────
CREATE TABLE IF NOT EXISTS needs_prerit (
  id TEXT PRIMARY KEY, opportunity_id TEXT, application_id TEXT,
  kind TEXT NOT NULL,   -- submit_form|approve|missing_info|review_letter|decision|captcha|login|interview|offer|assessment|legal|money|confirm_legacy
  title TEXT NOT NULL, instructions_md TEXT, answers_json TEXT NOT NULL DEFAULT '[]', files_json TEXT NOT NULL DEFAULT '[]',
  direct_url TEXT, priority INTEGER NOT NULL DEFAULT 50, due_at TEXT, est_minutes REAL,
  status TEXT NOT NULL DEFAULT 'open',       -- open|done|snoozed|dismissed
  snoozed_until TEXT, created_at TEXT NOT NULL, resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS notifications (
  id TEXT PRIMARY KEY, severity TEXT NOT NULL, title TEXT NOT NULL, body TEXT, url TEXT,
  mac_delivered INTEGER NOT NULL DEFAULT 0, acknowledged_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strategy_reports (
  date TEXT PRIMARY KEY, report_md TEXT, proposed_actions_json TEXT NOT NULL DEFAULT '[]',
  applied_actions_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL
);
