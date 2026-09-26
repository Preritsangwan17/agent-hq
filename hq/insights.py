"""Pipeline aggregates for the Analytics page and the Strategist's daily review (CONTRACT_E §1–§2).

Read-only and pure SQL + Python over the local database; nothing here touches the network. Opportunities are scoped
to real (`is_simulated=0`), simulated or all. Legacy items (stage frozen/skipped) are history, not pipeline: they are
counted separately and never enter the funnel or rates. Every rate carries its `n` so small samples read as such.
"""
from __future__ import annotations

import sqlite3
import statistics
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from hq.db.seed import get_settings
from hq.util.timeutil import parse_iso, today_ist, utcnow

SCOPES = ("all", "real", "sim")
FUNNEL = ["found", "verified", "drafted", "checked", "applied", "replied", "interview", "offer"]
# the furthest funnel step each stage has passed through
REACHED = {"found": 0, "filtered": 0, "verified": 1, "drafted": 2, "checked": 3, "applied": 4, "replied": 5,
           "rejected": 5, "interview": 6, "offer": 7}
HISTORY = ("frozen", "skipped")
APPLIED = {"applied", "replied", "rejected", "interview", "offer"}
REPLIED = {"replied", "rejected", "interview", "offer"}
PAY_BUCKETS = [(0, 10_000, "< ₹10K"), (10_000, 20_000, "₹10–20K"), (20_000, 30_000, "₹20–30K"),
               (30_000, 50_000, "₹30–50K"), (50_000, 100_000, "₹50K–1L"), (100_000, None, "₹1L+")]
SOURCE_KIND_LABEL = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "feed": "Remote feed",
                     "program_page": "Programme page", "manual": "Pasted link", "legacy": "Legacy shortlist",
                     "sim": "Simulator"}


def _scope_sql(scope: str) -> str:
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {', '.join(SCOPES)}")
    return {"all": "1=1", "real": "o.is_simulated=0", "sim": "o.is_simulated=1"}[scope]


def ist_date(iso: str | None) -> date | None:
    dt = parse_iso(iso)
    if dt is None:
        return None
    return (dt + timedelta(hours=5, minutes=30)).date()


def _opps(conn: sqlite3.Connection, scope: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT o.id, o.is_simulated, o.company_name, o.title, o.kind, o.role_type, o.country_iso2, o.city, o.stage, "
        "o.stage_reason, o.pay_status, o.pay_monthly_inr_mid, o.pay_ratio, o.fit_score, o.first_seen_at, "
        "o.source_label, (SELECT os.source_id FROM opportunity_sources os WHERE os.opportunity_id=o.id "
        "ORDER BY os.first_seen LIMIT 1) AS source_id FROM opportunities o WHERE " + _scope_sql(scope))
    return [dict(r) for r in rows]


def source_key(o: dict[str, Any]) -> str:
    if o.get("source_id"):
        return o["source_id"]
    return "sim" if o.get("is_simulated") else "manual"


def source_names(conn: sqlite3.Connection) -> dict[str, str]:
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM sources")}
    names.update({"legacy": "Legacy shortlist", "sim": "Simulator (SIM roles)", "manual": "Pasted by Prerit"})
    return names


REASON_PATTERNS = (  # first match wins; covers the verifier's and the simulator's wording
    ("ineligible", ("ineligible", "not eligible")),
    ("mill", ("mill",)),
    ("scam", ("scam", "charges a fee", "asks the applicant to pay", "fee")),
    ("unreadable", ("unreadable", "login wall")),
    ("expired", ("expired", "posting closed", "closed", "deadline")),
    ("availability", ("dates don't fit", "availability", "hours")),
    ("unpaid", ("unpaid",)),
    ("pay", ("pay ", "pay not", "stipend", "living cost")),
    ("low_fit", ("fit ",)),
    ("location", ("location", "remote only", "visa")),
    ("duplicate", ("duplicate",)),
)


def filter_reason(stage_reason: str | None) -> str:
    """'Ineligible: Only 7th/8th semester…' → 'ineligible', 'Pay ₹9,000/mo is 0.6× living cost' → 'pay'."""
    text = (stage_reason or "").strip().lower()
    if not text:
        return "other"
    for category, needles in REASON_PATTERNS:
        if any(text.startswith(n) or f" {n}" in f" {text}" for n in needles):
            return category
    return "other"


def funnel(opps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = [0] * len(FUNNEL)
    for o in opps:
        reached = REACHED.get(o["stage"])
        if reached is None:
            continue
        for i in range(reached + 1):
            counts[i] += 1
    return [{"stage": s, "n": counts[i]} for i, s in enumerate(FUNNEL)]


def _rate_rows(groups: dict[str, list[dict[str, Any]]], label_of=lambda k: k) -> list[dict[str, Any]]:
    out = []
    for key, items in groups.items():
        applied = [o for o in items if o["stage"] in APPLIED]
        if not applied:
            continue
        replied = sum(o["stage"] in REPLIED for o in applied)
        out.append({"key": key, "label": label_of(key), "applied": len(applied), "replied": replied,
                    "interviews": sum(o["stage"] in ("interview", "offer") for o in applied),
                    "rate": round(replied / len(applied), 3)})
    return sorted(out, key=lambda r: (-r["applied"], r["label"]))


def reply_rates(opps: list[dict[str, Any]], names: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    live = [o for o in opps if o["stage"] not in HISTORY]
    by: dict[str, dict[str, list[dict[str, Any]]]] = {"source": defaultdict(list), "country": defaultdict(list),
                                                      "role": defaultdict(list), "kind": defaultdict(list)}
    for o in live:
        by["source"][source_key(o)].append(o)
        by["country"][o["country_iso2"] or "—"].append(o)
        by["role"][o["role_type"] or "other"].append(o)
        by["kind"][o["kind"] or "other"].append(o)
    return {"source": _rate_rows(by["source"], lambda k: names.get(k, k)), "country": _rate_rows(by["country"]),
            "role": _rate_rows(by["role"]), "kind": _rate_rows(by["kind"])}


def source_yield(conn: sqlite3.Connection, opps: list[dict[str, Any]], names: dict[str, str]) -> list[dict[str, Any]]:
    health = {r["id"]: dict(r) for r in conn.execute(
        "SELECT id, kind, enabled, consecutive_errors, disabled_until, last_polled_at, last_ok_at FROM sources")}
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for o in opps:
        if o["stage"] not in HISTORY:
            groups[source_key(o)].append(o)
    rows = []
    for key, items in groups.items():
        h = health.get(key, {})
        kind = h.get("kind") or ("sim" if key == "sim" else "manual" if key == "manual" else key.split(":", 1)[0])
        rows.append({
            "source_id": key, "name": names.get(key, key), "kind": SOURCE_KIND_LABEL.get(kind, kind),
            "found": len(items), "filtered": sum(o["stage"] == "filtered" for o in items),
            "verified": sum(REACHED.get(o["stage"], -1) >= 1 for o in items),
            "applied": sum(o["stage"] in APPLIED for o in items),
            "replies": sum(o["stage"] in REPLIED for o in items),
            "interviews": sum(o["stage"] in ("interview", "offer") for o in items),
            "median_pay_inr": _median([o["pay_monthly_inr_mid"] for o in items]),
            "enabled": bool(h["enabled"]) if h else None, "errors": h.get("consecutive_errors", 0) if h else 0,
            "last_ok_at": h.get("last_ok_at") if h else None})
    return sorted(rows, key=lambda r: (-r["applied"], -r["verified"], -r["found"], r["name"]))


def gate_failures(conn: sqlite3.Connection, opps: list[dict[str, Any]], scope: str) -> dict[str, list[dict[str, Any]]]:
    reasons: dict[str, int] = defaultdict(int)
    for o in opps:
        if o["stage"] == "filtered":
            reasons[filter_reason(o["stage_reason"])] += 1
    gates: dict[tuple[str, str], int] = defaultdict(int)
    for r in conn.execute(
            "SELECT g.gate, json_extract(g.details_json, '$.rule') AS rule FROM gate_results g "
            "JOIN applications a ON a.id=g.application_id JOIN opportunities o ON o.id=a.opportunity_id "
            "WHERE g.passed=0 AND " + _scope_sql(scope)):
        gates[(r["gate"], r["rule"] or "")] += 1
    return {"filtered": [{"reason": k, "n": v} for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])],
            "drafts": [{"gate": g, "rule": rule or None, "n": n}
                       for (g, rule), n in sorted(gates.items(), key=lambda kv: -kv[1])]}


def applications_per_day(conn: sqlite3.Connection, scope: str, days: int) -> list[dict[str, Any]]:
    today = today_ist()
    start = today - timedelta(days=days - 1)
    per: dict[date, dict[str, int]] = {start + timedelta(days=i): defaultdict(int) for i in range(days)}
    for r in conn.execute(
            "SELECT a.submitted_at, a.mode FROM applications a JOIN opportunities o ON o.id=a.opportunity_id "
            "WHERE a.submitted_at IS NOT NULL AND " + _scope_sql(scope)):
        d = ist_date(r["submitted_at"])
        if d in per:
            per[d][r["mode"] or "dry_run"] += 1
    return [{"date": d.isoformat(), "dry_run": v.get("dry_run", 0), "self_test": v.get("self_test", 0),
             "live": v.get("live", 0), "total": sum(v.values())} for d, v in sorted(per.items())]


def found_per_day(opps: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    today = today_ist()
    start = today - timedelta(days=days - 1)
    per = {start + timedelta(days=i): 0 for i in range(days)}
    for o in opps:
        if o["stage"] in HISTORY:
            continue
        d = ist_date(o["first_seen_at"])
        if d in per:
            per[d] += 1
    return [{"date": d.isoformat(), "found": n} for d, n in sorted(per.items())]


def cloud_spend(conn: sqlite3.Connection, days: int) -> dict[str, Any]:
    s = get_settings(conn)
    today = today_ist()
    start = today - timedelta(days=days - 1)
    per = {(start + timedelta(days=i)).isoformat(): {"usd": 0.0, "calls": 0} for i in range(days)}
    for r in conn.execute("SELECT date_local, SUM(COALESCE(cost_usd_est, 0)) AS usd, COUNT(*) AS calls "
                          "FROM claude_usage WHERE date_local >= ? GROUP BY date_local", (start.isoformat(),)):
        if r["date_local"] in per:
            per[r["date_local"]] = {"usd": round(r["usd"] or 0.0, 4), "calls": r["calls"]}
    return {"cap_usd": float(s.get("claude_daily_budget_usd", 5.0)), "call_cap": int(s.get("claude_daily_call_cap", 40)),
            "days": [{"date": d, **v} for d, v in per.items()]}


def tokens_by_model(conn: sqlite3.Connection, days: int) -> list[dict[str, Any]]:
    since = (utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = conn.execute(
        "SELECT model_id, COUNT(*) AS runs, SUM(COALESCE(prompt_tokens,0)) AS prompt, "
        "SUM(COALESCE(completion_tokens,0)) AS completion, AVG(tok_s) AS tok_s FROM agent_runs "
        "WHERE model_id IS NOT NULL AND started_at >= ? GROUP BY model_id", (since,))
    out = []
    for r in rows:
        mid = r["model_id"]
        total = (r["prompt"] or 0) + (r["completion"] or 0)
        if not total:
            continue
        out.append({"model_id": mid, "label": mid.split(":", 1)[-1].split("/")[-1],
                    "cloud": mid.startswith(("claude:", "xai:")), "simulated": mid.startswith("sim:"),
                    "runs": r["runs"], "prompt_tokens": r["prompt"] or 0, "completion_tokens": r["completion"] or 0,
                    "total_tokens": total, "avg_tok_s": round(r["tok_s"], 1) if r["tok_s"] else None})
    return sorted(out, key=lambda x: -x["total_tokens"])


def _median(values: list[Any]) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return round(statistics.median(vals)) if vals else None


def pay_histogram(opps: list[dict[str, Any]]) -> dict[str, Any]:
    live = [o for o in opps if o["stage"] not in HISTORY and o["stage"] != "filtered"]
    buckets = [{"label": lab, "min": lo, "max": hi, "n": 0} for lo, hi, lab in PAY_BUCKETS]
    unknown = 0
    for o in live:
        v = o["pay_monthly_inr_mid"]
        if v is None:
            unknown += 1
            continue
        for b in buckets:
            if v >= b["min"] and (b["max"] is None or v < b["max"]):
                b["n"] += 1
                break
    return {"buckets": buckets, "unknown": unknown, "median": _median([o["pay_monthly_inr_mid"] for o in live]),
            "max": max((o["pay_monthly_inr_mid"] for o in live if o["pay_monthly_inr_mid"] is not None), default=None)}


def pay_by_country(opps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for o in opps:
        if o["stage"] not in HISTORY and o["stage"] != "filtered" and o["pay_monthly_inr_mid"] is not None:
            groups[o["country_iso2"] or "—"].append(o)
    rows = [{"country": c, "n": len(items), "median_inr": _median([o["pay_monthly_inr_mid"] for o in items]),
             "max_inr": round(max(o["pay_monthly_inr_mid"] for o in items)),
             "median_ratio": (round(statistics.median(r), 2) if (r := [o["pay_ratio"] for o in items
                                                                     if o["pay_ratio"] is not None]) else None)}
            for c, items in groups.items()]
    return sorted(rows, key=lambda r: (-(r["median_inr"] or 0), r["country"]))


def analytics(conn: sqlite3.Connection, *, scope: str = "all", days: int = 30) -> dict[str, Any]:
    days = max(7, min(int(days), 180))
    opps = _opps(conn, scope)
    names = source_names(conn)
    live = [o for o in opps if o["stage"] not in HISTORY]
    applied = [o for o in live if o["stage"] in APPLIED]
    replied = sum(o["stage"] in REPLIED for o in applied)
    return {
        "scope": scope, "days": days,
        "totals": {"opportunities": len(live), "history": len(opps) - len(live),
                   "filtered": sum(o["stage"] == "filtered" for o in live), "applied": len(applied),
                   "replied": replied, "reply_rate": round(replied / len(applied), 3) if applied else None,
                   "interviews": sum(o["stage"] in ("interview", "offer") for o in live),
                   "offers": sum(o["stage"] == "offer" for o in live),
                   "simulated": sum(bool(o["is_simulated"]) for o in live)},
        "funnel": funnel(live),
        "applications_per_day": applications_per_day(conn, scope, days),
        "found_per_day": found_per_day(opps, days),
        "reply_rates": reply_rates(opps, names),
        "sources": source_yield(conn, opps, names),
        "gate_failures": gate_failures(conn, opps, scope),
        "cloud_spend": cloud_spend(conn, days),
        "tokens_by_model": tokens_by_model(conn, days),
        "pay_histogram": pay_histogram(opps),
        "pay_by_country": pay_by_country(opps),
    }
