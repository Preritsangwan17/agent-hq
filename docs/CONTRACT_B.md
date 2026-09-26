# Agent HQ — Phase (b) contract: models, benchmarks, routing, Claude, budget

Extends `docs/CONTRACT.md` (still authoritative for everything it covers). Read `PLAN.md` → "Model manager".
Gold data (hand-labelled by the lead — do not relabel; report disagreements instead):
- `config/facts.yaml` — atomic facts (IDs, text, evidence at commit SHAs, allowed phrasings). Source of truth.
- `tests/fixtures/factcheck_pairs.jsonl` — 158 sentences (32 `unsupported` with rule + span, 126 `ok`).
- `tests/fixtures/eligibility_gold.jsonl` + `tests/fixtures/jobs/linkedin_*.txt` — 14 postings (verdict, exact quotes).
- `tests/fixtures/emails_synthetic.jsonl` — 41 synthetic replies (label + `lock_expected`).
- `tests/fixtures/titles_gold.jsonl` — 189 titles (`target` bool; includes "Internal/International" traps).
- Raw HTML for parsing fixtures: `legacy/scratchpad/{li_*.html,is_*.html,teep_*.html}` (offline use only).

## 1. Hard rules
- Phase (b) adds model/Claude plumbing. The pipeline tasks still run through the `sim` adapter; no real outbound.
- Local model servers bind 127.0.0.1 only. Agents never download models (a "Resume download" button may exist but
  must only run on an explicit user click and is out of scope unless trivial).
- Claude runs ONLY as: `claude -p --output-format json --json-schema <schema> --tools "" --strict-mcp-config
  --mcp-config '{"mcpServers":{}}' --settings '{"disableAllHooks":true}' --setting-sources project
  --disable-slash-commands --system-prompt <role prompt> --no-session-persistence --max-budget-usd <cap> --model <m>`
  with the prompt on stdin, cwd `data/claude_sandbox` (empty dir), env = {PATH, HOME, USER, LANG} only, timeout 180 s.
  Never `--bare` (needs an API key), never permission-bypass flags. Accept a result only if `is_error=false`,
  `subtype=="success"` and `structured_output` validates against the schema. Record `total_cost_usd` (a client-side
  estimate) + usage into `claude_usage`.
- The standalone CLI is currently NOT logged in (`claude auth status` → loggedIn false). The runner must detect
  "Failed to authenticate"/not-logged-in, mark Claude `unavailable`, create ONE `needs_prerit` item (kind `decision`,
  title "Log in to the Claude CLI", instructions: run `claude auth login` in Terminal) and let local-only work continue.
  Re-check availability at most every 10 minutes.

## 2. Modules (new)
- `hq/models/discovery/{__init__,mlx,ollama,lmstudio,llamacpp}.py` → `discover_all() -> list[ModelInfo]`.
  - MLX/HF cache (`~/.cache/huggingface/hub/models--*/snapshots/<rev>/` via refs/main): complete iff (index.json
    weight_map files all resolve to existing blobs AND no `.incomplete` blobs for them) OR `model.safetensors` /
    `weights.safetensors` resolves. Read config.json (model_type, architectures, quantization bits/group, max ctx).
    Modality: chat if tokenizer_config has chat_template (or chat_template.jinja exists); embedding if modules.json /
    "Embedding" in name; stt for whisper; tts for kokoro. Runtime support: `importlib.util.find_spec(f"mlx_lm.models.{model_type}")`.
    Expected on this Mac: 5 usable chat (Qwen3-Coder-30B-A3B-4bit-DWQ, Qwen2.5-7B-4bit, Qwen3-4B-2507-4bit,
    Qwen2.5-3B-4bit, Qwen3-0.6B-4bit), 3 non-chat, 5 broken (Qwen2.5-14B partial, Qwen2.5-1.5B ref only, 3×Qwen3.5-2B no weights).
  - Ollama: `GET http://127.0.0.1:11434/api/tags` (2 s timeout) else read `~/.ollama/models/manifests`.
  - LM Studio: `GET http://127.0.0.1:1234/v1/models` else scan `~/.lmstudio/models`.
  - llama.cpp: `mdfind "kMDItemFSName == '*.gguf'"` + common dirs; served by `/opt/homebrew/bin/llama-server`.
  - Model id format: `mlx:<repo>`, `ollama:<name>`, `lmstudio:<id>`, `gguf:<abs path>`.
  - Upsert into `models`; new complete chat model → event `model.discovered` + a `benchmark.quick` task.
- `hq/models/memory.py`: `phys_footprint_gb(pid)` via ctypes `proc_pid_rusage(pid, RUSAGE_INFO_V4)` (ri_phys_footprint,
  ri_lifetime_max_phys_footprint); `system_memory()` (total, available from vm_stat free+inactive+purgeable, pressure
  from `memory_pressure -Q` or sysctl kern.memorystatus_vm_pressure_level); `user_active()` (HIDIdleTime from
  `ioreg -c IOHIDSystem` < 300 s); `on_battery()` (`pmset -g batt`).
- `hq/models/manager.py`: `ModelManager` living in the worker. `await ensure(model_id) -> base_url`. One
  `mlx_lm.server` process per loaded MLX model: `.venv/bin/python -m mlx_lm.server --model <repo> --host 127.0.0.1
  --port <8101..8120> --max-tokens 2048` (+ `--chat-template-args '{"enable_thinking":false}'` for Qwen3-family),
  wait for `/health` (≤120 s), record `model_servers`. Policy: pool budget `model_pool_budget_gb` (default 30) —
  before loading need `pool_sum + need ≤ budget` AND `available ≥ need + 4 GB` AND pressure not warn; else evict idle
  non-pinned LRU (idle TTL 20 min); else task waits (`waiting_memory`). Usability mode (setting `usability_mode`
  default true): if `user_active()` or `on_battery()` → budget 8 GB (30B MoE unloaded); quiet hours respected.
  Health-check every 30 s; restart ≤ 3 per 10 min then mark `broken` and let routing fall back. Stop all servers on
  worker shutdown; re-adopt/reap stale PIDs from `model_servers` on startup.
- `hq/llm/client.py`: OpenAI-compatible chat (httpx, streaming) → `{text, prompt_tokens, completion_tokens, ttft_ms,
  tok_s}`. Always send `model` (served id) and `max_tokens`. Temperature from caller (0 for checks).
- `hq/llm/json_utils.py`: strip `<think>…</think>` and code fences, extract first JSON object/array, validate with
  jsonschema, one repair retry ("Your previous output was invalid: <error>. Return only valid JSON matching the schema").
- `hq/llm/claude.py`: the runner from §1 (+ availability probe, error classification: auth, budget
  `error_max_budget_usd`, usage/rate limit → defer 1 h, structured-output failure).
- `hq/llm/router.py`: `await route(role, messages, schema, *, exclude_models=frozenset(), lineage=(), allow_claude=True,
  max_tokens=..., temperature=0.0, task_type=...) -> LLMResult(model_id, output_json, usage..., escalation_level)`.
  Picks the highest-ranked assigned model for `role` not in `exclude_models ∪ lineage`; on invalid JSON after repair
  or `output.confidence < threshold` (when the schema has confidence) escalates: level 1 = next-ranked DIFFERENT local
  model (prefer different family), level 2 = Claude (budget + availability permitting), else raise `EscalationExhausted`.
  Each attempt is an `agent_runs` child row linked by `escalated_from_run_id`.
- `RunContext` gains `await ctx.llm(role, messages, schema, **kw)` and `await ctx.claude(task_type, prompt, schema, **kw)`
  (thin wrappers over the router / runner that also update `agent_live` model_id + tok/s).
- `hq/worker/budget.py`: `reserve(task_type) -> Reservation | None` (EMA cost per task type seeded from
  `config/claude_prices.yaml`; checks `spent_today + reserved + est ≤ claude_daily_budget_usd` and calls today ≤
  `claude_daily_call_cap`), `commit(reservation, actual_cost)`, `release()`. Over cap → task `deferred_budget` with
  `not_before = next midnight IST` + event `budget.capped`. `budget_state()` for API/UI. Day boundary = IST.
- `hq/models/roles.py`: roles and their benchmark tasks: `parser`←parse_job, `eligibility`←eligibility,
  `title_filter`←title_filter, `writer`←write_paragraph, `fact_checker`←factcheck, `classifier`←classify_email,
  `summarizer`←parse_job+write_paragraph. `role_score = 0.60·quality + 0.15·json_valid + 0.15·min(1, tok_s/target_r) +
  0.10·(1 − ram_gb/pool_budget)`; per-role floors (fact_checker recall_on_unsupported ≥ 0.90 AND precision_on_ok ≥ 0.85;
  classifier interview+offer recall ≥ 0.95; eligibility false-eligible weighted ×3). Assign fact_checker FIRST, then
  writer from remaining models with `writer ≠ fact_checker` (prefer a different family). Store ranked lists in
  `role_assignments`; overrides (`source='override'`) survive re-benchmarks. `validate_assignment()` rejects any
  state where writer == fact_checker. `checker_allowed(checker_model, lineage_models) -> bool` (lineage independence
  used by phase c). If no local model meets the fact_checker floor → role marked `needs_claude_signoff` (local runs
  as pre-screen only).
- `hq/pipeline/gates/fact_deterministic.py` (moved up from phase c because the writer benchmark needs it):
  `check_sentence(text, cited_fact_ids, facts, *, context=None) -> list[Violation(rule, span, message)]` and
  `check_document(sentences) -> report`. Rules (config-driven via `config/banned_claims.yaml`, `config/tech_terms.yaml`,
  `config/cliches.yaml`): NUM_NOT_IN_FACTS, BANNED_CLAIM (deploy*, production(-like), full-stack, scalable, real-time,
  "end-to-end systems/pipelines" plural, several/many/multiple projects, improve* performance, accuracy/users/impact,
  internship experience, expert/proficient/extensive, strong/solid foundation|base), FACT_WORDING ("200+"/"at least 200"
  for the user filter), TECH_NOT_WHITELISTED (tech outside F-SKILLS unless negated/aspirational: "haven't yet used",
  "keen to learn", "would be glad to pick up"), WRONG_PROJECT (book-only terms: pipeline, YAML, logging, Streamlit,
  kNN, CSR, Book-Crossing; churn-only: Random Forest, one-hot, tenure, Telco — using the sentence + previous-sentence
  context), PLURAL_OVERGEN, UNVERIFIABLE_SELF_CLAIM (lexicon), PROFILE_UNCONFIRMED (availability/hours/CGPA/phone
  claims unless the value is a confirmed profile field), ANGLE_LEAK (location/proximity claims not in facts).
  Target on `factcheck_pairs.jsonl`: recall on `unsupported` ≥ 0.80 by the deterministic layer alone, ZERO false
  blocks on `ok` sentences. Pytest must assert both.
- `hq/models/benchmark/{__init__,suite,scoring}.py` + `tasks/{parse_job,eligibility,title_filter,write_paragraph,
  factcheck,classify_email}.py`. `python -m hq.models.benchmark [--quick|--full] [--model ID] [--task T]`,
  `make bench`. Each model benchmarked alone (others unloaded) at temperature 0; quick ≈ 3 min/model (subsets),
  full ≈ 15 min/model. Metrics per task: n, accuracy/precision/recall/f1 as relevant, json_valid_first,
  json_valid_after_repair, tok_s_gen, tok_s_prompt, ttft_ms, peak_footprint_gb; details JSON in
  `data/artifacts/bench/<model>/<task>.json`. write_paragraph: 5 prompts (Readyly, Stripe, pharma&, EPFL, TEEP-CCU)
  built from facts.yaml + the job text only (NEVER legacy `angle` notes); score = share of sentences with zero
  deterministic violations, word-count compliance, cliché count. Writes `benchmarks` rows; then `roles.assign()`.
  Events: `benchmark.started|progress|done`, `roles.updated`.
- Adapters: `hq/adapters/openai_compatible.py` (managed via ModelManager when `adapter_config.managed` or explicit
  `base_url`; runs a prompt file + schema with the task payload) and `hq/adapters/claude_code.py` (uses the runner +
  budget). Register them in `build_adapters()`. Pipeline agents remain on `sim` in phase (b).
- Config: `config/claude_prices.yaml` (seed EMA per task type, USD), settings keys `model_pool_budget_gb:30`,
  `usability_mode:true`, `claude_model:"sonnet"`, `claude_signoff_model:"opus"`, `claude_per_call_cap_usd:0.5`,
  `require_claude_signoff:true`, `benchmark_on_new_model:true`.

## 3. API additions (auth as CONTRACT §2)
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /api/models | – | `{models: Model[], roles: RoleAssignment[], servers: Server[], memory: Memory, benchmark: BenchState, claude: ClaudeState}` |
| POST | /api/models/rescan | – | `{queued:true}` |
| POST | /api/models/benchmark | `{model_id?, suite:'quick'|'full'}` | `{queued:true}` |
| PATCH | /api/roles | `{role, model_id}` (override) or `{role, reset:true}` | `{roles}`; 409 `{error:'independence'}` if writer == fact_checker |
| POST | /api/models/{id}/pin | `{pinned: bool}` | `Model` |
| POST | /api/models/{id}/unload | – | `{ok}` |
| GET | /api/budget | – | `{date_ist, spent_usd, reserved_usd, budget_usd, calls, call_cap, by_task: {...}, deferred_tasks, claude_available, last_error}` |
SSE: `model.discovered`, `model.status`, `benchmark.started|progress|done`, `roles.updated`, `budget.updated`,
`claude.status`. Stats: `claude_cost_today_usd`, `claude_calls_today`, `local_tokens_today` become real.
```ts
type Model = { id; runtime:'mlx'|'ollama'|'lmstudio'|'llamacpp'; name; modality; complete; incomplete_reason; runtime_supported;
  size_gb; params_b; quant; ctx_len; est_ram_gb; measured_ram_gb; status:'available'|'loaded'|'broken'|'unsupported';
  pinned; roles: string[]; scores: Record<string /*task*/, {accuracy?, f1?, recall?, precision?, json_valid_first?, tok_s_gen?, peak_footprint_gb?}>;
  role_scores: Record<string /*role*/, number>; last_benchmark_at };
type RoleAssignment = { role; ranked: {model_id; score; source:'auto'|'override'}[]; needs_claude_signoff?: boolean };
type Memory = { total_gb; available_gb; pool_used_gb; pool_budget_gb; pressure:'normal'|'warn'|'critical'; user_active; on_battery; usability_mode };
type BenchState = { running: boolean; model_id?; task?; progress?: number; eta_s? };
type ClaudeState = { available: boolean; logged_in: boolean; reason?: string; model; signoff_model };
```

## 4. UI (web/src/pages/Models/ + header budget gauge + Settings›Budget)
Leaderboard (model cards/table: runtime badge, size, RAM measured vs est, tok/s, JSON validity, per-task scores
with mini bars, assigned roles as chips, status/pinned), role assignment panel (ranked per role, override dropdown,
independence error surfaced), memory bar (pool used vs budget, system available, pressure, usability mode badge),
broken-models card with reasons, "Rescan" and "Benchmark (quick/full)" buttons with live progress, Claude status card
("Not logged in — run `claude auth login`" when unavailable). Header budget gauge and Settings›Budget use `/api/budget`.

## 5. Tests (offline unless marked slow)
Fake HF cache trees (complete / index-with-missing-shard / `.incomplete` blob / ref-only / unsupported model_type /
embedding / whisper); memory helpers (own PID footprint > 0); manager eviction + budget + waiting_memory with a fake
spawner; client + json_utils (think tags, fences, repair) with respx; router escalation ladder (bad JSON → next model
→ Claude shim → exhausted); roles assignment/floors/independence/override validation; budget reserve/commit/defer at
cap and IST day rollover; Claude runner with a fake `claude` shim on PATH (success, is_error, not logged in,
`error_max_budget_usd`, invalid structured_output); fact_deterministic on the gold pairs (recall ≥ 0.80, zero false
blocks). Slow (`-m slow`): one real mlx_lm.server round-trip on Qwen3-0.6B; quick benchmark of one model.
