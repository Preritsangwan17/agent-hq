-- Inline JSON summaries of each agent run's input and output (the *_path columns stay for full payload files).
ALTER TABLE agent_runs ADD COLUMN input_json TEXT;
ALTER TABLE agent_runs ADD COLUMN output_json TEXT;
CREATE INDEX IF NOT EXISTS idx_runs_agent_started ON agent_runs(agent_id, started_at);
CREATE INDEX IF NOT EXISTS idx_events_opp ON events(opportunity_id, id);
CREATE INDEX IF NOT EXISTS idx_needs_status ON needs_prerit(status);
CREATE INDEX IF NOT EXISTS idx_tasks_source ON tasks(source_agent, created_at);
