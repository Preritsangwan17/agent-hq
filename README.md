# Agent HQ

Agent HQ is a local-first mission control that runs on this Mac. A team of agents (local LLMs plus Claude Code)
finds AI/ML/data/software internships, jobs and funded programmes, and checks each one for eligibility, pay and
scams. It drafts fact-checked applications and sends only when every safety gate passes. Anything a site will not
let a bot do lands in a **Needs Prerit** lane, pre-filled so it takes under two minutes. The dashboard shows every
agent live, the pipeline, and pay in ₹/month compared with local living costs.

## Status

**Phase (a): simulation + legacy import. Nothing is sent.**

- The agents run on a simulator. Simulated opportunities carry a small `SIM` tag, and the simulated
  Applicant writes only to an internal mock mailbox.
- The 11 items from the old shortlist are imported as frozen history. Agent HQ will not act on them until you
  answer "which of these did you actually send?" in Needs Prerit.
- The app makes no email, form, browser-automation or third-party POST requests. The only outbound call is a
  GET for FX rates to api.frankfurter.dev.

## Quick start

```sh
./start.sh          # checks tools, syncs deps, builds the web app if needed, migrates the DB, starts in background
./start.sh -f       # same, but in the foreground (Ctrl-C stops it)
```

Open **http://localhost:8765**. On your first visit you set a passcode (at least 6 characters). Setup works only
from this Mac (loopback); after that, you log in with the passcode.

Stop everything with `./stop.sh`.

## Where data lives

| Path | What |
|---|---|
| `data/hq.db` | SQLite database (WAL). `data/` is git-ignored and private (mode 700). |
| `data/logs/`, `data/run/` | Logs and pid files. |
| `data/artifacts/` | Generated files. The legacy letters and résumé PDFs are copied into `artifacts/legacy/<id>/`. |
| `data/fx/rates.json` | Daily FX cache. |
| `.env` | Passcode hash and session secret. Never committed. |
| `agents/*.yaml` | One file per agent. Edits hot-reload within about 3 s. |
| `config/fx_seed.json` | Fallback FX rates (to INR), used offline or when the API is down. |
| `config/living_costs.csv` | Monthly living cost per city. **Provisional estimates** until sourced figures replace them in phase (c). |
| `config/cities.csv` | City coordinates for the map. |

## Safety modes

- **DRY RUN** (the default, and the only mode in phase a). Everything runs end to end, but outbound actions go to
  mocks. Nothing leaves the Mac.
- **PAUSE ALL** stops every agent within about 2 s. **Freeze outbound** blocks sends but keeps research running.
- **SELF TEST** (from phase d) sends one real email, only to your own address.
- **GO LIVE** (later) needs the go-live checklist, a typed confirmation, and a request from this Mac. The
  recommended setup approves each of the first 10 live applications by hand.

Agent HQ never pays, enters card details, creates accounts, types passwords, solves CAPTCHAs or acts on
interviews, offers, money or legal matters. Those always come to you.

## Useful commands

```sh
python -m hq.importer.legacy --src legacy/applications   # re-import the old shortlist (idempotent); --offline uses the FX seed
python -m hq.pipeline.verify.fx USD TWD                  # current rates to INR
python -m hq.pipeline.verify.fx --write-seed             # refresh config/fx_seed.json
make test                                                # unit tests (or: uv run pytest)
```

## How pay is shown

- Each item shows ₹/month (min to max), its original currency and period, and a ratio against the living cost
  for the city (for remote roles, the cost of working from home in India).
- Hourly pay with unstated hours is marked *variable* and shown per hour. Agent HQ never assumes 40 h/week.
- Lump sums are spread over the programme length only when that length is known.
- Unknown pay stays unknown and becomes a one-click decision for you.

## Coming next

- **(b)** Local model discovery and benchmarks, model routing, and the Claude adapter with a daily budget.
- **(c)** The real pipeline in dry run: ATS, programme and TEEP sources; eligibility, pay and scam checks; the
  fact gate; the résumé builder; the Needs Prerit packs; the map. Researched living costs replace the provisional
  ones.
- **(d)** Gmail (read-only first), reply classification with notify-only locks, one follow-up per application,
  macOS notifications, and SELF TEST plus the go-live checklist.
- **(e)** The daily Strategist report, analytics, launchd auto-start after login (with FileVault, nothing runs
  until you log in), backups, and phone access over Wi-Fi.
