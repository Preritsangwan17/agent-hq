ALTER TABLE agent_runs ADD COLUMN ai_mode TEXT;
ALTER TABLE agent_runs ADD COLUMN task_type TEXT;
ALTER TABLE agent_runs ADD COLUMN route_reason TEXT;
ALTER TABLE agent_runs ADD COLUMN execution TEXT;
CREATE INDEX IF NOT EXISTS idx_runs_routing ON agent_runs(started_at) WHERE route_reason IS NOT NULL;
UPDATE settings SET value_json='true' WHERE key='llm_local_enabled';
