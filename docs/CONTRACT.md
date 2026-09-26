# Agent HQ — Phase (a) build contract

> **Update (Sept 2026):** the cloud layer described here was replaced by local-first routing with optional providers (Claude CLI, ChatGPT Codex CLI, Grok) and API-saving mode; the fit score by the career-plan match score. See `docs/CONTRACT_F.md`. Where this contract says "Claude" as HQ's cloud model, read "a cloud model per hq.llm.policy".

Single source of truth for parallel builders. Backend = Python 3.11 (`.venv`, run with `uv run` or `.venv/bin/python`),
FastAPI + SQLite (WAL). Frontend = `web/` (Vite + React 19 + TS + Tailwind v4 + motion). Read `PLAN.md` for the why.
Schema: `hq/db/migrations/0001_init.sql` (do not change column names without updating this file).

## 0. Hard rules (every builder)
- Truthfulness/safety: phase (a) is **simulation + legacy import only**. No real network POSTs, no email, no browser
  automation. The sim Applicant writes only to `mock_mailbox`. Legacy applications are `historical_frozen`.
- Simulated rows have `opportunities.is_simulated=1`; UI shows a small "SIM" tag on them. Legacy rows `is_simulated=0`.
- Secrets only in `.env` (never commit). Never log the passcode, cookies or tokens.
- Times: store ISO-8601 UTC (`2026-09-26T13:45:00Z`); display in Asia/Kolkata in the UI.
- IDs: ULID strings (`hq/util/ids.py: new_id()`), except `events.id` (integer autoincrement).

## 1. Processes, ports, files
- `python -m hq.supervisor` spawns `python -m hq.api` (uvicorn on 127.0.0.1:8765, or 0.0.0.0 if `HQ_LAN=1`) and
  `python -m hq.worker`; restarts children with exponential backoff (1s→60s), pidfile `data/run/supervisor.pid`,
  spawns `caffeinate -i -w <pid>` when setting `keep_awake` is true. SIGTERM → graceful stop of children.
- `./start.sh [-f]` (doctor → `uv sync` → build web if `web/src` newer than `web/dist` → migrate → start supervisor
  detached, or foreground with -f → print URL). `./stop.sh`. `Makefile`: up, down, dev, test, screens, fmt.
- DB file `data/hq.db` (WAL, `busy_timeout=5000`, `foreign_keys=ON`). Runtime dirs: `data/run`, `data/logs`, `data/artifacts`.
- The API serves the built SPA from `web/dist` at `/` (SPA fallback to index.html for non-/api paths).
- Dev: `npm run dev` in `web/` on :5173 with Vite proxy `/api` → `http://127.0.0.1:8765` (keep Host header as-is).

## 2. Auth (all `/api/*` except `/api/health`, `/api/auth/status`, `/api/auth/login`, `/api/auth/setup`)
- `.env`: `HQ_PASSCODE_HASH=scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>`, `HQ_SESSION_SECRET=<random 32B hex>`.
  `start.sh` creates `HQ_SESSION_SECRET` if missing. No passcode yet → `GET /api/auth/status` returns
  `{configured:false}`; `POST /api/auth/setup {passcode}` allowed **only from loopback** and only when unconfigured;
  writes the hash to `.env` (min length 6).
- `POST /api/auth/login {passcode}` → sets cookie `hq_session` (itsdangerous TimestampSigner, HttpOnly, SameSite=Strict,
  Path=/, max_age 30 days). 5 attempts/minute/IP. `POST /api/auth/logout`. `GET /api/auth/me` → `{ok:true}`.
- Host allowlist (ignore port): `localhost`, `127.0.0.1`, `::1`, plus `HQ_ALLOWED_HOSTS` (comma list) when `HQ_LAN=1`.
  Reject others with 421. Mutating methods (POST/PATCH/PUT/DELETE) require header `X-HQ: 1` **and** an `Origin`
  whose host is allowlisted (dev origin `http://localhost:5173` allowed). SSE also requires the cookie.
- Loopback-only routes (checked by client IP): `/api/auth/setup`, anything under `/api/control/golive*` (future),
  and agent creation with `adapter: script`.

## 3. REST API (JSON; errors `{error: string, detail?: any}`)
| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | /api/health | – | `{ok, worker_alive, worker_heartbeat_at, version}` (no auth) |
| GET | /api/snapshot | – | `Snapshot` (below) |
| GET | /api/stream | header `Last-Event-ID` or `?after=` | SSE (section 4) |
| GET | /api/events | `after, before, limit(≤500), agent, level, type, q` | `{events: Event[]}` newest last |
| GET | /api/opportunities | `stage, q, sim(0/1), limit` | `{items: OppSummary[]}` |
| GET | /api/opportunities/{id} | – | `OppDetail` |
| PATCH | /api/opportunities/{id}/stage | `{stage, reason}` | `OppSummary` (sets `stage_override=1`, audit + event; **never** triggers actions) |
| GET | /api/agents | – | `{agents: Agent[]}` |
| GET | /api/agents/meta | – | `{capabilities: Capability[], adapters: string[], reserved_side_effects: string[], palette: string[]}` |
| POST | /api/agents | `AgentConfig` (without side-effect caps) | `Agent` (writes `agents/<id>.yaml`; hot reload picks it up) |
| PATCH | /api/agents/{id} | `{paused?, enabled?, model?, concurrency?, schedule?, name?, avatar?, color?}` | `Agent` (pause/enable stored in DB; config edits rewrite YAML) |
| DELETE | /api/agents/{id} | – | `{ok}` (renames YAML to `.yaml.disabled`; built-ins cannot be deleted, only disabled) |
| POST | /api/control/pause-all | `{reason?}` | `{paused:true}` |
| POST | /api/control/resume-all | `{confirm:"RESUME"}` | `{paused:false}` |
| POST | /api/control/freeze-outbound | `{on: bool}` | `{freeze_outbound}` |
| GET | /api/settings | – | `{settings: Record<string, any>}` |
| PATCH | /api/settings | `{key: value, ...}` (whitelisted keys only) | `{settings}` |
| GET | /api/needs | `status=open` | `{items: Need[]}` |
| PATCH | /api/needs/{id} | `{status: done|snoozed|dismissed, snooze_hours?}` | `Need` |
| GET | /api/stats | – | `Stats` |
| POST | /api/sim/reset | – | purges `is_simulated=1` rows (dev convenience) |

### Settings keys (defaults, seeded by migration code)
`global_pause:false, freeze_outbound:false, mode:"dry_run" (dry_run|self_test|live — UI read-only in phase a),
autonomy:"auto" (auto|approve_first), sim_enabled:true, sim_speed:1.0 (0.25–4), keep_awake:true,
eligibility_threshold:0.8, min_pay_ratio:1.0, funded_program_min_inr:5000, fit_draft_threshold:60,
fit_polish_threshold:75, daily_draft_cap:20, cloud_daily_budget_usd:2.0, cloud_daily_call_cap:40,
email_daily_cap:10, quiet_hours:{enabled:false,start:"23:00",end:"07:00"}, unknown_pay_policy:"decision"`.

## 4. SSE `/api/stream`
- Each persisted event row is sent as `event: <type>`, `id: <events.id>`, `data: <Event JSON>`.
- Ephemeral agent-live updates (not in `events`): `event: agent.live`, no id, `data: AgentLive`. Sent when
  `agent_live.seq` changes (poll 200 ms), max ~4/s per agent.
- Keepalive comment every 15 s. On reconnect with `Last-Event-ID`, replay events with id > that (max 500), else send
  `event: resync` and the client refetches `/api/snapshot`.
- Event types (data = Event with type-specific `data`):
  - `agent.status` `{status}` · `agent.added|agent.updated|agent.removed` `{agent: Agent}`
  - `task.created|task.leased|task.succeeded|task.failed|task.retry|task.dead|task.escalated` `{task_id, capability, agent_id?, attempt?}`
  - `task.handoff` `{from_agent, to_agent, capability, opportunity_id}` → drives edge particles
  - `opp.created` `{opp: OppSummary}` · `opp.stage` `{opp: OppSummary, from, to}` · `opp.updated` `{opp: OppSummary}`
  - `control.pause` `{paused, reason}` · `control.freeze` `{freeze_outbound}` · `settings.updated` `{settings}`
  - `needs.created|needs.updated` `{need: Need}` · `notification` `{severity,title,body,url}`
  - `mail.mock_sent` `{to, subject, application_id}` (sim only)
  - `worker.heartbeat` (every 10 s, level debug) · `worker.started|worker.stopped`
  - `log` (generic line for the Activity terminal: message + optional data)

## 5. JSON shapes (TypeScript notation)
```ts
type Agent = { id; name; avatar; color; role; adapter; model: string|null; capabilities: string[]; cost_tier: 'local'|'cloud'|'external';
  concurrency: number; schedule: {mode:'on_demand'|'interval'|'cron', minutes?, cron?}; enabled: boolean; paused: boolean;
  status: 'idle'|'working'|'paused'|'error'|'stuck'|'offline'|'disabled'; builtin: boolean; side_effects: string[];
  tasks_today: number; errors_today: number; tokens_today: number; restarts: number; last_error: string|null;
  live: AgentLive|null; description: string };
type AgentLive = { agent_id; now_line: string|null; progress: number|null /*0..1*/; current_task_id; opportunity_id;
  model_id; tok_s: number|null; heartbeat_at; updated_at };
type Event = { id: number; ts; type; level: 'debug'|'info'|'warn'|'error'|'alert'; agent_id; opportunity_id; task_id; message; data: any };
type Pay = { raw: string|null; status: 'listed'|'unknown'|'variable'|'unpaid'|'fee_required'; min; max; currency; period;
  monthly_inr_min; monthly_inr_mid; monthly_inr_max; hourly_inr_min; hourly_inr_max; fx_rate; fx_date;
  living_cost_monthly_inr; living_cost_basis; living_cost_confidence: 'high'|'medium'|'low'|'provisional'|null;
  ratio: number|null; benefits: {housing?:boolean, meals?:boolean, travel?:boolean, allowance_inr?:number} };
type OppSummary = { id; company_name; title; kind; role_type; city; country_iso2; lat; lon; work_mode; stage; stage_reason;
  is_simulated: boolean; fit_score: number|null; eligibility_status; scam_status; deadline_at; deadline_confidence;
  pay: Pay; url; apply_channel; source_label; active_agent_id: string|null; needs_prerit: boolean; updated_at; first_seen_at };
type OppDetail = OppSummary & { summary; notes_unverified; applications: Application[]; documents: Document[];
  timeline: Event[]; gates: any[]; eligibility_checks: any[]; needs: Need[] };
type Application = { id; channel; status; mode; submitted_at; created_at };
type Document = { id; kind; version; status; author_agent; author_model; content_text; created_at; file_url: string|null };
type Need = { id; opportunity_id; kind; title; instructions_md; answers: {label,value,copy?:boolean}[]; files: {name,path}[];
  direct_url; priority; due_at; est_minutes; status; created_at };
type Stats = { found; verified; drafted; applied; replies; interviews; offers; rejected; filtered; success_rate: number|null;
  needs_open; cloud_cost_today_usd; cloud_budget_usd; cloud_calls_today; local_tokens_today;
  pay: { pipeline_median_inr: number|null; pipeline_max_inr: number|null; best_offer_inr: number|null; median_applied_inr: number|null };
  by_stage: Record<string, number>; sim: boolean };
type Snapshot = { settings; agents: Agent[]; opportunities: OppSummary[]; events: Event[] /* last 200 */; stats: Stats;
  needs: Need[]; server_time; last_event_id: number };
```
Pay semantics: `ratio = monthly_inr_min / living_cost_monthly_inr` (null if either unknown). Hourly with unknown hours →
`status:'variable'`, only `hourly_inr_*` set. Funded program: `benefits` set + allowance.

## 6. Agent YAML (`agents/<id>.yaml`), validated by pydantic `hq/agents/schema.py:AgentConfig`
```yaml
id: scout                  # ^[a-z][a-z0-9_-]{1,31}$ ; file name must match
name: Scout
avatar: "🛰️"               # single emoji or lucide icon name
color: "#22D3EE"
role: scout                # free text role key (used for model auto-assign in phase b)
description: Finds opportunities on ATS boards, program pages and alert emails.
adapter: sim               # sim | script | openai_compatible | cloud | http | browser
adapter_config: {}         # adapter-specific
model: null                # null|auto|"mlx:<repo>"
capabilities: [discover.ats, discover.program_page, parse.job]
cost_tier: local           # local|cloud|external
concurrency: 1
schedule: {mode: interval, minutes: 1}   # on_demand | interval | cron
enabled: true
builtin: true
```
- Reserved side-effect capabilities: `apply.email_send`, `apply.ats_submit`, `reply.send`, `followup.send`. Only the
  built-in agents `applicant`, `inbox`, `followup` may declare them; loader rejects others. Pausing an agent that owns a
  side-effect capability pauses that capability system-wide (tasks wait; never rerouted).
- Hot reload: watchfiles on `agents/`; valid change → upsert `agents` row + `agent.added|updated` event within 3 s;
  invalid file → `error` event, previous config kept; deleted/`.disabled` → drain then `agent.removed`.

### Capability vocabulary (phase a uses the starred ones via the sim adapter)
discover.ats* discover.feed discover.program_page* discover.email_alerts parse.job* classify.title
verify.link* verify.deadline* verify.eligibility* verify.eligibility_hard verify.pay* verify.scam* score.fit*
draft.cover_letter* draft.cold_email draft.research_statement draft.form_answers draft.followup polish.final
factcheck.deterministic* factcheck.sentence* factcheck.signoff* check.quality* build.resume*
apply.email_send* apply.ats_submit apply.manual_pack* inbox.poll* inbox.classify* reply.draft reply.send
followup.schedule* followup.send strategy.daily_review* debug.failed_run summarize

### Starting team (ids, colors, emoji)
| id | name | color | emoji | sim capabilities |
|---|---|---|---|---|
| scout | Scout | #22D3EE | 🛰️ | discover.ats, discover.program_page, parse.job |
| verifier | Verifier | #2DD4BF | 🔎 | verify.link, verify.deadline, verify.eligibility, verify.pay, verify.scam, score.fit |
| writer | Writer | #A78BFA | ✍️ | draft.cover_letter |
| factchecker | Fact-Checker | #F59E0B | 🧪 | factcheck.deterministic, factcheck.sentence, check.quality |
| reviewer | Reviewer | #FB7185 | 🧠 | factcheck.signoff |
| resume | Résumé Builder | #60A5FA | 📄 | build.resume |
| applicant | Applicant | #F472B6 | 🚀 | apply.email_send, apply.manual_pack |
| inbox | Inbox Watcher | #A3E635 | 📬 | inbox.poll, inbox.classify |
| followup | Follow-up | #FB923C | ⏰ | followup.schedule |
| strategist | Strategist | #E879F9 | 🧭 | strategy.daily_review |

## 7. Orchestrator semantics (worker)
- Loop every 500 ms: consume `commands`; read settings; if `global_pause` → do not lease, cancel running cooperatively
  (runs call `ctx.check_cancel()` at least every second); otherwise dispatch.
- Dispatch: ready tasks (`status='queued' AND (not_before IS NULL OR not_before<=now)`) by `priority DESC, created_at`.
  Candidate agents: enabled, not paused, has capability, running < concurrency, and the capability is not paused system-wide.
  Lease atomically (`UPDATE ... WHERE id=? AND status='queued'`), lease 90 s, heartbeat every 15 s extends it.
- Retry: failure → attempts+1; if < max_attempts → `queued` with `not_before = now + min(2^attempts*5s + jitter, 1h)`
  and event `task.retry`; else `dead` + event `task.dead` (level error).
- Watchdog every 5 s: expired leases → requeue; agent heartbeat stale > 60 s while working → status `stuck`, cancel,
  event (warn); worker writes `worker.heartbeat` event every 10 s and `settings.worker_heartbeat_at`.
- Scheduler: `interval`/`cron` agents get a task for their first schedulable capability when due (coalesce missed runs).
- Pipeline transitions in `hq/pipeline/state.py` (pure function `next_tasks(stage, capability, result) -> (new_stage, [TaskSpec])`),
  applied in the same transaction as task success; emits `opp.stage` and `task.handoff` (from the finishing agent to the
  agent that will likely take the next capability).

## 8. Simulation (phase a)
- `sim` adapter produces realistic, clearly-simulated work: Scout (interval ~ every 25–60 s ÷ sim_speed) creates 1–2
  opportunities from a curated pool of plausible AI/ML roles (mix of countries: IN, US, DE, CH, TW, JP, SG, GB, CA, AE, NL;
  kinds incl. internship, part_time, contract, fellowship, program; pay in local currencies incl. unknown/hourly/funded
  program cases; ~10% scam/mill, ~15% ineligible (e.g. "2026 graduates only"), ~5% expired).
- Each task: 2–8 s ÷ sim_speed, progress updates 3–6 times, `now_line` like "Reading EPFL Summer Research page…",
  plausible `tok_s` (local 40–370, claude null) and token counts; 5% transient failure to exercise retries.
- Stage flow: found → (verify) verified | filtered → (draft) drafted → (factcheck + signoff) checked → (resume, apply)
  applied (mock mailbox for email channel; manual pack → a `needs_prerit` item `submit_form`) → (inbox, sim reply after
  delay) replied → interview (creates alert `needs_prerit` kind `interview`, **no action**) | rejected | offer (alert).
- Stop creating new sim opps when there are > 60 non-terminal sim opps. `POST /api/sim/reset` purges them.

## 9. Legacy import (`python -m hq.importer.legacy --src <dir>`), idempotent
- Source dir = the old `applications/` folder (`jobs.json`, `letters.py`, `drafts/`, `NN-*/`). Default `legacy/applications`.
- For each of the 10 jobs + the TEEP item from `letters.py` (`07-nccu-teep` → **National Chung Cheng University (CCU)**,
  MARS lab, `apply_email=cychiu@ccu.edu.tw`, TEEP NT$15,000/month minimum, re-verify flag):
  opportunity (`is_simulated=0`, `stage='frozen'`, `source_label='legacy shortlist 2026-09-26'`, `notes_unverified` = old
  `angle`), application `status='historical_frozen'`, documents (`status='historical'`: the letter text; resume PDF path),
  pay normalised (section 5). `07-codingninjas` → `stage='skipped'`, reason "dropped; no final letter".
- One `needs_prerit` item kind `confirm_legacy`: "Which of these 11 legacy applications did you actually send?"
- Pay parsing examples (must pass tests): "INR 25,000/month"; "INR 25,000 - 40,000/month"; "USD 13.25 - 27.50/hour (...)"
  → variable, hourly INR only; "Not listed" → unknown; "Need-based stipend..." → unknown; "NT$15,000/month" → TWD.
- FX: `hq/pipeline/verify/fx.py` — Frankfurter (`https://api.frankfurter.dev/v1/latest?base=USD` and v2 for currencies ECB
  lacks, e.g. TWD); cache `data/fx/rates.json` (date-stamped); fallback `config/fx_seed.json` (marked seed). GET only.
- Living cost: `config/living_costs.csv` columns `key,country_iso2,city,monthly_inr,basis,confidence,source_note,as_of`.
  Phase (a) values are **provisional estimates** (confidence `provisional`, source_note says so; researched in phase c).

## 10. File ownership for parallel builders
- backend-core: `hq/{settings.py,supervisor.py,__init__.py}`, `hq/db/*` (not the SQL), `hq/api/*`, `hq/worker/*`,
  `hq/agents/*`, `hq/adapters/*`, `hq/pipeline/state.py`, `hq/sim/*`, `hq/util/*`, `agents/*.yaml`, `start.sh`, `stop.sh`,
  `Makefile`, `.env.example`, `tests/unit/test_{db,orchestrator,auth,agents,api,sim}*.py`.
- backend-data: `hq/importer/*`, `hq/pipeline/verify/{__init__,pay,fx,living_cost}.py`, `hq/pipeline/__init__.py`,
  `config/{fx_seed.json,living_costs.csv}`, `tests/unit/test_{pay,fx,living_cost,importer}*.py`, `README.md` (initial).
- frontend: everything under `web/`.
