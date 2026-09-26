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

## The models it uses

HQ works with whatever you give it:

1. **xAI (Grok)** — add your key to `.env` (never paste it into chat or code):
   ```
   HQ_XAI_API_KEY=xai-…
   ```
   Keep credit on the account (console.x.ai). No restart needed. With the key present, cloud work (sign-off,
   polish, escalations when no local model can do a task) goes to xAI. Settings › Budget › Cloud model lets you
   pick Auto / Claude CLI / xAI and the model names, and shows whether the key works. If the account runs out of
   credit you get one Needs item, not failing tasks.
2. **Claude CLI** (optional): `claude auth login` in Terminal.
3. **Local models** (optional, free): Ollama or LM Studio running, or MLX models in the Hugging Face cache. HQ
   finds them (Models page), benchmarks them and assigns roles. Rescan from the Models page.

Spending is capped per day (Settings › Budget, default $5) and per call; over the cap, cloud tasks wait until
midnight IST.

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
- **Needs Prerit**: your lane — packs to submit (copy buttons, résumé file, direct link), approvals, keep/drop
  decisions, interview/offer alerts. Mark each done when handled.
- **Inbox**: replies, locks, reply drafts (edit / send / discard).
- **Opportunity page** (click any card): the letter with per-sentence fact checks, eligibility quotes, scam
  signals, fit breakdown, timeline.
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
| `.env` | Passcode hash, session secret, Gmail client + token, xAI key. Private (mode 600), never committed. |
| `data/hq.db` | The database. `data/backups/` holds nightly copies (14 kept); `make backup` makes one now. |
| `data/logs/` | `api.log`, `worker.log`, `supervisor.log`, `launchd.*.log`. |
| `data/artifacts/` | Résumés and letters per application. `data/mail/` holds stored email bodies. |
| `config/` | Facts, answer bank, sources, rules, living costs, prices — plain files you can edit. |
| `agents/*.yaml` | One file per agent; edits reload within seconds. |

To restore a backup: `make down`, copy `data/backups/hq-YYYY-MM-DD.db` over `data/hq.db`, `make up`.

## Troubleshooting

- **Page won't load**: `make up` and read its output; logs are in `data/logs/`. Port busy → `HQ_PORT=8766` in `.env`.
- **"Worker down"** in the header: `tail -50 data/logs/worker.log`. A red banner means a safety refusal (see Go live).
- **Nothing gets drafted**: no model available — add the xAI key or start Ollama/LM Studio; check Models and
  Settings › Budget (tasks wait when the daily cap is used up).
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
