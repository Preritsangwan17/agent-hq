# Agent HQ

Agent HQ is a local mission control that runs on your Mac and you use in Safari. A team of agents finds AI/ML/data/
software internships, jobs and funded programmes; checks each for eligibility, pay (₹/month vs living cost) and
scams; drafts fact-checked applications; and sends only when every gate passes. Anything a site won't let a bot do
lands in **Needs Prerit**, pre-filled so it takes a couple of minutes. It starts in **DRY RUN**: nothing leaves the
Mac until you go live.

## What works

| Part | What it does |
|---|---|
| Discovery | Greenhouse / Lever / Ashby job boards, remote feeds (Remotive, Arbeitnow with visa sponsorship, Himalayas, Jobicy, We Work Remotely), programme pages (off until you read their terms), job-alert emails, **Paste a link** (Settings › Sources). GET-only, robots.txt respected, polite delays. |
| Checks | Title filter, eligibility rules + quoted model check, availability, scam/fee check, pay → ₹/month vs living cost, fit score. Unclear cases become one-click keep/drop decisions. |
| Writing | Cover letters built only from your verified facts, checked by fact rules, an independent local checker, a quality gate and a cloud sign-off. One-page résumé from approved bullets. |
| Applying | Email (only to an address quoted on the posting), or a pre-filled pack for ATS forms and LinkedIn/Internshala-type sites. Approve-first is on for your first live applications. |
| Inbox | Reads Gmail through Google's OAuth (read-only until you go live). It fetches headers first and only fetches bodies for job-related mail. Interview / assessment / offer / money / legal mail locks automatic sending, raises an alert and gets a reviewable draft when safe. One gated follow-up at day 10 if enabled and nobody replied. |
| Company communication | Each opportunity has a **Company** tab with sender and link checks, a source-linked email timeline, offer facts, onboarding checklist and full correspondence. Selected, accepted and joining are tracked separately from application submission. |
| Safety | PAUSE ALL, Freeze outbound, forced dry run, typed GO LIVE from the Mac only, audit log, redaction of secrets and your phone number from anything sent to a model. |
| Strategist | A daily review at 07:30 IST (or **Run review now**): what worked, what didn't, best-paying roles, budget. It turns off sources that keep failing (never while every source fails, e.g. no Wi-Fi) and adds Greenhouse/Lever/Ashby boards only after checking they exist; everything else is a proposal for you. Works without any model (built-in summary); a cloud or local model words it when available. |
| Analytics | Funnel found → offer, found vs applied per day, reply rate by source / country / role (with n), which sources work, why roles were stopped, cloud spend vs cap, local tokens by model, pay histogram and pay by country. Every chart has a table view. |
| Upkeep | Nightly database backup (14 kept), auto-start after login (launchd), crash recovery that checks Sent before any resend. |

**Whose HQ it is:** Prerit Sangwan · sangwanprerit40@gmail.com. Letters are signed with that name, forms get that
email, the self-test goes only there, and HQ refuses to send from any other Gmail account. Both live in
`config/resume.yaml` (and the fact sheet `config/facts.yaml`); the sidebar and Settings › Profile show them.

The 11 applications from before HQ (the legacy shortlist in `legacy/applications`) are imported automatically on
the first start as **Frozen** items with real ₹ pay; answer the Needs Prerit item saying which ones you actually sent.

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

### Application Email lab

Open **http://localhost:8765/email-module** to test the separate email workflow and its dashboard. It starts in a local sandbox mailbox, so draft approval, send, reply detection and follow-up tracking can be checked without contacting a company. The Gmail tab uses the OAuth connection configured under Settings → Gmail when available. See [the email module guide](docs/EMAIL_MODULE.md) for the test command, limits and live access requirements.

## AI Control: local first

Open **http://localhost:8765/ai** for the active mode, recommendation, provider switches, usage, model memory,
and task/subtask routing history. Every mode includes Local AI; it cannot be disabled. Auto and all eight explicit
combinations of Local AI with Claude CLI, ChatGPT/Codex CLI and Grok are available. Changes apply to the next
provider dispatch without restarting; already-running calls finish normally. Auto respects switches set to OFF.

1. **Local AI (required)**: run Ollama or LM Studio, or use cached MLX models on Apple Silicon. Discover and
   benchmark them on Models, then assign roles. Required means enabled, not that an unavailable model is magically
   running: missing assignments and loaded models are shown separately.
2. **Claude CLI (optional)**: sign in with `claude auth login`.
3. **ChatGPT / Codex CLI (optional)**: install the Codex CLI and sign in with `codex login`. The integration uses a
   read-only sandbox with shell/browser tools disabled and no persistent sessions.
4. **Grok API (optional)**: set `HQ_XAI_API_KEY` privately in `.env`. Never paste keys into chat or commit them.

The router tries local role assignments first, validates JSON/schema and confidence, and checks available benchmark
quality. If local attempts fail, enabled providers are ranked by task: Codex for coding, Claude for writing/planning,
Grok for explicit external reasoning. Routine tasks prefer CLI assistance before metered API. These are explainable
capability rules, not a claim of measured universal provider superiority. Every attempt records model, task, parent
run, mode, reason, status, duration and available token/cost data. Existing job workflows split discovery, eligibility,
writing, local checking and storage into separate tasks. The coding preview describes routing; AI proposals do not
execute code or modify your files.

Independent external application sign-off remains a separate policy after local fact/quality checks. With all external
providers off, required sign-off waits. Change the requirement explicitly in Settings › Models & Budget if desired;
choosing Local AI Only never silently weakens application gates.

Daily dollar and call caps apply across external providers, and rate-limited providers rest for one hour. AI Control
shows HQ usage for today and the current month in IST, including Grok separately. Costs are estimates, not invoices;
CLI subscription quotas and account-wide remaining limits are unavailable through this integration. Login/key checks
do not perform generation. No extra paid calls are made to produce recommendations or telemetry.

## Connect Gmail (read-only)

Settings › Gmail walks you through it (sign in to Google as **sangwanprerit40@gmail.com** throughout):

1. Create a Google Cloud project and enable the Gmail API.
2. OAuth consent screen: External, add sangwanprerit40@gmail.com as a test user. Google's Testing mode can expire
   refresh tokens after 7 days. Publishing beyond private testing may require Google's OAuth verification, especially
   because reading Gmail uses a restricted scope. If Google shows an unverified-app warning, check that it names the
   project you created before continuing. [Google's Gmail scope guide](https://developers.google.com/workspace/gmail/api/auth/scopes).
3. Credentials › OAuth client ID › **Desktop app** › **Download JSON**. In Settings › Gmail choose that
   `client_secret_….json` file (or paste the client ID and secret instead). It is saved to `.env` only.
4. **Connect sangwanprerit40@gmail.com (read-only)** — Google opens in a new tab with your account pre-selected;
   approve and come back. If a different account gets connected, HQ says so and will not send from it.

HQ stores only mail related to your applications, known company and ATS senders, job alerts, or clearly job-related
subjects. It checks headers first; unrelated mail bodies are not fetched. The classifier can use earlier messages in the
same thread as context, while every extracted joining fact keeps a link to the message that stated it. Settings › Gmail has independent switches
for reading, classification, drafting, routine sending, approval before sending, and follow-ups. All outgoing mail
still requires the separate send grant and GO LIVE gates. **Ask Before Sending** starts ON.

The **Company** tab on each opportunity shows what arrived, why a sender or link needs review, the exact email source
for each offer fact, and a checklist based on stated instructions. A matching domain and a live posting do not alone
prove a company is legitimate. The strongest label also requires aligned Gmail authentication and a live posting on
a supported ATS. Unknown or suspicious cases stay for review; emailed links are not followed automatically. Public
LinkedIn profiles and documents are not treated as verified unless independently checked.

## Go live (sending for real)

Settings › Autonomy & Mode › Checklist, **on the Mac itself**:

1. Gmail connected and healthy · required profile fields confirmed (Settings › Profile) · 5 dry-run applications
   marked reviewed (button on each opportunity page) · golden fact tests green (Run now) · caps set · cloud model
   available (or "accept local checks only").
2. **Grant send permission** (second Google consent).
3. **Write live flags to .env**, then restart: `make down && make up`.
4. **Send self-test** — one email to your own address.
5. Type **GO LIVE**. HQ starts in approve-first: every application waits for your OK in Needs Prerit.

**Back to DRY RUN** is one click there, any time. If `.env` still forces dry run while Gmail can send, the worker
refuses to start and a red banner says why.

## Using it

- **Command Center**: live agents and pay stats. **Pipeline**: every opportunity by stage. **Map**: where they are.
- **Analytics**: what's working, with the Strategist's daily review underneath (**Run review now** any time).
- **Needs Prerit**: your lane — packs to submit (copy buttons, résumé file, direct link), approvals, keep/drop
  decisions, interview/offer alerts. Mark each done when handled.
- **Inbox**: replies, locks, reply drafts (edit / send / discard).
- **Opportunity page** (click any card): the letter with per-sentence fact checks, eligibility quotes, scam
  signals, fit breakdown, timeline, and the **Company** tab for communication and onboarding.
- **Settings › Sources**: turn boards on/off, paste a link, see every request HQ made.
- **Settings › Simulation**: the simulator adds fictional `SIM` opportunities for demo — turn it **off** for real use.
- **Rules**: fit threshold, pay ratio, daily caps. **Agents**: pause/edit agents or add your own.
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
| `.env` | Passcode hash, session secret, Gmail client + token, xAI key. Private (mode 600), never committed. Claude and ChatGPT keep their own logins (`claude auth login`, `codex login`). |
| `data/hq.db` | The database. `data/backups/` holds nightly copies (14 kept); `make backup` makes one now. |
| `data/logs/` | `api.log`, `worker.log`, `supervisor.log`, `launchd.*.log`. |
| `data/artifacts/` | Résumés and letters per application. `data/mail/` holds stored email bodies. |
| `config/` | Facts, answer bank, sources, rules, living costs, prices — plain files you can edit. |
| `agents/*.yaml` | One file per agent; edits reload within seconds. |

To restore a backup: `make down`, copy `data/backups/hq-YYYY-MM-DD.db` over `data/hq.db`, `make up`.

## Troubleshooting

- **Page won't load**: `make up` and read its output; logs are in `data/logs/`. Port busy → `HQ_PORT=8766` in `.env`.
- **"Worker down"** in the header: `tail -50 data/logs/worker.log`. A red banner means a safety refusal (see Go live).
- **Nothing gets drafted**: no model available or all switched off — check Settings › Models & Budget › Models
  on/off, log in (`claude auth login` / `codex login`), add the xAI key or start Ollama/LM Studio (tasks also wait
  when the daily cap is used up).
- **Gmail says reconnect**: Settings › Gmail › Disconnect, then Connect again.
- **No macOS banners**: System Settings › Notifications › allow Script Editor (or terminal-notifier).
- **Forgot the passcode**: `make down`, delete the `HQ_PASSCODE_HASH=` line from `.env`, `make up`, set a new one.

## For development

```sh
make test          # all tests (no test touches the network or Google)
make mock-ats      # local fake ATS on :8799 for the browser adapter
make bench         # benchmark local models
make audit         # export the first 20 eligibility/pay verdicts to check by hand
```
