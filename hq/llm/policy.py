"""Deterministic, explainable routing. A valid local result wins before any cloud call."""
from typing import Any

from hq.llm import modes
from hq.llm.providers import CLOUD, REGISTRY
from hq.models import roles


def task_kind(task: str) -> str:
    task = task.lower()
    for kind, words in {
        "coding": ("coding", "debug", "code", "automation"),
        "writing": ("polish", "resume", "write", "draft"),
        "review": ("factcheck", "fact_checker", "signoff", "review"),
        "planning": ("plan", "strategy"),
        "external_reasoning": ("external_reasoning", "grok"),
    }.items():
        if any(word in task for word in words):
            return kind
    return "routine"


def cloud_order(s: dict[str, Any], task: str = "") -> list[str]:
    kind = task_kind(task)
    base = [p for p in CLOUD if kind in REGISTRY[p].strengths]
    base += [p for p in CLOUD if p not in base]
    preferred = s.get("cloud_llm", "auto")
    if preferred in base:
        base = [preferred] + [p for p in base if p != preferred]
    return [p for p in base if modes.enabled(s, p)]


def local_quality(conn, role: str, model_id: str) -> tuple[bool | None, str]:
    benches = roles.latest_benchmarks(conn).get(model_id, {})
    relevant = [benches[t] for t in roles.ROLE_TASKS.get(role, ()) if t in benches]
    if not relevant:
        return None, "No benchmark evidence yet; try Local AI and validate its output."
    floor_ok, reason = roles.meets_floor(role, benches)
    quality = sum(roles.quality(role, b) for b in relevant) / len(relevant)
    ok = floor_ok and quality >= 0.8
    return ok, (f"Local benchmark quality {quality:.0%}; " +
                ("meets the quality floor." if ok else reason or "below the 80% quality floor."))


def cloud_reason(task: str, provider: str, fallback: bool = False) -> str:
    kind = task_kind(task)
    fit = kind in REGISTRY[provider].strengths
    return ("Fallback after an earlier attempt failed. " if fallback else "") + (
        f"{REGISTRY[provider].label} assists with {kind} after local work; " +
        ("matches the task's capability needs." if fit else "available within the allowed provider set."))


def recommendation(s: dict[str, Any]) -> dict[str, str]:
    states = (s.get("claude_state") or {}).get("providers") or {}
    available = [p for p in cloud_order(s) if states.get(p, {}).get("available") and
                 not states.get(p, {}).get("resting")]
    selected = available[:1]
    mode = modes.mode_for(selected)
    return {"mode": mode, "label": modes.MODES[mode]["label"], "reason":
            ("Prefer local models for routine work. " + REGISTRY[selected[0]].label +
             " is available to assist when local output fails quality checks.") if selected else
            "Keep work local. No enabled external provider is currently confirmed available; local quality is checked per task."}


def plan(conn, s: dict[str, Any], workflow: str = "job_search") -> list[dict[str, Any]]:
    workflows = {
        "job_search": [("Filter and rank opportunities", "title_filter", "filter", False),
                       ("Analyze resume and role", "summarizer", "resume.analysis", False),
                       ("Improve application", "writer", "polish.final", True),
                       ("Independent fact check", "fact_checker", "review", False),
                       ("Final filtering and storage", "parser", "store", False)],
        "coding": [("Analyze requirements", "summarizer", "planning", False),
                   ("Propose code and debugging changes", "writer", "coding", True),
                   ("Review output", "fact_checker", "review", False)],
    }
    result = []
    for title, role, task, allow_cloud in workflows[workflow]:
        assigned = roles.ranked(conn, role)
        quality, reason = local_quality(conn, role, assigned[0]) if assigned else (
            None, "No local model assigned; configure one in Models.")
        result.append({"title": title, "role": role, "task_type": task, "local_model": assigned[0] if assigned else None,
                       "local_quality_sufficient": quality, "reason": reason,
                       "fallback_providers": cloud_order(s, task) if allow_cloud else [],
                       "execution": "local first", "estimated_api_cost_usd": 0,
                       "cloud_cost_note": "A fallback reserves the configured task estimate before calling."})
    return result

