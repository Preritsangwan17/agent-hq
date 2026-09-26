# Agent HQ — Phase (d) contract: Gmail, replies, follow-ups, notifications, go-live

> **Update (Sept 2026):** the cloud layer described here was replaced by local-first routing with optional providers (Claude CLI, ChatGPT Codex CLI, Grok) and API-saving mode; the fit score by the career-plan match score. See `docs/CONTRACT_F.md`. Where this contract says "Claude" as HQ's cloud model, read "a cloud model per hq.llm.policy".

Extends CONTRACT.md / _B / _C. PLAN.md → "Security and safety" (mode table) + "Pipeline and gates" §9–10.

## 1. Gmail connection (capability-based modes)
- Prerit creates a Google Cloud OAuth **Desktop** client (consent screen "In production" to avoid the 7-day
  refresh-token expiry of Testing mode; single-user unverified app warning is expected). A Settings › Gmail wizard
  shows these steps with links and a field for client_id / client_secret, which are written to `.env`
  (`HQ_GMAIL_CLIENT_ID`, `HQ_GMAIL_CLIENT_SECRET`) — loopback-only route.
- `hq/gmail/auth.py`: installed-app flow (google-auth-oauthlib `InstalledAppFlow.run_local_server(port=0)`), started
  from the UI on loopback only; Prerit consents in his own browser. Stores the refresh token in `.env`
  (`HQ_GMAIL_REFRESH_TOKEN`) + granted scopes (`HQ_GMAIL_SCOPES`). Phase-(d) default requests ONLY
  `gmail.readonly`. The go-live step requests `gmail.send` + `gmail.compose` in a second consent.
- Startup check: if `HQ_FORCE_DRY_RUN=1` and granted scopes include send/compose → refuse to start the worker
  (clear error). Token health check hourly; failure → notification + needs_prerit.
- Tests use `hq/gmail/fake.py` (an in-memory Gmail API double with history ids, threads, messages, labels, sent).
  No test ever touches Google.

## 2. Inbox Watcher
- Poll `users.history.list` every 3 min from the stored `historyId` (404 → full sync of the last 30 days).
  Scope: threads linked to applications (`gmail_thread_id`), senders from applied-company and ATS domains
  (greenhouse.io, lever.co, ashbyhq.com, myworkday*, smartrecruiters, hackerrank, codesignal…), and job-alert senders.
- Classification (`inbox.classify`, role `classifier`) + deterministic rule guards → labels: interview_invite,
  assessment, info_request, rejection, auto_ack, offer, scam, legal, job_alert, other. Gold: `emails_synthetic.jsonl`
  (interview+offer recall ≥ 0.95; lock precision/recall asserted in tests).
- `notify_only_lock` on the thread when rules OR classifier detect: interview/scheduling (Calendly, time slots,
  "availability", call/chat/meet/Zoom/round), assessment (HackerRank, CodeSignal, take-home, test), offer/CTC/salary/
  stipend expectations, money/fees/bank, legal (NDA, contract, agreement, background verification), joining/visa
  documents. Lock ⇒ big UI alert + macOS notification (`osascript display notification`; terminal-notifier if
  installed) + needs_prerit (interview|assessment|offer|legal|money) + NO outbound on that thread ever (until Prerit
  unlocks in the UI; unlock is audited).
- Info requests: auto-reply only if rules AND classifier agree it is a pure info request, confidence ≥ 0.9, every
  requested item is in the allowed answer set (résumé re-send, GitHub/LinkedIn/repo links), all gates pass, no lock
  terms, and setting `auto_reply_enabled` (default **false** for the first 2 live weeks). Otherwise create a draft
  (local; Gmail draft once compose scope exists) + needs_prerit.
- Job alerts: parse LinkedIn/Internshala/Naukri alert bodies (no fetch of those sites) → opportunities with
  `automation=manual_lane`; `ats_resolve` searches the company's Greenhouse/Lever/Ashby board for the same role →
  compliant channel when found.

## 3. Sending (LIVE only after go-live; SELF_TEST before)
- `apply/guard.py` + `gmail/sender.py`: deterministic RFC 5322 `Message-ID` per outbound intent; on crash recovery
  search Sent for `rfc822msgid:<id>` before any resend; ambiguous → needs_prerit, never auto-retry.
- SELF_TEST: recipient must equal `sangwanprerit40@gmail.com` (hard equality), used to verify the send path.
- Caps: `email_daily_cap`, per-domain 1/14 days, ≤ 3 cold lab emails/day; outbound_log rows.

## 4. Follow-ups
Scheduled 10 days after an email application with no inbound message on the thread; exactly one per application
(UNIQUE constraint); fully gated (fact + quality + caps + locks); never on locked threads; ATS applications get none
unless a recruiter email is known from the thread. Tested with a simulated clock.

## 5. Go-live checklist (Settings › Autonomy & Mode, loopback-only)
Gmail healthy (readonly) · required profile fields confirmed · ≥ 5 dry-run applications reviewed by Prerit ·
golden fact-gate tests green · caps set · Claude available or sign-off policy acknowledged · then: send-scope
consent → `.env` `HQ_FORCE_DRY_RUN=0` + `HQ_MODE=live` (written by the loopback route) → restart → typed "GO LIVE"
confirmation → mode LIVE. Recommended default after go-live: `autonomy=approve_first` for the first 10 applications.

## 6. UI
Inbox page (threads, tags, lock icons, interview/offer banners + one-time modal, drafts with approve/send), Settings ›
Gmail wizard, go-live checklist with live status per item, notifications center (bell) in the header.
