# Agent HQ — PLAN

## Context
Prerit (2nd-year B.Tech CSE AI/ML, Bennett University) wants a local-first "mission control" website: his own AI-powered internship
and job agent. A team of local LLMs on his Mac (free, private) finds, checks and applies to AI/ML/data/software
internships, jobs and funded programs around the clock. Cloud models are optional and used only when they add value:
the Claude CLI and ChatGPT's Codex CLI on his subscriptions first, then pay-per-token Grok (see docs/CONTRACT_F.md,
which supersedes this plan wherever they differ).

The agents only apply when four safety gates pass:
- **Fact:** every claim traces to Prerit's verified facts.
- **Eligibility:** the role accepts a current 2nd-year student.
- **Quality:** the letter is specific to that company or lab.
- **Scam:** no fees or other scam signals.

Anything a website won't allow to be automated goes to a "Needs Prerit" lane, pre-filled so it takes under 2 minutes.

The previous session produced reusable work:
- A verified fact sheet (the `FACTS` string in `draft_letters.py`).
- A 10-item shortlist (`jobs.json`).
- Fact-checked letters (`letters.py`).
- Tailored résumé PDFs (`build.py` plus Chrome headless).
- A compact fpdf résumé (the script that made it was lost; re-implement it).
- 10 local-model drafts that invented claims ("deploy", "full-stack", "production-like"). These become gold test data for the fact gate.

**Location (answered):** `~/Documents/agent-hq`, a git repo. Step 0 copies everything there first. The current folder is a
temporary workspace, and the fixtures in `/private/tmp/...scratchpad` are cleared on reboot.

### Honest expectations (shapes the design)
- **Full automation mainly means email.**
  - Greenhouse, Lever and Ashby expose public job-read APIs but no candidate apply API.
  - Their hosted forms use invisible reCAPTCHA or hCaptcha.
  - LinkedIn, Internshala, Indeed, Naukri, Wellfound and YC ban bots in their terms.
  - So automatic submission covers email applications (labs, TEEP professors, programs and companies that publish an apply address). ATS forms and banned sites become Needs Prerit packs.
  - Browser auto-submit is built and tested only against a local mock ATS in v1.
- **Local models, measured on this Mac:**
  - Five complete chat models: Qwen3-Coder-30B-A3B-4bit (about 94 tok/s, 17 GB), Qwen2.5-7B, Qwen3-4B-2507, Qwen2.5-3B, Qwen3-0.6B.
  - Five are broken or incomplete: Qwen2.5-14B, Qwen2.5-1.5B, and three Qwen3.5-2B variants.
  - There is no Ollama, no LM Studio and no GGUF file (llama-server is installed but has nothing to serve).
- **Fact correction found:** the code keeps users with `value_counts() > 200`. The fact therefore becomes "more than 200 ratings", not "200+", and the résumé and letters are regenerated.
- **Pay is shown everywhere** (Prerit's last ask). Every item carries ₹/month, its original currency, and a pay-vs-living-cost ratio.

## Stack and environment
- **Backend:** a uv venv on the already-installed Python 3.11.15, with these packages:
  - `mlx-lm` (latest; reuses `~/.cache/huggingface/hub`, so nothing is re-downloaded)
  - `fastapi`, `uvicorn`, `sse-starlette`, `pydantic`, `httpx`, `psutil`, `rapidfuzz`, `selectolax`, `pyyaml`, `croniter`, `jsonschema`, `watchfiles`
  - `fpdf2`, `pypdf`, `google-api-python-client`, `google-auth-oauthlib`, `playwright` (using the installed Chrome via `channel="chrome"`, so no browser download)
  - Tests: `pytest`, `pytest-asyncio`, `respx`
- **Frontend:** Vite + React + TypeScript, Tailwind v4, `motion` (Framer Motion).
  - Visuals: `@xyflow/react` for the agent graph, `d3-geo` + `topojson-client` + `world-atlas` for an offline 2D glowing map (an optional 3D `react-globe.gl` toggle comes in phase e), `recharts`.
  - State and UI: zustand, TanStack Query, react-virtuoso, lucide.
  - Fonts, self-hosted: Space Grotesk, Inter, JetBrains Mono.
  - Node 26 with npm; node@22 is the fallback.
- **Cloud models (optional):** the Claude CLI (headless `claude -p`), ChatGPT's Codex CLI (`codex exec`) and Grok via xAI's API — each switchable; see docs/CONTRACT_F.md.
- **Ports:** 8765 (app), 5173 (dev), 8799 (mock ATS), 8101–8120 (model servers).

## Architecture
```
launchd (KeepAlive, RunAtLoad) → hq.supervisor (restarts children w/ backoff; caffeinate -i -w pid)
  ├─ hq-api    FastAPI :8765  REST commands · SSE /api/stream · serves built SPA · auth on every route
  ├─ hq-worker asyncio: Scheduler · Dispatcher · Watchdog · Agent runners · ModelManager · CloudRunner
  │            · SideEffectGuard · BrowserWorker(Playwright, 1 at a time)
  ├─ mlx_lm.server ×N  (one process per hot model, OpenAI-compatible, managed by ModelManager)
  └─ mock-ats :8799 (dry-run/dev only)
SQLite (WAL) data/hq.db = state + task queue + event bus (worker writes events in same txn; api tails → SSE)
```
- Commands (pause, approve, settings) are REST calls that write rows. The worker picks them up within 500 ms.
- SSE updates are coalesced per animation frame in a zustand store, targeting 60 fps.

## Repo layout (key parts)
```
~/Documents/agent-hq/  start.sh stop.sh Makefile README.md PLAN.md .env.example pyproject.toml
  agents/*.yaml  agents/scripts/   prompts/*.md  schemas/*.json
  config/ sources.yaml manual_lane.yaml banned_claims.yaml tech_terms.yaml cliches.yaml scam_lexicon.yaml
          known_mills.yaml answer_bank.yaml doc_types.yaml living_costs.csv cloud_prices.yaml
  hq/ supervisor.py settings.py db/ api/ worker/ agents/ adapters/ llm/ models/{discovery,benchmark}/
      pipeline/{discover,verify,gates,apply}/ profile/ resume/ gmail/ notify/ importer/ strategist/ util/
  mock_ats/  web/  tests/{unit,integration,fixtures}/  scripts/ launchd/  legacy/  data/ (gitignored, 700)
```
**Reused code:**
- `build.py`'s `TAILOR`, `resume_html()` and Chrome `--headless=new --print-to-pdf` call go into `hq/resume/builder.py`.
- The fpdf layout becomes `hq/resume/compact.py`.
- `draft_letters.py`'s mlx_lm usage and `FACTS` go into `hq/profile/facts.py` as atomic fact IDs.
- `letters.py` and `drafts/` become gold fixtures.
- `scratchpad/scan.py` (ATS scanner) goes into `hq/pipeline/discover/{greenhouse,lever,ashby}.py`, with the title regex fixed. It currently matches "Internal" and "International".

## Data model (SQLite, WAL)
**Settings and audit**
- `settings`: mode, autonomy, thresholds, caps, pause.
- `audit_log`.
- `commands`: UI to worker.

**Profile**
- `profile_facts`:
  - id (e.g. `F-BOOK-FILTER`), text, allowed phrasings, evidence (GitHub permalink at a commit SHA), status (verified/pending/retired).
  - GitHub-derived facts start `pending` until Prerit confirms them.
- `profile_fields`:
  - phone, CGPA/marks, grad year, semester, city, availability windows, hours cap, passport, DOB/address.
  - `share_policy` (forms/on_request/never) and `confirmed_by_prerit`. **Unconfirmed values are never used in outbound text.**
- `answer_bank`: a question regex, then an answer mapped to fact IDs or confirmed fields; otherwise the policy is needs_prerit.

**Sources and fetching**
- `sources`: kind, config, automation (auto/discover_only/manual_lane), tos_status + tos_url + reviewed_at, circuit breaker. **Every source starts disabled until its ToS and robots status are recorded.**
- `domain_policy`, `http_cache`, `companies`.

**Opportunities**
- `opportunities`:
  - Core: canonical_key, kind (internship/job/part-time/contract/fellowship/program), role_type, location, lat/lon, work_mode, apply_channel, apply_email + exact quote, deadline + confidence, start/duration/hours.
  - **Pay block:** min/max, currency, period, status (listed/unknown/unpaid/fee), monthly_local, monthly_inr min/mid/max, fx rate/date, benefits (housing/meals/travel/allowance), living_cost_inr + basis + confidence, pay_ratio.
  - Status: eligibility, availability, scam, fit_score + breakdown, stage, stage_reason, link_status.
- `opportunity_sources`: many sources map to one opportunity, for dedupe.
- `eligibility_checks`: requirements with exact quotes, verdict, confidence, method/model.
- `scam_checks`.

**Applications and documents**
- `applications`: mode (dry_run/self_test/live), status incl. `historical_frozen` and `awaiting_approval`, approval_sha256, gmail thread + Message-ID.
- `documents` (versioned, with author_model lineage) and `document_sentences` (fact_ids, job_quote_ids).
- `fact_checks` (per sentence, per layer) and `gate_results`.

**Agents, models and runs**
- `agents`, `agent_live` (now-line, progress, tok/s, heartbeat).
- `models` (runtime, complete, reason, RAM est/measured), `model_servers`, `benchmarks`, `role_assignments` (auto/override).
- `tasks` (queue: capability, priority, lease, heartbeat, attempts, backoff, escalation_level, idempotency_key), `agent_runs` (full input/output paths, model, tokens, tok/s, cost, duration), `events`, `cloud_usage`.

**Email and alerts**
- `email_threads` (classification, notify_only_lock), `email_messages`.
- `outbound_log` (intent rows, caps, deterministic Message-ID), `mock_mailbox`.
- `needs_prerit` (kinds: submit_form/approve/missing_info/decision/captcha/login/interview/offer/assessment/legal/money).
- `notifications`, `strategy_reports`.

**Not tables:** FX rates and living costs live as cached JSON/CSV in `config/` and `data/`.

## Agent protocol
Each agent is one YAML file, pydantic-validated and hot-reloaded with watchfiles. An invalid file is rejected and the last good version kept.
```yaml
id: writer  name: Writer  avatar: "✍️"  color: "#A78BFA"  role: writer
adapter: openai_compatible   # openai_compatible|cloud|script|http|browser|sim
adapter_config: {managed: true, prompt: prompts/writer.md, schema: schemas/draft.json, max_tokens: 900}
model: auto                  # leaderboard winner, or explicit id
capabilities: [draft.cover_letter, draft.cold_email, draft.research_statement, draft.form_answers, draft.followup]
cost_tier: local  concurrency: 1  schedule: {mode: on_demand}  enabled: true
```
**Adapters** share `run(task, ctx)` and `health()`. The context offers `ctx.llm(role, msgs, schema)` (router, JSON repair,
escalation), `ctx.cloud()` (budgeted), `ctx.fetch()` (polite, with the manual-lane block), `ctx.emit()`, `ctx.progress()`,
`ctx.heartbeat()` and `ctx.check_cancel()`.
- **openai_compatible:**
  - Streams to measure time-to-first-token and tok/s.
  - Always sends `model` (the served path) and `max_tokens`.
  - Strips `<think>` tags.
  - Validates against a JSON schema and does one repair retry. MLX has no `response_format`; llama.cpp, Ollama and LM Studio use it when present.
- **Claude CLI provider (optional, via the `cloud` adapter/runner):** `claude -p --output-format json --json-schema <s> --tools "" --strict-mcp-config --mcp-config '{"mcpServers":{}}' --settings '{"disableAllHooks":true}' --system-prompt <role> --no-session-persistence --max-budget-usd <cap> --model <m>`.
  - Runs with an empty working directory and a minimal environment.
  - A result is accepted only when `subtype=success` and `structured_output` validates.
  - Records `total_cost_usd` (a client-side estimate) and usage.
  - Never uses permission-bypass flags.
- **script:** built-in modules run in-process. User scripts are subprocesses speaking JSON over stdio, with no secrets.
- **http:** synchronous `POST /run`; the endpoint must be localhost or allowlisted; payloads are redacted.
- **browser:** Playwright with a transparent user agent and no stealth plugins.
  - It stops and creates a Needs Prerit item on any CAPTCHA or bot-detection script (grecaptcha, hcaptcha, turnstile, px, `_abck`), a login or password field, account creation, a sensitive-ID field, or an unknown required field.
  - v1 targets are the mock ATS only.
- **Side effects:**
  - `apply.*`, `reply.send` and `followup.send` belong only to the built-in Applicant, Inbox Watcher and Follow-up agents, and the loader enforces this.
  - Pausing an agent that owns a side effect pauses that capability system-wide; its tasks are not rerouted.
  - Wizard-created agents return data only. Creating script agents is loopback-only.
- **Starting team (10 nodes):** Scout, Verifier, Writer, Fact-Checker, Reviewer, Résumé Builder, Applicant, Inbox Watcher, Follow-up, Strategist.
- **Add Agent wizard:** adapter → identity → capabilities → config (endpoint probe, env-var name only) → schedule and concurrency → live test. The agent then appears in the graph with no restart. New agents run on probation (their outputs need approval) for 5 runs.

## Orchestrator
- **Task lifecycle:** queued → leased → running → succeeded, failed (retry), dead, deferred_budget, waiting_memory or cancelled.
  - `pipeline/state.py` maps (stage, result) to (new stage, new tasks) in the same transaction.
  - Idempotency keys stop duplicate work.
- **Dispatcher (every 500 ms):**
  - Candidates are agents with the capability that are enabled, not paused, and below their concurrency.
  - `score = role_score × availability(loaded 1 / loadable .7) × (1−0.3·load) − cost_penalty(cloud .5 unless escalation)`.
  - Leases are atomic UPDATEs lasting 90 s, extended by a heartbeat every 15 s.
- **Failures:**
  - Transient failures back off exponentially, honouring Retry-After.
  - Quality failures (bad JSON, low confidence, disagreement) **escalate**: role model → next-ranked different local model → a cloud model when hq.llm.policy allows it (subscriptions first, then Grok within its budget) → Needs Prerit decision or dead.
  - Domain outcomes (404, ineligible, scam) are stage changes, not failures.
- **Budget:**
  - Reserve the EMA cost of that task type, then check today's spend + reserved + estimate ≤ cap. Grok's call cap defaults to 40/day; each subscription CLI gets at most 30 HQ calls per 5-hour window so Prerit keeps the rest of his plan.
  - When over the cap, the task is set to `deferred_budget` until midnight IST, and local work continues.
  - Items due within 48 h that are blocked on the budget go to Needs Prerit.
  - With `signoff_required` on (default), nothing is submitted without sign-off.
- **PAUSE ALL / Freeze outbound / per-agent pause:**
  - Every send passes through `apply/guard.py`. In one transaction it re-reads pause, mode, approval sha, caps and idempotency, writes the intent row, then sends.
- **Watchdog (every 30 s):**
  - Expired leases are re-queued.
  - Stuck agents (heartbeat older than 2× the interval) are cancelled and restarted.
  - Model servers are health-checked and restarted at most 3 times per 10 min, then marked broken.
  - A repeated error signature (3 times in 1 h) sends a cloud `debug.failed_run` diagnosis. Only whitelisted actions are applied automatically.

## Model manager (phase b)
- **Discovery** runs every 10 min, on a rescan button, and when a new model appears (which triggers a quick benchmark):
  - **MLX:** the HF cache snapshot, verified with index.json weight_map vs blobs and no `.incomplete` files. Also checks mlx_lm model_type support and modality.
  - **Ollama:** `:11434/api/tags` or the manifests.
  - **LM Studio:** `:1234/v1/models` or `~/.lmstudio`.
  - **llama.cpp:** a scan for `*.gguf` files (mdfind plus common directories); these are served by `llama-server`.
  - Broken models are listed with a reason. "Resume download" runs only when Prerit clicks it; agents never download anything.
- **Benchmark suite (real project data, `tests/fixtures`):**
  - `parse_job`: 13 LinkedIn pages (offline only), Internshala cards, a TEEP detail page, and Greenhouse/Lever/Ashby JSON.
  - `eligibility`:
    - Ineligible: Linde (7th semester), Meril (2026 grads), eTeam and MetAntz (2026/27 grads).
    - Eligible: Readyly. Eligible with gaps: pharma&.
    - Scoring: quote grounding, and a false "eligible" weighs ×3.
  - `title_filter`: 222 scan lines.
  - `write_paragraph`: must pass the deterministic fact gate.
  - `factcheck`: `factcheck_pairs.jsonl` with ~35 labelled bad draft sentences plus ~120 good letters.py sentences (the "200+" ones relabelled). Recall floor 0.90.
  - `classify_email`: ~40 synthetic emails. Interview and offer recall floor 0.95.
  - Metrics per model:
    - tok/s and TTFT from streaming.
    - JSON validity (first try and after repair), per-task accuracy.
    - Peak **phys_footprint** via `proc_pid_rusage`, because RSS misses Metal memory.
    - Measured both alone and co-loaded.
- **Role assignment:**
  - `0.6·quality + 0.15·json_valid + 0.15·speed_vs_target + 0.10·(1−ram/pool)`, with per-role floors.
  - The fact-checker is assigned first.
  - **Independence is enforced per document lineage:** the checker model must differ from every author model in that document's version history. This covers escalations, overrides and cloud polish; a cloud-polished letter is re-checked locally and signed off by a different model (a local checker or another cloud model), otherwise it goes to review.
  - Leaderboard overrides are kept; the validator rejects writer = checker.
  - Recommendation: add one non-Qwen model (e.g. a Llama or Gemma 8B MLX) for a more independent verifier. It needs Prerit's OK to download.
- **Memory policy (48 GB, Metal wired limit about 36 GB):**
  - The pool budget is 30 GB, with a pinned hot set of the role winners (likely the 30B MoE plus one 4–7B model).
  - Before loading, check the pool sum + need ≤ budget **and** free memory (from vm_stat) ≥ need + 4 GB, with no pressure warning.
  - Otherwise evict idle models (least recently used, 20 min TTL); if it still doesn't fit, the task waits.
  - **Usability mode:**
    - Prerit active (HIDIdleTime < 5 min) or on battery: drop to a small pool of 8 GB or less and unload the 30B.
    - Quiet-hours setting.
  - Qwen3 servers start with `--chat-template-args '{"enable_thinking":false}'`.

## Pipeline and gates (phase c)
1. **Discover.** All traffic goes through a polite fetcher:
   - robots.txt, a per-domain delay of 5 s for HTML and 1/s for APIs, ETag caching, a transparent user agent.
   - A **hard block** on manual-lane domains.
   - Sources:
     - Greenhouse, Lever and Ashby APIs, seeded with slugs from the earlier scans; the Strategist adds more, each validated first.
     - Program and lab watchers: SRFP, Summer@EPFL, UTRIP, MLH, TEEP tables and details (after a robots/ToS check).
     - Prerit's own job-alert emails (phase d), then an attempt to find the same role on an ATS.
     - A manual paste-a-link box.
     - Remote feeds (Remotive, Arbeitnow with visa_sponsorship, and others) come in phase e, with attribution.
   - A role-type classifier keeps part-time, contract, freelance, Werkstudent and junior roles, not only "intern".
2. **Dedupe:**
   - A canonical URL and the ATS id.
   - Otherwise a fuzzy match: company ≥ 92, title ≥ 90, compatible location, and posted within 60 days.
3. **Verify:**
   - **Link live:** the job is still on the board, or a 200 response with no "closed" markers.
   - **Deadline:** conservative by 1 day. No deadline means rolling, re-verified every 3 days.
   - **Eligibility:** a deterministic rule engine (grad-year, stage, semester, degree, CGPA, **work authorization / enrolment / visa**), time-aware because Prerit becomes a rising 3rd-year in May 2027. Then local LLM extraction with exact quotes; confidence = model accuracy × agreement × grounding. Below 0.80 it escalates to a different local model, then a cloud model.
   - **Availability gate:** the role's dates and hours must fit Prerit's confirmed availability windows and hours cap. Unknown sends it to Needs Prerit.
   - **Pay:**
     - Parse the amount, currency and period, then convert to monthly and to INR (Frankfurter, cached daily).
     - Living cost comes from the seed `living_costs.csv` (editable in the UI, with provenance); an unseeded city becomes a decision item.
     - Accept if the ratio ≥ 1.0, or if it's a funded program with stay + food + travel covered and ≥ ₹5,000/month.
     - Unpaid postings are rejected. **Unknown pay becomes a one-click decision** by default (configurable).
     - Hourly pay without stated hours gets `pay_status=variable`; the system never assumes 40 h.
   - **Scam:** fee lexicon (including application fees, e.g. OIST ¥5,000), a known-mill list (11 names), certificate-only wording, free-mail recruiters for brand names, lookalike domains, early requests for ID or bank details, crypto or cheque language.
4. **Score fit (0–100):**
   - Role relevance 25, skills 20, eligibility confidence 15, pay ratio 15, source prior 10, deadline 5, location 5, program benefits 5.
   - Draft if the score is ≥ 60; cloud polish if ≥ 75; at most 20 new drafts a day.
5. **Draft.** The Writer receives the atomic facts (with IDs), verified job quotes, doc-type rules and gold exemplars. It **never** sees legacy `angle` notes. It outputs one entry per sentence: `{text, kind, fact_ids, job_quote_ids}`.
6. **Fact gate.** It runs on **every outbound string**: letters, résumé summary lines, form answers, subject lines, follow-ups and info replies.
   - (a) Deterministic rules:
     - `NUM_NOT_IN_FACTS`: numbers, dates and URLs must be in the cited facts or quotes.
     - `BANNED_CLAIM`: deploy, production, full-stack, scalable, real-time, plural end-to-end, several projects, improve performance, accuracy/users, internship experience, and the unused tech list. **Negation and aspiration clauses are allowed**, e.g. "haven't yet used PyTorch".
     - `WRONG_PROJECT`: pipeline/YAML/Streamlit belong to the book project; RandomForest/one-hot/tenure belong to churn.
     - Also `TECH_NOT_WHITELISTED`, `PLURAL_OVERGEN`, `CITATION_MISSING`, `JOB_CLAIM_UNQUOTED`, and structural rules.
   - (b) An independent local verifier checks each sentence; a `partial` verdict counts as a fail.
   - (c) final sign-off (a second local model, or a cloud model).
   - On any failure: targeted feedback, a rewrite, and **all** layers re-run. After 3 loops, cloud polish. If it still fails, a review item goes to Needs Prerit.
   - Yes/no and numeric screening answers must map to a fact or a confirmed field, otherwise they go to Needs Prerit.
   - Résumé: approved bullets only. The PDF is checked for one page and approved text.
7. **Quality gate:**
   - Names the organisation and ≥ 1 verified job quote; zero clichés; correct length, salutation and sign-off.
   - Specificity rubric ≥ 3/5; Jaccard < 0.6 against recent letters.
8. **Apply.** First a pre-submit recheck within 24 h: link, deadline, scam, pause, mode, caps, approval sha and budget. Then one of three routes:
   - **Email:** only to an address that is an exact quote on the official page, with a matching domain.
     - Gmail API with the résumé attached.
     - A deterministic Message-ID. On crash recovery the Sent folder is checked before any resend, and ambiguous cases go to Needs Prerit.
     - Caps: 10/day total, 3/day to labs, 1 per recipient domain per 14 days.
   - **Pre-filled pack (default for ATS forms and manual-lane sites):**
     - Direct link, copyable answers, cover letter, files ("Reveal in Finder"), pay and deadline.
     - Buttons: "I submitted it", Skip, Snooze.
     - An optional phase-e mode opens the form headed and pre-filled, and Prerit clicks Submit.
   - **Answer policy:** EEO questions get "Prefer not to say" (a form without that option goes to Needs Prerit); sensitive IDs are never provided.
9. **Inbox (phase d):**
   - Gmail history polling every 3 min.
   - Rules and the LLM classify: interview, assessment, info_request, rejection, auto_ack, offer, scam, job_alert, other.
   - **Notify-only locks:** interview or scheduling, assessments and coding tests, requests for availability or expected stipend, offers/CTC/money, legal/NDA/contract/background checks, and joining or visa documents. A lock means a big alert, a macOS notification, a Needs Prerit item, and **no outbound** on that thread.
   - Info-request auto-replies need the rules and the classifier to agree, high confidence, all gates passed, and no lock terms. They are **off for the first 2 live weeks** (Gmail drafts are created instead).
10. **Follow-up:** one only (a unique constraint), 10 days after an email application with no reply, fully gated. Never sent on a locked thread.

**Legacy import:**
- The 10 items plus TEEP (CCU, not NCCU; to re-verify) are imported as **`historical_frozen`**, with no outbound until Prerit says what was sent.
- Coding Ninjas is imported as `skipped`.
- The letters are historical: reapplying means a fresh draft through the gates.
- Pay is normalised so real ₹ figures show from day one.

## "How much they pay me"
- **`<PayBadge>` everywhere:**
  - A large ₹/month figure (min–max), with the original currency and period underneath, and a ratio bar vs living cost (green ≥ 1.5×, amber 1–1.5×, red < 1×).
  - The tooltip shows provenance.
  - Programs show "Stay + food + travel + ₹X/mo".
- **Where it appears:**
  - **Command Center:** "Pipeline pay" (median/max ₹/mo), "Best offer", "Median stipend applied".
  - **Kanban:** pay is the second line of every card, with pay sort and filter.
  - **Map:** pin size scales with pay.
  - **Detail page:** a pay hero with local/INR and monthly/total toggles.
  - **Offers:** a side-by-side comparison.
  - **Analytics:** pay histogram and pay by country.

## UI (premium mission control)
- **Routes:**
  - `/login`
  - `/` Command Center
  - `/pipeline`
  - `/map`
  - `/o/:id` Detail
  - `/activity`
  - `/inbox`
  - `/needs`: Needs Prerit, with an Approvals queue in approve-before-submit mode
  - `/analytics`
  - `/models`: Leaderboard
  - `/agents`: Manager and wizard
  - `/settings`: Rules, Autonomy & Mode, Budget, Schedules, Sources, Profile & Facts, Security
- **Header:**
  - A big red **PAUSE ALL** button (resume needs a hold-to-confirm).
  - A mode badge: DRY RUN, SELF-TEST, LIVE or APPROVE-FIRST.
  - A Grok budget gauge and worker/SSE status.
- **Look:**
  - Background `#070B14`, glass panels (`white/4%`, blur, `white/10` border), and a glow in each agent's own accent colour: Scout cyan, Verifier teal, Writer violet, Fact-Checker amber, Reviewer coral, Résumé blue, Applicant pink, Inbox lime, Follow-up orange, Strategist fuchsia.
  - Red is reserved for errors and the kill switch; **gold** is reserved for money.
  - A 24 px faded grid plus 4% SVG noise.
  - Fonts: Space Grotesk (display and numbers), Inter (UI), JetBrains Mono (logs).
  - Only transform and opacity are animated; reduced motion is respected.
- **Command Center:**
  - Count-up hero stats, including Grok $ today vs local tokens.
  - **AgentNetwork:** React Flow with custom glowing nodes (breathing when working, dim when idle, red shake on error) and particle edges fired by `task.handoff` events in the source agent's colour.
  - Agent cards: live "now" line, progress, tok/s, tasks today.
  - Strategist daily report card.
- **Pipeline:** the columns requested, plus a collapsed "Filtered" column (scam, ineligible, expired). Cards slide between columns with `layoutId`. Dragging a card is an audited display override only and never triggers an action.
- **Detail page:**
  - Stage stepper, pay hero, deadline countdown, fit breakdown, eligibility quotes.
  - The exact letter and PDF sent, and the **fact-check report** (green/red sentences, rules and facts on hover).
  - Agent timeline with the escalation ladder and costs; reply thread.
- **Activity:** a virtualised JetBrains Mono terminal with agent filters and a run drawer.
- **Inbox:** tags, locks, and interview/offer banners plus a modal.
- **Needs Prerit:** open + copy answers, completable in under 2 min.
- **Analytics:** Recharts; the dataviz skill is used when building it.
- **Models:** leaderboard, memory bar, broken-model card, pin/override/benchmark controls.
- **Mobile:** below 768 px a bottom tab bar, a swipeable kanban, and the kill switch always visible.

## Security and safety
- **Modes enforced by capability, not code path:**

  | Mode | Gmail token scope | What can be sent |
  |---|---|---|
  | DRY_RUN | readonly | nothing (mock mailer, mock ATS only) |
  | SELF_TEST | send | only to sangwanprerit40@gmail.com (hard equality check) |
  | LIVE | send | as gated |

  - The send scope is requested only in the go-live step, through a second consent.
  - Startup refuses if `HQ_FORCE_DRY_RUN=1` and a send-scoped token exists.
  - **GO LIVE** needs an `.env` edit, a restart, and a loopback-only typed confirmation. It is never available from the phone.
- **Development and my testing never contact third parties.**
  - A network guard blocks non-localhost POSTs.
  - Playwright aborts any request that isn't to localhost.
  - The fetch log is asserted to contain zero manual-lane domains.
- **Auth:**
  - Required on **every** route, including loopback and SSE: an scrypt-hashed passcode in `.env`, and a signed HttpOnly `SameSite=Strict` cookie.
  - The `Host` header is allowlisted and `Origin` is checked on changes, which stops DNS rebinding.
  - Login is rate-limited.
  - LAN binding (`HQ_LAN=1`) is off by default. Self-signed HTTPS is optional (phase e).
- **Secrets:**
  - Only in `.env`: passcode hash, session secret, Gmail client ID/secret and refresh token (written there by the OAuth step).
  - A redaction filter covers logs, run records and anything sent to a cloud model. The phone number is never sent to any cloud model.
- **Prompt-injection defence:**
  - Web and email text is treated as data. LLM outputs are validated values only.
  - Every send decision (recipient, URL, whether to send) is made by deterministic code.
  - The Claude and Codex CLIs run with no tools and no hooks in empty read-only sandboxes; Grok gets plain chat completions.
- **Never:** paying, card details, creating accounts, entering passwords, solving CAPTCHAs, bypassing logins, attempting assessments, or acting on interviews, offers, money or legal matters.

## Reliability
- **`./start.sh`:**
  - A `doctor` check (uv, node, Chrome, Ollama, optional claude/codex CLIs, ports, disk).
  - `uv sync`, then build the web app if it changed.
  - Migrate the database, start the supervisor, print the URL.
- **`./stop.sh`:** drains the worker and stops the model servers.
- **Make targets:** `make up/down/test/bench/screens/backup`.
- **launchd:** `scripts/install_launchd.sh` installs a LaunchAgent (KeepAlive, RunAtLoad, ThrottleInterval 30, logs in `data/logs`).
  - It runs **after login**. With FileVault on, nothing runs after a reboot until Prerit logs in; the README says so and does not suggest disabling FileVault.
  - The step verifies that the optional `claude`/`codex` CLI logins and `osascript` notifications work from the launchd context.
- **Keeping the Mac awake (README):**
  - AC power; `caffeinate -i` from the supervisor; optional `sudo pmset -c sleep 0` (Prerit runs it).
  - Closing the lid sleeps the Mac unless it's in clamshell mode.
  - Missed schedules catch up once.
- **Self-healing:**
  - Leases and heartbeats, the watchdog, model-server restarts.
  - Per-source circuit breakers (5 errors → disabled for 6 h).
  - A Gmail token health alert (re-checked on day 8).
- **Retention and backups:**
  - Nightly SQLite backups, 14 kept.
  - Events kept 60 days, runs 90 days (gzipped).

## Phases (each: build → pytest → run → screenshots (1440×900 + 390×844) → fix → report)
**How I build each phase:**
- A workflow with parallel builders (backend and frontend in separate directories), then tests.
- An adversarial review pass: correctness, safety gates, and UI polish via screenshots with the design critique skill.
- Fixes, then verification in the in-app browser.
- The README grows with every phase.

**0. Setup (right after approval)**
- Move the session to `~/Documents/agent-hq` and `git init`.
- Copy the legacy files, the scratchpad fixtures and repos (with a sha256 manifest), and write `PLAN.md`.
- Smoke tests:
  - `claude -p` isolation: the stream-json init event shows no tools, no MCP servers, no hooks, and 1 turn; cost is reported; the budget flag works under subscription auth.
  - mlx-lm in the venv loads all 5 models, with measured memory.
  - `osascript` notifications show.
  - Chrome renders PDFs from the venv.

**(a) Foundation plus the live dashboard with simulated agents**
- Deliverables:
  - DB and migrations, supervisor, start/stop scripts.
  - Queue with leases, retries, pause/kill and the watchdog.
  - YAML registry with hot reload; the sim adapter drives all 10 agents.
  - REST + SSE + auth.
  - Full UI: Command Center, Pipeline, Activity, Agents + wizard, Settings; the other pages as shells.
  - Legacy importer (frozen items with real ₹ pay).
- Acceptance:
  - The graph runs at ≥ 55 fps.
  - PAUSE ALL stops everything within 2 s.
  - A new YAML agent appears within 3 s.
  - A `kill -9` of the worker recovers within 30 s.
  - Auth and Host tests pass.

**(b) Models, benchmarks, routing and cloud models**
- Deliverables:
  - Discovery for 4 runtimes; ModelManager with the memory and usability policy.
  - Benchmark suite with gold fixtures; leaderboard with overrides.
  - openai_compatible and cloud adapters; escalation; budget.
- Acceptance:
  - 5 usable and 5 broken models shown with reasons; the leaderboard is filled.
  - Writer ≠ checker across the full document history (tests cover escalation and override).
  - A forced escalation goes local → local → a cloud model and is logged with cost.
  - Budget deferral works.
  - The memory pool is never exceeded.

**(c) Real pipeline, dry run**
- Deliverables:
  - Fetcher, ATS and program/TEEP sources (ToS recorded), dedupe, verify (eligibility, availability, pay/FX/living cost, scam), fit score.
  - Writer, fact gate, quality gate, résumé builder.
  - Applicant: mock mailer, mock ATS, packs, approvals.
  - Detail, Map and Needs Prerit pages.
- Acceptance:
  - ≥ 30 real verified opportunities within 24 h, each with ₹/mo and a ratio.
  - Golden fact tests pass (every bad draft sentence blocked, every letters.py sentence passes).
  - End-to-end dry-run applications appear only in the mocks.
  - A Stripe-like posting produces a pack with the phone field flagged.
  - Zero real outbound traffic.
  - Prerit audits the first 20 eligibility and pay verdicts.

**(d) Gmail, replies, follow-ups and notifications**
- Deliverables:
  - OAuth (readonly first), history polling, classification and locks.
  - macOS notifications, the Inbox page, job-alert parsing.
  - Follow-up agent, info-reply drafts.
  - SELF_TEST mode and the **go-live checklist**: required profile fields, golden tests green, ≥ 5 dry-run applications reviewed, caps set, send-scope consent, typed GO LIVE. Recommended: approve-first for the first 10 live applications.
- Acceptance:
  - A synthetic interview email produces an alert, a notification and a lock, with no reply.
  - The follow-up fires once at day 10 (simulated clock).
  - A duplicate-send recovery test passes.

**(e) Strategist, analytics and hardening**
- Deliverables:
  - Daily Strategist report card. It may auto-apply ATS-slug adds, disabling dead sources, and keyword tuning within the vocabulary; other changes are proposals.
  - Analytics; remote feeds; optional 3D globe and headed pre-fill mode.
  - launchd install/uninstall; backups; `debug.failed_run`; README completed.
- Acceptance:
  - Auto-start after a login or reboot.
  - A stuck agent is healed.
  - A report is produced and its actions logged.
  - Phone access over Wi-Fi with auth works.

## What Prerit provides (none of it blocks phases 0–b)
1. **Profile fields** in Settings (needed before go-live): phone, CGPA and marks since class X, grad year, semester, city, availability windows and hours cap, passport yes/no.
2. **Confirmations:** the "more than 200 ratings" rewording, and which legacy applications (if any) were already sent.
3. **Phase d:** create a Google Cloud OAuth *Desktop* client with the consent screen set to *In production*, put its values in `.env`, and approve consent.
4. **Cloud models:** which to switch on (Claude CLI, Codex CLI, Grok), the Grok budget (default $2/day) and HQ's share of each subscription window (default 30 calls / 5 h).
5. **Optional downloads:** a non-Qwen verifier model; re-downloading the broken models.
6. **Going live:** flip GO LIVE and work through the Needs Prerit lane.

## Risks and mitigations
- **Little real auto-submission.** Most ATS and portal applications will be packs rather than automatic submissions. Mitigations: email channels, ATS matching for alert emails, and packs that take under 2 min.
- **Local-model errors:** multi-layer gates, lineage independence, final sign-off (a second local model, or a cloud model), and golden tests.
- **Laptop usability and heat:** the usability and battery mode plus quiet hours.
- **Subscription limits (Claude, ChatGPT):** HQ's per-window cap, reported windows, pause until reset, and local-only mode.
- **Gmail token expiry:** "In production" status plus a health alert.

## Verification (end to end)
- `make test`: unit, gate, orchestrator and dry-run tests.
- `make bench`: fills the leaderboard.
- `./start.sh`, then log in at `http://localhost:8765`.
- Watch the sim or dry-run pipeline animate. Check that PAUSE ALL stops everything and that `kill -9` of the worker recovers.
- `make screens`: captures desktop and mobile screenshots of every page, reviewed each phase.
- In the phase-c dry run, check the mock mailbox and mock ATS contents and the fetch log (no manual-lane domains, no third-party POSTs).
- Before go-live, SELF_TEST sends one real email only to Prerit's own address.
