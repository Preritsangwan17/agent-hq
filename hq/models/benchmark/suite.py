"""Run the benchmark tasks against local models and fill the leaderboard.

Each model is measured alone (other servers unloaded) at temperature 0. Per task: n, accuracy / precision /
recall / f1 as relevant, JSON validity on the first answer and after one repair turn, generation and prompt
speed, time to first token and peak phys_footprint. Details go to data/artifacts/bench/<model>/<task>.json,
rows to `benchmarks`; afterwards roles are re-assigned (fact-checker first).
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from hq import settings as paths
from hq.db import repo
from hq.db.conn import tx
from hq.db.seed import get_settings, set_settings
from hq.llm import client as llm_client
from hq.llm.json_utils import parse_and_validate, repair_message
from hq.llm.prompts import load_schema
from hq.models import roles
from hq.models.benchmark.tasks import BenchTask, all_tasks
from hq.models.manager import ModelManager
from hq.util.ids import new_id
from hq.util.timeutil import now_iso

SUITE_VERSION = "b1"
ChatFn = Callable[..., Awaitable[llm_client.ChatResult]]


@dataclass
class TaskRun:
    outputs: list[Any] = field(default_factory=list)
    first_valid: int = 0
    repaired_valid: int = 0
    tok_s: list[float] = field(default_factory=list)
    prompt_tok_s: list[float] = field(default_factory=list)
    ttft: list[float] = field(default_factory=list)
    tokens: int = 0


async def ask(chat_fn: ChatFn, base_url: str, served: str, messages: list[dict[str, str]], schema: dict[str, Any],
              max_tokens: int, run: TaskRun) -> Any:
    chat = await chat_fn(base_url, served, messages, max_tokens=max_tokens, temperature=0.0)
    _stats(chat, run)
    out, errors = parse_and_validate(chat.text, schema)
    if not errors:
        run.first_valid += 1
        run.repaired_valid += 1
        return out
    fix = messages + [{"role": "assistant", "content": chat.raw_text or chat.text},
                      {"role": "user", "content": repair_message(errors, schema)}]
    chat2 = await chat_fn(base_url, served, fix, max_tokens=max_tokens, temperature=0.0)
    _stats(chat2, run)
    out, errors = parse_and_validate(chat2.text, schema)
    if not errors:
        run.repaired_valid += 1
        return out
    return out if isinstance(out, dict) else None


def _stats(chat: llm_client.ChatResult, run: TaskRun) -> None:
    if chat.tok_s:
        run.tok_s.append(chat.tok_s)
    if chat.ttft_ms:
        run.ttft.append(chat.ttft_ms)
        if chat.prompt_tokens:
            run.prompt_tok_s.append(chat.prompt_tokens / (chat.ttft_ms / 1000))
    run.tokens += (chat.prompt_tokens or 0) + (chat.completion_tokens or 0)


def _avg(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 2) if xs else None


def _slug(model_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model_id)[:120]


def _set_state(conn: sqlite3.Connection, state: dict[str, Any]) -> None:
    with tx(conn):
        set_settings(conn, {"benchmark_state": state}, by="worker")


async def benchmark_model(conn: sqlite3.Connection, manager: ModelManager, model_id: str, tasks: list[BenchTask], *,
                          quick: bool, chat_fn: ChatFn = llm_client.chat,
                          progress: Callable[[str, float], None] | None = None) -> dict[str, dict[str, Any]]:
    for other in list(manager.servers):
        if other != model_id:
            await manager.unload(other, reason="benchmarking another model alone")
    results: dict[str, dict[str, Any]] = {}
    total_cases = sum(len(t.cases(quick)) for t in tasks)
    done = 0
    async with manager.use(model_id) as ep:
        for task in tasks:
            schema = load_schema(task.schema_name)
            cases = task.cases(quick)
            run = TaskRun()
            t0 = time.monotonic()
            for case in cases:
                try:
                    out = await ask(chat_fn, ep.base_url, ep.served_id, case.messages, schema, task.max_tokens, run)
                except llm_client.LLMError as exc:
                    out = None
                    run.outputs.append(None)
                    done += 1
                    if progress:
                        progress(task.name, done / total_cases)
                    if isinstance(exc, llm_client.LLMUnavailable):
                        raise
                    continue
                run.outputs.append(out)
                done += 1
                if progress:
                    progress(task.name, done / total_cases)
            metrics = task.score(cases, run.outputs)
            sv = manager.servers.get(model_id)
            if sv:
                manager._measure(sv)
            peak = sv.peak_gb if sv else None
            row = {"task": task.name, "n": metrics.n, "accuracy": metrics.accuracy, "precision": metrics.precision,
                   "recall": metrics.recall, "f1": metrics.f1,
                   "json_valid_first": round(run.first_valid / len(cases), 4) if cases else None,
                   "json_valid_after_repair": round(run.repaired_valid / len(cases), 4) if cases else None,
                   "tok_s_gen": _avg(run.tok_s), "tok_s_prompt": _avg(run.prompt_tok_s), "ttft_ms": _avg(run.ttft),
                   "peak_footprint_gb": peak, "duration_s": round(time.monotonic() - t0, 1), "tokens": run.tokens}
            out_dir = paths.ARTIFACTS / "bench" / _slug(model_id)
            out_dir.mkdir(parents=True, exist_ok=True)
            details_path = out_dir / f"{task.name}.json"
            details_path.write_text(json.dumps({**row, "quick": quick, "suite": SUITE_VERSION,
                                                "details": metrics.details, "outputs": run.outputs}, indent=1,
                                               default=str)[:5_000_000])
            with tx(conn):
                conn.execute(
                    "INSERT INTO benchmarks(id, model_id, suite_version, task, n, accuracy, precision, recall, f1, "
                    "json_valid_first, json_valid_after_repair, tok_s_gen, tok_s_prompt, ttft_ms, peak_footprint_gb, "
                    "details_path, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (new_id(), model_id, SUITE_VERSION + ("q" if quick else "f"), task.name, row["n"], row["accuracy"],
                     row["precision"], row["recall"], row["f1"], row["json_valid_first"],
                     row["json_valid_after_repair"], row["tok_s_gen"], row["tok_s_prompt"], row["ttft_ms"], peak,
                     str(details_path), now_iso()))
                repo.emit(conn, "benchmark.progress", f"{model_id} · {task.name}: accuracy {row['accuracy']}",
                          data={"model_id": model_id, "task": task.name, **{k: row[k] for k in (
                              "accuracy", "recall", "precision", "tok_s_gen", "json_valid_first")}})
            results[task.name] = row
    return results


def usable_model_ids(conn: sqlite3.Connection) -> list[str]:
    return [r["id"] for r in conn.execute(
        "SELECT id FROM models WHERE complete=1 AND runtime_supported=1 AND modality='chat' AND status!='broken' "
        "ORDER BY COALESCE(measured_ram_gb, est_ram_gb, 99)")]


async def run_suite(conn: sqlite3.Connection, manager: ModelManager, *, model_ids: list[str] | None = None,
                    task_names: list[str] | None = None, quick: bool = True,
                    chat_fn: ChatFn = llm_client.chat) -> dict[str, Any]:
    registry = all_tasks()
    tasks = [registry[t] for t in (task_names or list(registry))]
    models = model_ids or usable_model_ids(conn)
    with tx(conn):
        repo.emit(conn, "benchmark.started", f"Benchmark ({'quick' if quick else 'full'}) on {len(models)} model(s)",
                  data={"models": models, "tasks": [t.name for t in tasks], "quick": quick})
    summary: dict[str, Any] = {}
    t0 = time.monotonic()
    for i, mid in enumerate(models):
        def prog(task: str, frac: float, i: int = i, mid: str = mid) -> None:
            overall = (i + frac) / len(models)
            elapsed = time.monotonic() - t0
            _set_state(conn, {"running": True, "model_id": mid, "task": task, "progress": round(overall, 3),
                              "eta_s": round(elapsed / overall * (1 - overall)) if overall > 0.02 else None})
        prog(tasks[0].name if tasks else "", 0.0)
        try:
            summary[mid] = await benchmark_model(conn, manager, mid, tasks, quick=quick, chat_fn=chat_fn, progress=prog)
        except Exception as exc:  # one model failing must not stop the rest
            summary[mid] = {"error": f"{type(exc).__name__}: {exc}"}
            with tx(conn):
                repo.emit(conn, "benchmark.progress", f"{mid}: benchmark failed ({exc})", level="warn",
                          data={"model_id": mid, "error": str(exc)[:300]})
    _set_state(conn, {"running": False, "finished_at": now_iso()})
    pool = float(get_settings(conn).get("model_pool_budget_gb", 30))
    roles.assign(conn, pool)
    with tx(conn):
        repo.emit(conn, "benchmark.done", f"Benchmark done: {len(models)} model(s)", data={"summary": {
            m: {t: (r.get("accuracy") if isinstance(r, dict) else None) for t, r in (s.items() if isinstance(s, dict)
                and "error" not in s else [])} for m, s in summary.items()}})
    return summary
