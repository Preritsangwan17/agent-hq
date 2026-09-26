"""AI usage for the Usage page: Grok spend, the subscription CLIs' usage windows, how much HQ kept local, and what's
left.

Exact vs estimated, always labelled:
- per-call cost is "reported" when xAI returned it with the response (usage.cost_in_usd_ticks), otherwise
  "estimated" from config/cloud_prices.yaml;
- HQ's own daily budget and call cap are exact (HQ enforces them);
- xAI's API does not expose the account's credit balance to an inference key, so "remaining credit" is an
  ESTIMATE: the balance Prerit typed in (from console.x.ai) minus what HQ has spent since. Other apps using the same
  key are invisible to HQ;
- Claude CLI / Codex CLI (subscriptions): HQ's own calls in the rolling 5-hour and 7-day windows and HQ's share
  cap are exact; the plan's own remaining allowance is shown only when the CLI reported it ("reported by …"),
  otherwise it is unknown — HQ never guesses a plan's limits.
"""
from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any

from hq.llm import cloud, policy
from hq.llm.cloud import PROVIDERS, SUBSCRIPTIONS
from hq.llm.xai import key_fingerprint, price_for
from hq.util.timeutil import now_iso, to_iso, today_ist, utcnow
from hq.worker import budget as budget_mod

REAL = "subtype NOT IN ('reserved','released') AND COALESCE(provider,'xai')='xai'"
ANY = "subtype NOT IN ('reserved','released')"


def _agg(conn: sqlite3.Connection, where: str, params: tuple = ()) -> dict[str, Any]:
    r = conn.execute(
        f"SELECT COALESCE(SUM(cost_usd_est),0) AS spent, COUNT(*) AS calls, COALESCE(SUM(input_tokens),0) AS tin, "
        f"COALESCE(SUM(output_tokens),0) AS tout, "
        f"COALESCE(SUM(CASE WHEN cost_source='reported' THEN cost_usd_est END),0) AS reported "
        f"FROM cloud_usage WHERE {REAL} AND {where}", params).fetchone()
    spent = float(r["spent"])
    return {"spent_usd": round(spent, 6), "calls": int(r["calls"]), "input_tokens": int(r["tin"]),
            "output_tokens": int(r["tout"]),
            "reported_share": round(float(r["reported"]) / spent, 3) if spent else None}


def grok_usage(conn: sqlite3.Connection, s: dict[str, Any], *, days: int = 30) -> dict[str, Any]:
    today = today_ist()
    since_day = (today - timedelta(days=days - 1)).isoformat()
    month = today.strftime("%Y-%m")
    since_iso = to_iso(utcnow() - timedelta(days=days))
    state = s.get("cloud_state") or {}

    today_agg = _agg(conn, "date_local=?", (today.isoformat(),))
    daily_budget = float(s.get("cloud_daily_budget_usd", 2.0))
    cap = int(s.get("cloud_daily_call_cap", 40))
    b = budget_mod.usage_today(conn)

    credit = None
    if s.get("grok_credit_usd") is not None and s.get("grok_credit_at"):
        spent_since = float(conn.execute(
            f"SELECT COALESCE(SUM(cost_usd_est),0) FROM cloud_usage WHERE {REAL} AND created_at >= ?",
            (s["grok_credit_at"],)).fetchone()[0])
        entered = float(s["grok_credit_usd"])
        credit = {"entered_usd": entered, "entered_at": s["grok_credit_at"], "spent_since_usd": round(spent_since, 6),
                  "estimated_remaining_usd": round(max(0.0, entered - spent_since), 4), "is_estimate": True,
                  "note": "Estimate: the balance you entered minus what HQ spent since. xAI's API doesn't report "
                          "the account balance to HQ, and other apps using the same key aren't counted. Check "
                          "console.x.ai for the exact figure."}

    daily = {r["d"]: {"date": r["d"], "spent_usd": round(float(r["s"]), 6), "calls": int(r["n"])} for r in conn.execute(
        f"SELECT date_local AS d, COALESCE(SUM(cost_usd_est),0) AS s, COUNT(*) AS n FROM cloud_usage "
        f"WHERE {REAL} AND date_local >= ? GROUP BY date_local", (since_day,))}
    series = []
    for i in range(days):
        d = (today - timedelta(days=days - 1 - i)).isoformat()
        series.append(daily.get(d, {"date": d, "spent_usd": 0.0, "calls": 0}))

    by_model = [{"model": r["model"] or "unknown", "calls": int(r["n"]), "spent_usd": round(float(r["s"]), 6),
                 "input_tokens": int(r["tin"] or 0), "output_tokens": int(r["tout"] or 0)} for r in conn.execute(
        f"SELECT model, COUNT(*) AS n, COALESCE(SUM(cost_usd_est),0) AS s, SUM(input_tokens) AS tin, "
        f"SUM(output_tokens) AS tout FROM cloud_usage WHERE {REAL} AND date_local >= ? GROUP BY model "
        f"ORDER BY s DESC", (since_day,))]
    by_task = [{"task_type": r["task_type"] or "other", "calls": int(r["n"]), "spent_usd": round(float(r["s"]), 6)}
               for r in conn.execute(
        f"SELECT task_type, COUNT(*) AS n, COALESCE(SUM(cost_usd_est),0) AS s FROM cloud_usage WHERE {REAL} "
        f"AND date_local >= ? GROUP BY task_type ORDER BY s DESC", (since_day,))]
    sources = {r["src"]: int(r["n"]) for r in conn.execute(
        f"SELECT COALESCE(cost_source,'estimated') AS src, COUNT(*) AS n FROM cloud_usage WHERE {REAL} "
        f"GROUP BY src")}
    recent = [{"at": r["created_at"], "task_type": r["task_type"], "model": r["model"],
               "cost_usd": r["cost_usd_est"], "cost_source": r["cost_source"] or "estimated",
               "input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"], "result": r["subtype"]}
              for r in conn.execute(f"SELECT * FROM cloud_usage WHERE {REAL} ORDER BY created_at DESC LIMIT 25")]

    # how much stayed on the Mac: individual local model calls made by the router vs cloud calls
    loc = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(prompt_tokens),0) AS tin, COALESCE(SUM(completion_tokens),0) AS tout "
        "FROM agent_runs WHERE adapter='openai_compatible' AND status='succeeded' AND started_at >= ?",
        (since_iso,)).fetchone()
    cloud_n = conn.execute(f"SELECT COUNT(*) FROM cloud_usage WHERE {ANY} AND date_local >= ?", (since_day,)).fetchone()[0]
    grok_n = sum(d["calls"] for d in series)
    local_n = int(loc["n"])
    pin, pout = price_for((s.get("xai_model") or cloud.XAI_DEFAULT))
    saved = (int(loc["tin"]) * pin + int(loc["tout"]) * pout) / 1e6

    return {
        "generated_at": now_iso(),
        "policy": policy.describe(s),
        "key": {"present": key_fingerprint() is not None, "fingerprint": key_fingerprint(),
                "available": ((state.get("providers") or {}).get("xai") or {}).get("available",
                                                                                   state.get("available")),
                "reason": state.get("reason"),
                "checked_at": state.get("checked_at"), "info": state.get("key_info") or {},
                "info_source": "GET https://api.x.ai/v1/api-key (does not include a balance)"},
        "today": today_agg,
        "budget": {"daily_usd": daily_budget, "call_cap": cap, "spent_today_usd": b["spent_usd"],
                   "reserved_usd": b["reserved_usd"], "calls_today": b["calls"],
                   "remaining_today_usd": round(max(0.0, daily_budget - b["spent_usd"] - b["reserved_usd"]), 4),
                   "calls_left_today": max(0, cap - b["calls"]), "resets_at": to_iso(budget_mod.next_midnight_ist()),
                   "is_estimate": False,
                   "note": "Exact: HQ's own daily limit for Grok. Over it, Grok work waits until midnight IST."},
        "month": {**_agg(conn, "substr(date_local,1,7)=?", (month,)), "month": month},
        "last_days": {**_agg(conn, "date_local >= ?", (since_day,)), "days": days},
        "all_time": _agg(conn, "1=1"),
        "credit": credit,
        "daily": series,
        "by_model": by_model,
        "by_task": by_task,
        "cost_sources": {"reported": sources.get("reported", 0), "estimated": sources.get("estimated", 0)},
        "rate_limits": {"headers": state.get("rate_limits") or {}, "at": state.get("rate_limits_at"),
                        "note": "Copied from the x-ratelimit-* headers of xAI's last response, when it sends them."},
        "local": {"calls": local_n, "input_tokens": int(loc["tin"]), "output_tokens": int(loc["tout"]),
                  "grok_calls": grok_n, "cloud_calls": int(cloud_n),
                  "local_share": round(local_n / (local_n + cloud_n), 3) if (local_n + cloud_n) else None,
                  "est_saved_usd": round(saved, 4),
                  "saved_note": f"Estimate: what the same local tokens would have cost on "
                                f"{s.get('xai_model') or cloud.XAI_DEFAULT} (config/cloud_prices.yaml)."},
        "recent": recent,
        "providers": providers_usage(conn, s, state),
    }


def providers_usage(conn: sqlite3.Connection, s: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per cloud provider: switch, reachability, HQ's own usage in the 5-hour / 7-day windows (exact) and
    any limits the CLI itself reported."""
    now = utcnow()
    pstates = state.get("providers") or {}
    on = cloud.enabled_providers(s)
    out = []
    for p in cloud.order(s):
        meta = PROVIDERS[p]
        st = pstates.get(p) or {}

        def since(hours: int) -> dict[str, Any]:
            r = conn.execute(
                f"SELECT COUNT(*) AS n, COALESCE(SUM(input_tokens),0) AS tin, COALESCE(SUM(output_tokens),0) AS tout, "
                f"COALESCE(SUM(cost_usd_est),0) AS spent, COALESCE(SUM(notional_usd),0) AS notional FROM cloud_usage "
                f"WHERE {ANY} AND COALESCE(provider,'xai')=? AND created_at >= ?",
                (p, to_iso(now - timedelta(hours=hours)))).fetchone()
            return {"calls": int(r["n"]), "tokens": int(r["tin"]) + int(r["tout"]), "spent_usd": round(float(r["spent"]), 6),
                    "notional_usd": round(float(r["notional"]), 4)}

        row: dict[str, Any] = {
            "provider": p, "label": meta["label"], "kind": meta["kind"], "switched_on": cloud.switched_on(s, p),
            "in_use": p in on, "available": st.get("available"), "installed": st.get("installed", p == "xai"),
            "reason": st.get("reason"), "fast_model": cloud.models_for(s, p)[0],
            "strong_model": cloud.models_for(s, p)[1], "last_5h": since(5), "last_7d": since(24 * 7),
        }
        if p in SUBSCRIPTIONS:
            cap = cloud.window_cap(s, p)
            used = row["last_5h"]["calls"]
            limits = st.get("limits") or {}
            row["hq_window"] = {"cap": cap, "used": used, "left": max(0, cap - used), "is_estimate": False,
                                "note": f"Exact: HQ's own cap of {cap} calls per rolling 5 hours on this plan, "
                                        "so the rest of the plan stays yours."}
            row["reported"] = {"windows": limits.get("windows") or [], "at": limits.get("windows_at"),
                               "source": limits.get("source"), "limited_until": limits.get("limited_until"),
                               "limit_message": limits.get("limit_message"), "limit_at": limits.get("limit_at"),
                               "note": "What the CLI itself reported. When it reports nothing, the plan's remaining "
                                       "allowance is unknown to HQ — check it in the app (Claude: /usage, "
                                       "Codex: /status)."}
        out.append(row)
    return out
