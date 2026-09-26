-- 0006: local models first; cloud providers (Claude CLI, Codex CLI, Grok) each switchable; per-model on/off.
ALTER TABLE claude_usage RENAME TO cloud_usage;
ALTER TABLE cloud_usage ADD COLUMN cost_source TEXT;   -- reported (exact, from xAI) | estimated | subscription
ALTER TABLE cloud_usage ADD COLUMN provider TEXT;      -- xai | claude | codex (NULL = rows from before: xai)
ALTER TABLE cloud_usage ADD COLUMN notional_usd REAL;  -- a subscription CLI's API-equivalent figure (not spend)
CREATE INDEX IF NOT EXISTS idx_cloud_usage_provider ON cloud_usage(provider, created_at);
CREATE INDEX IF NOT EXISTS idx_cloud_usage_date ON cloud_usage(date_local);
ALTER TABLE models ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1;   -- Prerit's on/off switch per local model

UPDATE OR IGNORE settings SET key='cloud_daily_budget_usd' WHERE key='claude_daily_budget_usd';
UPDATE OR IGNORE settings SET key='cloud_daily_call_cap' WHERE key='claude_daily_call_cap';
UPDATE OR IGNORE settings SET key='cloud_per_call_cap_usd' WHERE key='claude_per_call_cap_usd';
UPDATE OR IGNORE settings SET key='signoff_required' WHERE key='require_claude_signoff';
UPDATE OR IGNORE settings SET key='cloud_state' WHERE key='claude_state';
DELETE FROM settings WHERE key IN ('claude_daily_budget_usd', 'claude_daily_call_cap', 'claude_per_call_cap_usd',
                                   'require_claude_signoff', 'claude_state', 'claude_model', 'claude_signoff_model',
                                   'cloud_llm');

UPDATE role_assignments SET reason = replace(reason, 'needs_claude_signoff', 'needs_cloud_signoff')
 WHERE reason LIKE '%needs_claude_signoff%';
UPDATE agents SET config_json = replace(replace(config_json, '"claude_code"', '"cloud"'), '"cost_tier": "claude"',
                                        '"cost_tier": "cloud"')
 WHERE config_json LIKE '%claude%';
UPDATE agent_runs SET adapter = 'cloud' WHERE adapter = 'claude_code';
UPDATE commands SET kind = 'cloud_recheck' WHERE kind = 'claude_recheck' AND consumed_at IS NULL;
