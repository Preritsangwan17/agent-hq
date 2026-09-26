"""Text generators for the simulation: agent "now" lines, simulated letters, mock replies and reports.

Letters only use facts from Prerit's verified fact sheet (IDs referenced inline for the fact-check animation) and
are prefixed with a SIMULATED banner; nothing here is ever sent anywhere."""
from __future__ import annotations

import random
from typing import Any

from hq.sim.pool import CITIES, SimRole

FACTS = {
    "F-EDU": "second-year B.Tech CSE (AI/ML) student at Bennett University",
    "F-BOOK-KNN": "built a KNN-based book recommender",
    "F-BOOK-FILTER": "kept only users with more than 200 ratings",
    "F-BOOK-PIPELINE": "organised the book project as a YAML-configured pipeline with a Streamlit demo",
    "F-CHURN-RF": "trained a RandomForest churn classifier on one-hot encoded features including tenure",
}

BOARD_LINES = {
    "greenhouse": ["Polling Greenhouse board for {company}…", "Listing {n_open} open roles on {company}'s Greenhouse board…"],
    "lever": ["Polling Lever postings for {company}…", "Listing {n_open} open roles on {company}'s Lever board…"],
    "ashby": ["Querying Ashby job board for {company}…", "Listing {n_open} open roles on {company}'s Ashby board…"],
    "careers": ["Reading {company} careers page…", "Scanning {company} careers page for new postings…"],
    "program_page": ["Reading {company} program page…", "Parsing {company} program table: {n_rows} rows…"],
    "lab_page": ["Reading {company} openings page…", "Checking {company} lab news for intern calls…"],
}


def fmt_inr(v: float | None) -> str:
    if v is None:
        return "?"
    v = int(round(v))
    s = str(v)
    if len(s) <= 3:
        return f"₹{s}"
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return "₹" + ",".join(parts) + "," + tail


def discover_lines(rng: random.Random, roles: list[SimRole], total_known: int) -> list[str]:
    first = roles[0] if roles else None
    lines = []
    if first:
        tpl = rng.choice(BOARD_LINES[first.board])
        lines.append(tpl.format(company=first.company, n_open=rng.randint(9, 64), n_rows=rng.randint(6, 18)))
    lines.append(f"Filtering titles: kept {len(roles)} of {rng.randint(18, 70)} "
                 "(intern|werkstudent|junior|fellow|research)…")
    lines.append(f"Dedupe: fuzzy match against {total_known} known roles — no duplicates")
    for r in roles:
        lines.append(f"New posting: {r.title} — {r.company} ({CITIES[r.city].name})")
    return lines


def parse_lines(rng: random.Random, role: SimRole) -> list[str]:
    ch = {"email": f"email ({role.apply_email})", "ats_form": "ATS form", "portal": "program portal"}[role.channel]
    return [
        f"Parsing job description for {role.company} ({rng.randint(380, 1400)} words)…",
        "Extracting requirements, deadline, hours and pay…",
        f"Pay line: \"{role.pay.raw}\"",
        f"Apply channel: {ch}",
    ]


def link_lines(rng: random.Random, role: SimRole, url: str, deadline_note: str) -> list[str]:
    return [
        f"HEAD {url} → 200 in {rng.randint(90, 480)} ms",
        f"Checking the role is still listed on the {role.board_label.lower()}…",
        deadline_note,
    ]


def eligibility_lines(rng: random.Random, role: SimRole) -> list[str]:
    return [
        f"Checking eligibility: '{role.eligibility[1]}'…",
        "Rule engine: grad year 2028 · semester 3 · B.Tech CSE (AI/ML)…",
        f"Second-model cross-check (agreement {rng.uniform(0.86, 0.99):.2f})…",
    ]


def scam_lines(rng: random.Random, role: SimRole) -> list[str]:
    lines = ["Scanning for fee language, known mills, free-mail recruiters…",
             f"Recruiter domain {role.slug}.example vs company site…"]
    if role.scam_signal:
        lines.append(f"Signal: {role.scam_signal}")
    else:
        lines.append("No fee, mill or ID-harvesting signals")
    return lines


def pay_lines(role: SimRole, pay: dict[str, Any]) -> list[str]:
    city = CITIES[role.city]
    lines = [f"Normalising '{role.pay.raw}' → {role.pay.currency or '—'}/{role.pay.period}"]
    if pay.get("fx_rate") and role.pay.currency and role.pay.currency != "INR":
        lines.append(f"FX {role.pay.currency}→INR @ {pay['fx_rate']} (sim table)")
    lines.append(f"Living cost {city.name if role.work_mode != 'remote' else 'Greater Noida (remote)'}: "
                 f"{fmt_inr(pay.get('living_cost_monthly_inr'))}/mo (provisional)")
    if pay.get("pay_ratio") is not None:
        lines.append(f"Pay ratio {pay['pay_ratio']:.2f}× living cost")
    elif pay.get("pay_status") == "variable":
        lines.append("Hourly pay, hours not stated → pay marked variable (never assume 40 h)")
    return lines


def fit_lines(rng: random.Random, role: SimRole, score: int) -> list[str]:
    return [
        "Scoring fit: role relevance, skills overlap, eligibility, pay ratio…",
        f"Skills overlap vs facts: {rng.randint(11, 19)}/20 · relevance {rng.randint(16, 25)}/25",
        f"Fit {score}/100",
    ]


def draft_lines(rng: random.Random, role: SimRole, version: int, tok_s: float) -> list[str]:
    lines = ["Selecting facts: F-BOOK-KNN, F-BOOK-FILTER, F-CHURN-RF…",
             f"Citing job quote: '{role.job_quote[:70]}'"]
    if version > 1:
        lines.insert(0, f"Rewriting draft v{version} with fact-checker feedback…")
    lines += [f"Drafting paragraph {p}/4 for {role.company}…" for p in (2, 3)]
    lines.append(f"Streaming {rng.randint(240, 420)} tokens @ {tok_s:.0f} tok/s…")
    return lines


def factcheck_lines(rng: random.Random, capability: str, n_sent: int) -> list[str]:
    if capability == "factcheck.deterministic":
        return ["Rule pass: NUM_NOT_IN_FACTS, BANNED_CLAIM, WRONG_PROJECT…",
                f"Sentence {rng.randint(2, n_sent)}/{n_sent}: checking tech whitelist…",
                "Checking citations: every claim maps to a fact ID…"]
    if capability == "factcheck.sentence":
        fact = rng.choice(list(FACTS))
        k = rng.randint(2, n_sent - 1)
        return [f"Fact-checking sentence {k}/{n_sent} against {fact}…",
                f"Fact-checking sentence {k + 1}/{n_sent} against {rng.choice(list(FACTS))}…",
                f"Verdicts: {n_sent} supported, 0 partial, 0 unsupported"]
    return [f"Quality: names the organisation ✓ · job quote ✓ · clichés 0",
            f"Specificity rubric {rng.randint(3, 5)}/5 · Jaccard vs recent letters {rng.uniform(0.18, 0.45):.2f}",
            "Length, salutation and sign-off ✓"]


def signoff_lines(n_sent: int) -> list[str]:
    return [f"Claude sign-off: reviewing {n_sent} sentences with fact IDs…",
            "Cross-checking job quotes against the posting…",
            "Sign-off decision…"]


def resume_lines(role: SimRole) -> list[str]:
    emphasis = {"ml": "ML", "data": "data", "software": "software", "research": "research"}.get(role.role_type, "ML")
    return [f"Selecting approved bullets for {emphasis} emphasis…",
            "Rendering one-page PDF (sim, headless Chrome)…",
            "Checking PDF: 1 page · approved text only ✓"]


def apply_email_lines(role: SimRole) -> list[str]:
    return ["Pre-submit recheck: link, deadline, scam, pause, caps ✓",
            "Mode DRY RUN → mock mailbox only (no real email)",
            f"Mock-sent to {role.apply_email}"]


def manual_pack_lines(rng: random.Random, role: SimRole) -> list[str]:
    what = "ATS form" if role.channel == "ats_form" else "program portal"
    return [f"Building pre-filled pack for {role.company} {what}…",
            f"Mapping {rng.randint(8, 16)} form fields to the answer bank…",
            "Flagging fields that need Prerit (phone, availability)…",
            "Pack ready: about 2 minutes for Prerit"]


def letter_text(role: SimRole, version: int, bad_claim: bool = False) -> tuple[str, list[dict[str, Any]]]:
    """A short simulated letter plus per-sentence fact IDs. `bad_claim` inserts an unsupported sentence of the
    kind the old local drafts invented, so the fact gate has something real to catch."""
    sentences = [
        (f"Dear {role.company} team,", []),
        (f"I am Prerit Sangwan, a {FACTS['F-EDU']}, and I would like to apply for the {role.title} role.",
         ["F-EDU"]),
        (f"Your posting says {role.job_quote}, which is the kind of work I want to learn from.", ["JOB-Q1"]),
        (f"In my book-recommendation project I {FACTS['F-BOOK-KNN']} and {FACTS['F-BOOK-FILTER']}.",
         ["F-BOOK-KNN", "F-BOOK-FILTER"]),
        (f"I {FACTS['F-BOOK-PIPELINE']}.", ["F-BOOK-PIPELINE"]),
        *([("I deployed the recommender to production for real users.", ["F-BOOK-PIPELINE"])] if bad_claim else []),
        (f"In a separate project I {FACTS['F-CHURN-RF']}.", ["F-CHURN-RF"]),
        ("I have not yet worked on this exact problem, so I would bring careful habits rather than claims.", []),
        ("Thank you for considering my application.", []),
        ("Prerit Sangwan", []),
    ]
    body = "\n".join(s for s, _ in sentences)
    text = f"[SIMULATED DRAFT v{version} — never sent]\n\n{body}"
    return text, [{"idx": i, "text": s, "fact_ids": f} for i, (s, f) in enumerate(sentences)]


REPLY_SUBJECTS = {
    "interview": "Interview invitation — {title}",
    "rejection": "Update on your application — {title}",
    "offer": "Offer — {title}",
    "auto_ack": "We received your application",
    "info_request": "Quick question about your availability",
}

REPLY_SNIPPETS = {
    "interview": "Thanks for applying to {company}. We'd like to schedule a 30-minute call next week — could you "
                 "share a few slots?",
    "rejection": "Thank you for your interest in {company}. After careful review we won't be moving forward this "
                 "time.",
    "offer": "We're delighted to offer you the {title} position at {company}. Details are attached.",
    "auto_ack": "This is an automatic confirmation that {company} received your application.",
    "info_request": "Could you confirm your availability dates and weekly hours for the {title} role?",
}


def reply_for(classification: str, role: SimRole) -> tuple[str, str]:
    return (REPLY_SUBJECTS[classification].format(title=role.title),
            REPLY_SNIPPETS[classification].format(company=role.company, title=role.title))


def strategy_report(counts: dict[str, int], top: list[dict[str, Any]]) -> str:
    lines = ["# Daily review (simulated)", "",
             f"- Found {counts.get('found', 0)}, verified {counts.get('verified', 0)}, "
             f"applied {counts.get('applied', 0)}, filtered {counts.get('filtered', 0)}.",
             f"- Replies {counts.get('replies', 0)} · interviews {counts.get('interview', 0)} · "
             f"offers {counts.get('offer', 0)}.", "", "## Best-paying live items"]
    for o in top:
        lines.append(f"- {o['company_name']} — {o['title']}: {fmt_inr(o.get('pay_monthly_inr_mid'))}/mo")
    lines += ["", "## Proposals (need Prerit's OK)",
              "- Add two more Ashby boards for research-lab spinouts.",
              "- Lower the fit threshold for funded programs from 60 to 55."]
    return "\n".join(lines)
