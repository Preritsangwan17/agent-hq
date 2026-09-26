# Agent HQ

Agent HQ is Prerit's own AI-powered internship and job agent. It runs on his Mac (Safari at http://localhost:8765),
finds AI/ML internships, jobs and funded programmes, scores each one against his career plan, checks eligibility,
pay (₹/month vs living cost) and scams, drafts fact-checked applications, and sends only when every gate passes.
Anything a site won't let a bot do lands in **Needs Prerit**, pre-filled so it takes a couple of minutes. It starts
in **DRY RUN**: nothing leaves the Mac until you go live.

**Local AI first.** Models on the Mac (free, private) do the work; cloud models are used only when they add real
value — your Claude and ChatGPT subscriptions first (already paid for), then pay-per-token Grok. Every engine and
every model has an on/off switch, and the **AI usage & limits** page shows what each one used and what is left.

## What works

| Part | What it does |
|---|---|
| Discovery | Greenhouse / Lever / Ashby job boards, remote feeds (Remotive, Arbeitnow with visa sponsorship, Himalayas, Jobicy, We Work Remotely), programme pages (off until you read their terms), job-alert emails, **Paste a link** (Settings › Sources), plus suggested boards for European/Canadian/Australian AI companies (off until you enable them). GET-only, robots.txt respected, polite delays. |
| Checks | Title filter, eligibility rules + quoted model check, availability, scam/fee check, pay → ₹/month vs living cost. Unclear cases become one-click keep/drop decisions. |
| Match score | Every role is scored 0–100 against the career plan in `config/career.yaml` with twelve explained factors: skills, projects, education, experience, location priority (Europe / Russia / Canada / Australia first, India second, anywhere else only when unusually relevant), visa, internship vs full-time, pay, company, AI/ML relevance, eligibility probability and career value. It also marks stepping-stone roles (data engineering, MLOps, backend at AI companies). Only matches ≥ 60 get an application (the best first); the rest are parked with the reason, and **Apply anyway** is one click. |
| AI engines | Local models via Ollama / MLX / LM Studio, benchmarked on your real data and assigned to roles; optional Claude CLI and ChatGPT (Codex CLI) on your subscriptions; optional Grok (xAI API). Switches: Both / Local only / Cloud only / None, each provider, each local model. **API-saving mode** (default) keeps optional work local. |
| Writing | Cover letters built only from your verified facts, checked by fact rules, an independent local checker, a quality gate and a cloud sign-off. One-page résumé from approved bullets. |
| Applying | Email (only to an address quoted on the posting), or a pre-filled pack for ATS forms and LinkedIn/Internshala-type sites. Approve-first is on for your first live applications. |
| Inbox | Reads Gmail (read-only until you go live). Interview / assessment / offer / money / legal mail locks the thread (HQ never writes there), raises an alert, a macOS banner and a Needs item. Simple info requests get a gated draft. One follow-up at day 10 if nobody replied. |
| Safety | PAUSE ALL, Freeze outbound, forced dry run, typed GO LIVE from the Mac only, audit log, redaction of secrets and your phone number from anything sent to a model. |
| Upkeep | Nightly database backup (14 kept), auto-start after login (launchd), crash recovery that checks Sent before any resend. |

Not built: the daily Strategist report and the Analytics charts (the pages exist but are placeholders).

## Install and start (once)

Easiest of all: download https://github.com/Preritsangwan17/agent-hq/archive/refs/heads/main.zip, open the
`agent-hq-main` folder in Finder and double-click **Start Agent HQ.command** (the first time: right-click → Open →
Open, because macOS asks about downloaded files). **Stop Agent HQ.command** stops it.

Or: paste this one line into Terminal (installs everything, downloads HQ into `~/agent-hq`, starts it and
opens Safari):

```sh
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Preritsangwan17/agent-hq/main/install.sh)"
```

Or by hand — needs Homebrew, `uv` and Node (`brew install uv node`):

```sh
cd agent-hq
./start.sh                 # checks tools, installs deps, builds the web app, prepares the database, starts HQ
```

Open **http://localhost:8765** in Safari. The first visit asks you to set a passcode (≥ 6 characters). After that
you log in with it (the session lasts 30 days).

Start automatically after every login (recommended):

```sh
make install-launchd       # installs the LaunchAgent, starts HQ, checks notifications + the cloud model
make uninstall-launchd     # undo
```

Day to day: `make up` starts, `make down` stops (it also unloads the LaunchAgent until your next login).

## Local AI on your Mac (free) — do this first

Your MacBook Pro (M4 Pro, 48 GB) runs good models locally. Install Ollama and the recommended set in one go:

```sh
cd ~/agent-hq && make models        # installs Ollama if needed, then ~39 GB of models (core set)
make models-all                     # optional: the core set plus extra checkers (~105 GB)
```

Or click **Download** next to each model on the **Models** page (Ollama must be running). The list lives in
`config/local_models.yaml`:

| Model | Role | Why |
|---|---|---|
| `qwen3:30b-a3b` | writer, job parser, eligibility | 30B quality at ~3B speed on Apple silicon |
| `gemma3:12b` | fact-checker, email classifier | a different family from Qwen, so it can check Qwen's writing |
| `phi4:14b` | second fact-checker | lets the final sign-off run locally instead of in the cloud |
| `qwen3:4b` | title filter, email triage | small and fast for high-volume work |

HQ notices new models within 10 minutes (or click Rescan), benchmarks them on your real data and assigns roles.
The model pool uses up to 32 GB of the 48 GB and shrinks to 8 GB while you're using the Mac (Usability mode).
Each model has an on/off switch on the Models page.

## Cloud models (optional)

Used only when the local models can't do a task, or for the final sign-off when no second local checker exists
(API-saving mode). Switch each one on in **AI usage & limits** or Settings › AI & budget:

1. **Claude CLI** (your Claude subscription, no per-call cost): install Claude Code, run `claude auth login`,
   switch it on. HQ uses at most 30 calls per 5-hour window (editable) so the rest of your plan stays yours.
2. **ChatGPT — Codex CLI** (your ChatGPT subscription, no per-call cost): `brew install codex`, run
   `codex login` (sign in with ChatGPT), switch it on. Same 5-hour share limit.
3. **Grok (xAI API, pay per token)**: add your key to `.env` (never paste it into chat or code):
   ```
   HQ_XAI_API_KEY=xai-…
   ```
   HQ never spends more than the daily limit (Settings › AI & budget, default $2); over it, Grok work waits
   until midnight IST.

Subscriptions are tried before Grok (switchable). Prompts are redacted (your phone number and secrets never
leave the Mac) and every answer is validated before it's used.

**What the usage page can and can't know:** HQ's own call counts, spend and limits are exact. Grok's per-call
cost is exact when xAI reports it (otherwise estimated from `config/cloud_prices.yaml`, and labelled so). xAI
doesn't give HQ your account balance, so "remaining credit" is an estimate from the balance you type in. For the
Claude and ChatGPT plans, the page shows the window percentages only when the CLI reported them (the Codex CLI
does in its JSON output; a "limit reached, resets in …" message pauses that provider until the reset); otherwise
it says "not reported" — check `/usage` in Claude Code or `/status` in Codex.

## Connect Gmail (read-only)

Settings › Gmail walks you through it:

1. Create a Google Cloud project and enable the Gmail API.
2. OAuth consent screen: External, add yourself as a test user, then **Publish app** ("In production"). Testing
   mode expires the token after 7 days. Google's "unverified app" warning is expected for a single user.
3. Credentials › OAuth client ID › **Desktop app**; paste the ID and secret into Settings › Gmail (saved to `.env`).
4. **Connect Gmail (read-only)** — Google opens in a new tab; approve and come back.

HQ stores only mail related to your applications, companies you applied to, ATS senders and job alerts.

## Go live (sending for real)

Settings › Autonomy & Mode › Checklist, **on the Mac itself**:

1. Gmail connected and healthy · required profile fields confirmed (Settings › Profile) · 5 dry-run applications
   marked reviewed (button on each opportunity page) · golden fact tests green (Run now) · caps set · a final
   sign-off available: two independent local checkers or a cloud model (or "accept local checks only").
2. **Grant send permission** (second Google consent).
3. **Write live flags to .env**, then restart: `make down && make up`.
4. **Send self-test** — one email to your own address.
5. Type **GO LIVE**. HQ starts in approve-first: every application waits for your OK in Needs Prerit.

**Back to DRY RUN** is one click there, any time. If `.env` still forces dry run while Gmail can send, the worker
refuses to start and a red banner says why.

## Using it

- **Command Center**: live agents and pay stats. **Pipeline**: every opportunity by stage. **Map**: where they are.
- **Needs Prerit**: your lane — packs to submit (copy buttons, résumé file, direct link), approvals, keep/drop
  decisions, interview/offer alerts. Mark each done when handled.
- **Inbox**: replies, locks, reply drafts (edit / send / discard).
- **Opportunity page** (click any card): the letter with per-sentence fact checks, eligibility quotes, scam
  signals, the match-score breakdown (every factor, its weight and why), **Apply anyway**, timeline.
- **AI usage & limits**: switches for local / cloud / each provider, API-saving mode, Claude and ChatGPT
  usage windows, Grok spend (today, month, 30 days, by model and task), HQ's daily limit and estimated credit.
- **Settings › Sources**: turn boards on/off, paste a link, see every request HQ made.
- **Settings › Simulation**: the simulator adds fictional `SIM` opportunities for demo — turn it **off** for real use.
- **Rules**: match threshold, pay ratio, daily caps. **Agents**: pause/edit agents or add your own.
- **Career plan**: `config/career.yaml` — regions and countries in priority order, target roles and stepping
  stones, target companies and programmes, factor weights. Edit it and new scores use it.
- The bell (top right) lists notifications; interview and offer alerts also show as macOS banners.

## Keep the Mac awake

- Keep it on AC power. HQ runs `caffeinate -i` while it's up (Settings › Schedules › keep awake).
- Optional: `sudo pmset -c sleep 0` (never sleep on AC). Closing the lid still sleeps the Mac unless an external
  display is connected (clamshell mode).
- With FileVault on, nothing runs after a reboot until you log in. That's expected; don't turn FileVault off.
- Missed schedules catch up once when the Mac wakes.

## Where data lives

| Path | What |
|---|---|
| `.env` | Passcode hash, session secret, Gmail client + token, xAI key. Private (mode 600), never committed. |
| `config/career.yaml` | The career plan the match score uses. `config/local_models.yaml`: recommended local models. |
| `data/hq.db` | The database. `data/backups/` holds nightly copies (14 kept); `make backup` makes one now. |
| `data/logs/` | `api.log`, `worker.log`, `supervisor.log`, `launchd.*.log`. |
| `data/artifacts/` | Résumés and letters per application. `data/mail/` holds stored email bodies. |
| `config/` | Facts, answer bank, sources, rules, living costs, prices — plain files you can edit. |
| `agents/*.yaml` | One file per agent; edits reload within seconds. |

To restore a backup: `make down`, copy `data/backups/hq-YYYY-MM-DD.db` over `data/hq.db`, `make up`.

## Troubleshooting

- **Page won't load**: `make up` and read its output; logs are in `data/logs/`. Port busy → `HQ_PORT=8766` in `.env`.
- **"Worker down"** in the header: `tail -50 data/logs/worker.log`. A red banner means a safety refusal (see Go live).
- **Nothing gets drafted**: no model available — run `make models` (or start Ollama/LM Studio), or switch on a
  cloud provider; check Models and AI usage & limits (Grok tasks wait when the daily limit is used up). Also check
  the match score: roles below 60 are parked on purpose.
- **Gmail says reconnect**: Settings › Gmail › Disconnect, then Connect again.
- **No macOS banners**: System Settings › Notifications › allow Script Editor (or terminal-notifier).
- **Forgot the passcode**: `make down`, delete the `HQ_PASSCODE_HASH=` line from `.env`, `make up`, set a new one.

## For development

```sh
make test          # all tests (no test touches the network or Google)
make mock-ats      # local fake ATS on :8799 for the browser adapter
make bench         # benchmark local models
make models        # install Ollama + the recommended local models
make audit         # export the first 20 eligibility/pay verdicts to check by hand
```
