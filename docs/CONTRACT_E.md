# Agent HQ — Phase (e) contract: Strategist, analytics, hardening, launchd

Extends CONTRACT.md / _B / _C / _D.

## 1. Strategist (daily 07:30 IST, `strategy.daily_review`, Claude via runner; local summarizer fallback)
Input: last-24 h/7-day aggregates (per source: found/verified/applied/replies; gate failure reasons; reply rates by
country/role/kind; budget use; errors). Output schema: `{report_md, actions:[{type, params, rationale, risk}]}`.
Auto-apply ONLY whitelisted low-risk actions: `add_ats_slug` (validated by one API GET before enabling),
`disable_source` (≥ 5 consecutive errors or zero yield for 14 days), `tune_keywords` (within the acceptance-rule
vocabulary only). Everything else (thresholds, rules, new HTML/program domains) is a proposal shown in the UI for
Prerit (new domains need robots + ToS approval). `strategy_reports` row + Command Center card + Analytics tab.

## 2. Analytics page (Recharts; load the `dataviz` skill before building charts)
Applications per day/week, funnel found→offer, reply rate by source/country/role (always show n), source yield table
("which sources work"), gate failure reasons, Claude spend vs cap, local tokens by model, pay histogram, pay by country.

## 3. Sources added
Remote feeds with attribution + link-back: Remotive (≤ 4 calls/day), Arbeitnow (`visa_sponsorship=true` filter),
Himalayas, Jobicy (≤ 1/h), We Work Remotely RSS; remote roles whose `candidate_required_location` excludes India →
ineligible(location).

## 4. Hardening
- launchd: `scripts/install_launchd.sh` / `uninstall_launchd.sh` (LaunchAgent `com.prerit.agenthq`, RunAtLoad,
  KeepAlive, ThrottleInterval 30, WorkingDirectory repo, PATH incl. /opt/homebrew/bin and ~/.local/bin, logs in
  data/logs). Verify `claude` auth + osascript notifications from the launchd context.
- Backups: nightly `sqlite3 .backup` to data/backups (keep 14), weekly VACUUM, hourly `wal_checkpoint(TRUNCATE)`;
  retention events 60 days / runs 90 days (gzip after 7).
- `debug.failed_run`: repeated error signature (3×/1 h) → Claude diagnosis JSON; auto-apply only restart agent /
  disable source / lower concurrency; else recommendation.
- Per-source circuit breakers (5 errors → disabled 6 h, Strategist informed).
- Optional: 3D globe toggle (react-globe.gl, desktop only), headed "open + prefill, Prerit clicks Submit" mode for
  allowlisted ATS domains, self-signed HTTPS for LAN, PWA manifest.
- README complete: start/stop, first-run passcode, add an agent, add a model, change rules, connect Gmail, go live,
  keep the Mac awake (AC power, `caffeinate`, optional `sudo pmset -c sleep 0`, clamshell caveat), FileVault note
  (nothing runs after reboot until login), troubleshooting.
