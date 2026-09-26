# Agent HQ — Contract F: local-first AI, cloud providers, usage & limits, career-plan match score

Supersedes the cloud-model parts of PLAN.md and CONTRACT_B–E, and the fit score of CONTRACT_C.

## 1. Engines and switches (`hq/llm/policy.py`, `hq/llm/cloud.py`)
- Settings: `local_ai_enabled`, `cloud_ai_enabled` (master), `claude_cli_enabled`, `codex_cli_enabled` (both opt-in),
  `grok_enabled`, `prefer_subscriptions` (default true), `cloud_mode` = `saver` (default) | `balanced` | `quality`.
- `POST /api/ai/engines {engines: both|local|cloud|none}` sets the two masters; `PATCH /api/settings` sets the rest;
  `POST /api/models/{id}/enabled` switches one local model (switched-off models are never routed to and are unloaded).
- Provider order: claude → codex → xai (subscriptions before pay-per-token), or xai first when
  `prefer_subscriptions` is off. Each provider has a fast and a strong model (`claude_cli_model`/`claude_cli_strong_model`,
  `codex_model`, `xai_model`/`xai_signoff_model`).
- Policy (`escalate`, `polish`, `signoff`) decides whether a cloud model may answer and which tier:
  saver = only when no local model can do the task, or for the final sign-off when no second independent local
  checker exists; unclear eligibility becomes a one-click decision; no optional polish. balanced adds the third
  opinion, polish of important letters (match ≥ `important_score_threshold`) and strong sign-off for them. quality =
  strong sign-off and polish of every high-fit letter.
- The router tries the role's local ladder, then providers in order; a rate limit, logout or full window hands over to
  the next provider. Final sign-off prefers a second local fact-checker that meets the floor and is neither an author
  nor the layer-(b) checker.

## 2. Providers
- **Claude CLI** (`hq/llm/claude_cli.py`): `claude -p` with no tools/MCP/hooks/slash commands/session, empty sandbox,
  minimal env, redacted prompt on stdin, JSON schema. Recorded at $0 (`cost_source=subscription`, the CLI's figure kept
  as `notional_usd`). A usage-limit answer pauses the provider until the parsed reset (default 1 h).
- **Codex CLI** (`hq/llm/codex_cli.py`): `codex exec --json --skip-git-repo-check --sandbox read-only --color never
  -C <sandbox> --output-last-message <f> [--output-schema <f>] [-m model] -` (falls back to prompt-only JSON when the
  CLI rejects the schema flag). Rate-limit snapshots found in its JSON events (`used_percent`, `window_minutes`,
  `resets_in_seconds`) are kept as reported windows.
- **Grok** (`hq/llm/xai.py`): chat completions with `response_format` JSON schema; exact cost from
  `usage.cost_in_usd_ticks` when present, else the price table; `GET /v1/api-key` for key status (no balance);
  `x-ratelimit-*` headers kept when sent.
- Subscription CLIs: at most `<provider>_window_calls` (default 30) HQ calls per rolling 5 hours. Grok: daily $ limit
  `cloud_daily_budget_usd` (default 2) and `cloud_daily_call_cap` (40), per-call cap `cloud_per_call_cap_usd`.

## 3. Usage & limits (`GET /api/usage`, page `/usage`)
Grok today / month / 30 days / all time, by model and task, recent calls, each labelled exact (reported by xAI) or
estimated; HQ's daily limit left (exact); remaining credit = the balance Prerit entered (`grok_credit_usd`) minus spend
since (always labelled an estimate); share of AI calls handled locally and an estimate of what that saved. Per
provider: switch, reachability, HQ's own 5-hour/7-day usage and window cap (exact), reported windows with reset times
(only when the CLI reported them, otherwise "not reported").

## 4. Local models (`config/local_models.yaml`, `hq/models/catalog.py`)
Recommended set for an M4 Pro with 48 GB (core: qwen3:30b-a3b, gemma3:12b, phi4:14b, qwen3:4b; optional: mistral-small3.2,
gemma3:27b, llama3.1:8b). `GET /api/models/recommended`, `POST /api/models/pull {name}` (catalog names only; the worker
calls Ollama's `/api/pull` and publishes progress), `make models` / `scripts/pull_models.sh`. Pool budget 32 GB.

## 5. Match score (`config/career.yaml`, `hq/pipeline/verify/score.py`)
Twelve factors, each 0–100 with a reason, weighted to 100: skills 12, projects 8, education 7, experience 7, location 12,
visa 9, role type 6, compensation 7, company 8, AI/ML relevance 12, eligibility 6, career value 6. Regions: Europe,
Russia, Canada, Australia (priority 1; European countries ranked), India (priority 2), elsewhere 40 unless unusually
relevant (AI relevance ≥ 90 and career value ≥ 80 lifts location to 70). Tracks: core AI/ML, stepping stone, other.
Verdict: apply ≥ `fit_draft_threshold` (60), consider ≥ 45, skip below. Drafts are prioritised by score;
`POST /api/opportunities/{id}/apply-anyway` pushes a parked match through (all gates still run). Stored in
`fit_breakdown_json` (`version: 2`).

## 6. Data
Migration 0006: `claude_usage` → `cloud_usage` (+ `cost_source`, `provider`, `notional_usd`), `models.enabled`, renamed
settings keys (`cloud_daily_budget_usd`, `cloud_daily_call_cap`, `cloud_per_call_cap_usd`, `signoff_required`,
`cloud_state`), role reason `needs_cloud_signoff`, adapter `claude_code` → `cloud`.
