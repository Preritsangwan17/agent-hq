# Agent HQ — Phase (c) contract: the real pipeline (DRY RUN)

Extends `docs/CONTRACT.md` and `docs/CONTRACT_B.md`. PLAN.md → "Pipeline and gates" is the design; this file pins
interfaces. Phase (c) replaces the `sim` adapter for real opportunities while keeping sim available (setting
`sim_enabled`). **Mode stays DRY_RUN**: outbound email goes to `mock_mailbox`, form submission only to the local mock
ATS (`mock_ats/`, port 8799). No Gmail code in this phase.

## 1. Hard rules
- Truthfulness: every outbound string (letter, cold email, research statement, résumé summary line, form answer,
  subject line) passes the fact gate. Unconfirmed `profile_fields` never appear in outbound text. Legacy `angle`
  notes never reach the Writer.
- Terms of service: fetch only sources with `tos_status='allowed'` and robots.txt permission; hard block on
  `config/manual_lane.yaml` domains (linkedin.com, internshala.com, naukri.com, wellfound.com, indeed.*,
  workatastartup.com, ycombinator.com). Record `tos_url` + `tos_reviewed_at` for every enabled source.
- Polite fetching: robots (24 h cache), per-domain min delay 5 s HTML / 1 s API, ETag/If-Modified-Since, UA
  `AgentHQ/1.0 (personal job search; +local)`. GET only. `util/netguard.py`: in DRY_RUN any non-GET to a
  non-localhost host raises.
- Never create accounts, log in, solve CAPTCHAs, or attempt assessments. Sensitive IDs are never provided.

## 2. Profile & answers
- Seed `profile_facts` from `config/facts.yaml` (status verified; `F-*` ids). Seed `profile_fields` keys: phone,
  cgpa, marks_x, marks_xii, grad_year, semester, home_city, home_living_cost_inr, availability_windows (JSON list of
  {from,to,hours_per_week,mode}), hours_cap_term, passport (yes/no), dob, address (share_policy never), all
  `confirmed_by_prerit=0` until Prerit edits them in Settings › Profile & Facts (UI + `PATCH /api/profile/fields/{key}`
  loopback-or-authenticated; every edit audited; `confirmed_by_prerit=1` on save).
- `answer_bank` seeded from `config/answer_bank.yaml`: patterns for name, email, LinkedIn, GitHub, citizenship,
  work authorization (India: yes; elsewhere: needs sponsorship), relocation, salary expectation ("flexible; standard
  rate for the role and location"), EEO/demographics → "Prefer not to say" (policy auto only if that option exists),
  sensitive IDs → never, availability/start date/CGPA/phone → only from confirmed fields else needs_prerit.

## 3. Discovery (Scout, `hq/pipeline/discover/`)
- `fetch.py` polite fetcher (+ `domain_policy`, `http_cache` tables). `greenhouse.py`, `lever.py`, `ashby.py`
  (public board APIs; seed slugs from `legacy/scratchpad/scan*.txt` companies + a curated list in
  `config/sources.yaml`), `program_pages.py` (SRFP, Summer@EPFL, UTRIP, MLH, TEEP program table + detail pages;
  daily; diff-based), `manual.py` (paste-a-link box: stores URL + pasted text; no fetch for manual-lane domains).
  Remote feeds are phase (e).
- Title/role prefilter: `classify.title` (role `title_filter` via router; deterministic regex first, LLM for the
  rest). Must fix the "Internal/International" false positives. Keep internships, co-ops, fellowships, junior/new-grad,
  part-time, contract, freelance, Werkstudent in AI/ML/data/software/research.
- `parse.job` (role `parser`): posting → `JobParse` JSON {company, title, kind, location {city,country_iso2,work_mode},
  pay_raw, deadline_raw, start/duration/hours, requirements quotes, apply {channel,email,url}, benefits}. Every
  extracted requirement carries an exact quote (non-substring quotes are dropped).
- Dedupe (`dedupe.py`): canonical key (ATS id or normalized URL); fuzzy company ≥ 92 & title ≥ 90 & compatible
  location & posted within 60 days → merge into `opportunity_sources`.

## 4. Verify (Verifier, `hq/pipeline/verify/`)
- `link.py` (job still on board / 200 + no closed markers), `deadline.py` (1-day conservative buffer; rolling →
  re-verify every 3 days), `eligibility_rules.py` (deterministic: grad-year windows, final/pre-final year, semester,
  PhD/Master's-only, CGPA/marks minima vs confirmed fields, enrolment-country and work-authorization/visa
  requirements; time-aware: Prerit is 2nd year in 2026-27 and a rising 3rd-year from May 2027) + `eligibility_llm.py`
  (role `eligibility`; exact quotes) → confidence = model accuracy × agreement(1.0/0.4) × grounding share; a
  deterministic hard hit decides alone; < `eligibility_threshold` → escalate (alt local → Claude `verify.eligibility_hard`).
  Skill gaps lower fit, never eligibility. `availability.py` (role dates/hours vs confirmed availability windows +
  hours cap; unknown → needs_info → Needs Prerit decision). `pay.py`/`fx.py`/`living_cost.py` (already built) +
  `living_cost_research.py`: phase (c) replaces provisional living-cost rows with researched values (sources cited in
  `source_note`, confidence medium) — research runs as a Claude or local summarization task over fetched public pages;
  unseeded city → decision item. `scam.py` (fee lexicon incl. application fees e.g. OIST ¥5,000, `config/known_mills.yaml`
  11 names, certificate-only wording, free-mail recruiter for brand names, lookalike domains, early ID/bank requests,
  crypto/cheque). Acceptance: pay_ratio ≥ `min_pay_ratio`, or funded program (housing+meals+travel + allowance ≥
  `funded_program_min_inr`); unpaid → filtered; unknown pay → decision item (setting `unknown_pay_policy`).
- `score.py` fit 0–100 per PLAN (role 25, skills 20, eligibility conf 15, pay ratio 15, source prior 10, deadline 5,
  location 5, program 5). Draft if ≥ `fit_draft_threshold`; Claude polish if ≥ `fit_polish_threshold`;
  `daily_draft_cap`.

## 5. Draft + gates (Writer, Fact-Checker, Reviewer)
- Writer (role `writer`, `prompts/writer.md`, schema `schemas/draft.json`): input = facts (ids+text), verified job
  quotes (ids `J1..`), doc-type rules (`config/doc_types.yaml`: cover_letter 170–230 words / 3–4 paragraphs;
  cold_email ≤ 170 words + subject; research_statement 150–250; profile_summary; form_answers), salutation rules,
  fixed sign-off, repo link exactly once, 2 gold exemplars from `legacy/applications` letters (with "more than 200"
  wording). Output `{sentences:[{text, kind: claim|motivation|job_reference|logistics|salutation|closing, fact_ids,
  job_quote_ids}]}` → `documents` + `document_sentences` (author_model + lineage).
- Fact gate: (a) `fact_deterministic` (phase b), (b) local verifier (role `fact_checker`, model must satisfy
  `checker_allowed(checker, lineage)`), per sentence `{verdict: supported|unsupported|partial|na, unsupported_span,
  explanation}` (partial = fail), (c) Claude sign-off (`factcheck.signoff`, `claude_signoff_model`, different from any
  Claude model in lineage) when `require_claude_signoff`. Failure → targeted rewrite → ALL layers re-run; 3 loops →
  Claude polish (budget) → re-verify → else `needs_prerit` review_letter. Results in `fact_checks`, `gate_results`.
- Quality gate (`gates/quality.py`): org named + ≥ 1 job quote; zero clichés (`config/cliches.yaml`); length /
  salutation / sign-off; specificity rubric ≥ 3/5 (local LLM, Claude on disagreement); shingle Jaccard < 0.6 vs last
  20 letters.
- Résumé Builder (`hq/resume/builder.py` port of `legacy/applications/build.py` TAILOR/resume_html/Chrome headless
  PDF; `hq/resume/compact.py` fpdf2 core-font version): approved bullets only (tied to fact ids; "more than 200"),
  generated summary line passes the fact gate; post-check with pypdf: 1 page, text ⊆ approved strings.

## 6. Apply (Applicant) — DRY RUN
- Pre-submit recheck (link, deadline, scam, pause, mode, caps, approval sha, budget). `apply/guard.py`: one
  transaction re-reads global_pause / freeze_outbound / agent+capability pause / mode / approval sha256 / caps /
  idempotency, writes `outbound_log` intent (deterministic Message-ID), then sends via the channel.
- Channels: `email` (only to an address quoted on the official page with matching org domain) → in DRY_RUN
  `MockMailer` writes `mock_mailbox`; `ats_form` → Needs Prerit pack by default; browser adapter (Playwright,
  channel chrome) fills ONLY the local mock ATS (`mock_ats/app.py`: Greenhouse-shaped posting + hosted form + CAPTCHA
  variant + login-wall variant + fee-scam posting + ineligible posting) and aborts any non-localhost request;
  `manual_pack` → `needs_prerit` kind submit_form with direct link, answers (copy buttons), letter, files, pay,
  deadline, est_minutes ≤ 2.
- Approve-before-submit (`autonomy=approve_first`): `needs_prerit` kind approve with letter/résumé/answers preview;
  approval binds to the sha256 of the exact documents+answers; any rewrite invalidates it.
- Caps from settings; per-recipient-domain 1 per 14 days; per-lab ≤ 3 cold emails/day.

## 7. UI additions
Detail page shows real documents, the sentence-level fact-check report (green/red, rule ids, cited facts on hover),
eligibility quotes, scam signals, gate results, agent timeline with escalation ladder + costs. Map shows real pins.
Needs page supports submit_form packs, approve items, decisions (unknown pay, unseeded city, availability),
review_letter. Settings › Profile & Facts edits `profile_fields` (+ shows `profile_facts` with evidence links).
Settings › Sources lists sources with ToS status, enable toggles, last poll, errors.

## 8. Acceptance (from PLAN)
≥ 30 real verified opportunities within 24 h each with ₹/month + ratio (discovery is read-only GETs); golden
fact-gate tests pass; end-to-end dry-run applications appear only in the mocks; a Greenhouse-style posting becomes a
pack with the phone field flagged missing; zero real outbound traffic (fetch log shows only GETs to allowed sources);
first 20 eligibility + pay verdicts exported for Prerit's audit (`make audit` → CSV in data/artifacts/audit/).
