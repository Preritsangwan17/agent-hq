"""Apply an adapter's declared `effects` to the DB (inside the task-success transaction).

Only the ops below exist. There is deliberately no op that sends anything: in phase (a) the only "outbound"
is `mock_mail`, which writes a `mock_mailbox` row."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from hq.db import repo, serializers
from hq.db.conn import dumps
from hq.util.ids import new_id
from hq.util.timeutil import now_iso


@dataclass
class EffectOutcome:
    created_opps: list[str] = field(default_factory=list)
    touched_opps: set[str] = field(default_factory=set)


def _jsonify(values: dict[str, Any]) -> dict[str, Any]:
    return {k: (dumps(v) if k.endswith("_json") and not isinstance(v, str) else v) for k, v in values.items()}


def _insert(conn: sqlite3.Connection, table: str, values: dict[str, Any], allowed: set[str]) -> None:
    bad = set(values) - allowed
    if bad:
        raise ValueError(f"{table}: columns not writable: {sorted(bad)}")
    vals = _jsonify(values)
    conn.execute(f"INSERT INTO {table}({','.join(vals)}) VALUES ({','.join('?' * len(vals))})", tuple(vals.values()))


def _update(conn: sqlite3.Connection, table: str, row_id: str, values: dict[str, Any], allowed: set[str],
            touch_updated_at: bool = True) -> None:
    bad = set(values) - allowed
    if bad:
        raise ValueError(f"{table}: columns not writable: {sorted(bad)}")
    vals = _jsonify(values)
    if touch_updated_at:
        vals["updated_at"] = now_iso()
    if not vals:
        return
    conn.execute(f"UPDATE {table} SET {','.join(f'{k}=?' for k in vals)} WHERE id=?", (*vals.values(), row_id))


APP_INSERT = {"id", "opportunity_id", "channel", "status", "mode", "doc_kind"}
APP_UPDATE = {"status", "letter_doc_id", "resume_doc_id", "answers_json", "gates_json", "submitted_at",
              "submission_ref", "gmail_thread_id", "message_id", "followup_due_at", "pack_need_id", "doc_kind"}
DOC_INSERT = {"id", "application_id", "opportunity_id", "kind", "version", "parent_id", "content_text", "sha256",
              "author_agent", "author_model", "lineage_models_json", "status", "content_path", "subject",
              "email_thread_id"}
EVENT_TYPES_ALLOWED = {"log", "notification"}
# The only tasks an adapter may request directly (everything else follows the pipeline state machine).
REQUESTABLE = {"inbox.classify", "reply.send"}
THREAD_COLS = {"id", "gmail_thread_id", "opportunity_id", "application_id", "subject", "counterpart_domain",
               "counterpart_addr"}
MSG_COLS = {"id", "gmail_message_id", "direction", "from_addr", "to_addr", "date", "subject", "snippet", "body_path",
            "rfc822_message_id", "in_reply_to"}


def apply_effects(conn: sqlite3.Connection, effects: list[dict[str, Any]], *, agent_id: str, task_id: str,
                  run_id: str, opportunity_id: str | None = None) -> EffectOutcome:
    out = EffectOutcome()
    now = now_iso()
    for eff in effects:
        op = eff.get("op")
        if op == "opp.create":
            opp_id = repo.insert_opportunity(conn, eff["values"], is_simulated=bool(eff.get("is_simulated", True)))
            out.created_opps.append(opp_id)
        elif op == "opp.update":
            repo.update_opportunity(conn, eff["id"], eff["values"])
            out.touched_opps.add(eff["id"])
        elif op == "eligibility_check":
            _insert(conn, "eligibility_checks", {"id": new_id(), "created_at": now, **eff["values"]},
                    {"id", "opportunity_id", "method", "model_id", "requirements_json", "quotes_json", "verdict",
                     "confidence", "run_id", "created_at"})
        elif op == "scam_check":
            _insert(conn, "scam_checks", {"id": new_id(), "created_at": now, **eff["values"]},
                    {"id", "opportunity_id", "signals_json", "verdict", "run_id", "created_at"})
        elif op == "application.create":
            values = dict(eff["values"])
            bad = set(values) - APP_INSERT
            if bad:
                raise ValueError(f"applications: columns not writable: {sorted(bad)}")
            values.setdefault("id", new_id())
            _insert(conn, "applications", {**values, "created_at": now, "updated_at": now},
                    APP_INSERT | {"created_at", "updated_at"})
        elif op == "application.update":
            _update(conn, "applications", eff["id"], eff["values"], APP_UPDATE)
        elif op == "document.create":
            values = dict(eff["values"])
            values.setdefault("id", new_id())
            _insert(conn, "documents", {**values, "created_at": now}, DOC_INSERT | {"created_at"})
            for s in eff.get("sentences", []):
                conn.execute(
                    "INSERT INTO document_sentences(id, document_id, idx, text, kind, fact_ids_json, job_quote_ids_json) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (s.get("id") or new_id(), values["id"], s["idx"], s["text"], s.get("kind"),
                     dumps(s.get("fact_ids", [])), dumps(s.get("job_quote_ids", []))))
            if values.get("opportunity_id"):
                out.touched_opps.add(values["opportunity_id"])
        elif op == "document.update":
            _update(conn, "documents", eff["id"], eff["values"], {"status", "content_path", "sha256"},
                    touch_updated_at=False)
        elif op == "opp.source":
            v = eff["values"]
            conn.execute(
                "INSERT INTO opportunity_sources(opportunity_id, source_id, external_id, source_url, first_seen, last_seen, "
                "raw_path) VALUES (?,?,?,?,?,?,?) ON CONFLICT(opportunity_id, source_id, external_id) DO UPDATE SET "
                "last_seen=excluded.last_seen, source_url=excluded.source_url",
                (v["opportunity_id"], v["source_id"], v.get("external_id"), v.get("source_url"), now, now,
                 v.get("raw_path")))
        elif op == "fact_check":
            _insert(conn, "fact_checks", {"id": new_id(), "created_at": now, "run_id": run_id, **eff["values"]},
                    {"id", "document_id", "sentence_id", "layer", "checker_model", "verdict", "rule_ids_json",
                     "unsupported_span", "explanation", "run_id", "created_at"})
        elif op == "gate_result":
            _insert(conn, "gate_results", {"id": new_id(), "ts": now, **eff["values"]},
                    {"id", "application_id", "document_id", "gate", "passed", "details_json", "ts"})
        elif op == "mock_mail":
            values = {"id": new_id(), **eff["values"], "created_at": now}
            _insert(conn, "mock_mailbox", values, {"id", "to_addr", "subject", "body", "attachments_json",
                                                   "in_reply_to", "application_id", "created_at"})
            opp_id = conn.execute("SELECT opportunity_id FROM applications WHERE id=?",
                                  (values.get("application_id"),)).fetchone()
            repo.emit(conn, "mail.mock_sent",
                      f"Mock mail → {values['to_addr']}: {values.get('subject')} (dry run — nothing left this Mac)",
                      agent_id=agent_id, task_id=task_id, opportunity_id=opp_id["opportunity_id"] if opp_id else None,
                      data={"to": values["to_addr"], "subject": values.get("subject"),
                            "application_id": values.get("application_id")})
        elif op == "need.create":
            need_id = repo.insert_need(conn, eff["values"])
            need = serializers.need_json(repo.get_need_row(conn, need_id))
            level = "alert" if need["kind"] in ("interview", "offer") else "info"
            repo.emit(conn, "needs.created", f"Needs Prerit: {need['title']}", level=level, agent_id=agent_id,
                      task_id=task_id, opportunity_id=need["opportunity_id"], data={"need": need})
            if need["opportunity_id"]:
                out.touched_opps.add(need["opportunity_id"])
        elif op == "email.inbound":
            t, m = eff["thread"], eff["message"]
            _insert(conn, "email_threads", {**t, "last_message_at": now},
                    {"id", "gmail_thread_id", "opportunity_id", "application_id", "subject", "counterpart_domain",
                     "last_message_at"})
            _insert(conn, "email_messages", {**m, "thread_id": t["id"], "date": now},
                    {"id", "gmail_message_id", "thread_id", "direction", "from_addr", "to_addr", "date", "subject",
                     "snippet"})
            repo.emit(conn, "log", f"New reply in mock inbox: \"{t.get('subject')}\" from {m.get('from_addr')}",
                      agent_id=agent_id, task_id=task_id, opportunity_id=t.get("opportunity_id"),
                      data={"thread_id": t["id"], "message_id": m["id"]})
        elif op == "email.classify":
            conn.execute("UPDATE email_messages SET classification=?, confidence=?, handled_run_id=?, lock_terms_json=?, "
                         "reason=? WHERE id=?",
                         (eff["classification"], eff.get("confidence"), run_id, dumps(eff.get("lock_terms") or []),
                          eff.get("reason"), eff["message_id"]))
            # a lock is sticky: only Prerit can lift it (audited, in the Inbox)
            conn.execute("UPDATE email_threads SET classification=?, notify_only_lock=MAX(notify_only_lock, ?), "
                         "lock_reason=CASE WHEN ? THEN COALESCE(lock_reason, ?) ELSE lock_reason END, "
                         "locked_at=CASE WHEN ? AND locked_at IS NULL THEN ? ELSE locked_at END WHERE id=?",
                         (eff["classification"], int(bool(eff.get("lock"))), int(bool(eff.get("lock"))),
                          eff.get("lock_reason"), int(bool(eff.get("lock"))), now, eff["thread_id"]))
            repo.emit(conn, "inbox.updated", f"Classified: {eff['classification'].replace('_', ' ')}"
                      + (" — notify-only lock" if eff.get("lock") else ""), level="debug", agent_id=agent_id,
                      task_id=task_id, opportunity_id=opportunity_id, data={"thread_id": eff["thread_id"]})
        elif op == "email.store":
            t, m = dict(eff["thread"]), dict(eff["message"])
            if set(t) - THREAD_COLS or set(m) - MSG_COLS:
                raise ValueError("email.store: columns not writable")
            row = conn.execute("SELECT id, opportunity_id, application_id, counterpart_addr FROM email_threads WHERE "
                               "gmail_thread_id=?", (t["gmail_thread_id"],)).fetchone()
            if row:
                t["id"] = row["id"]
                conn.execute("UPDATE email_threads SET last_message_at=?, opportunity_id=COALESCE(opportunity_id, ?), "
                             "application_id=COALESCE(application_id, ?), counterpart_addr=COALESCE(counterpart_addr, ?) "
                             "WHERE id=?", (m.get("date") or now, t.get("opportunity_id"), t.get("application_id"),
                                            t.get("counterpart_addr"), row["id"]))
            else:
                _insert(conn, "email_threads", {**t, "created_at": now, "last_message_at": m.get("date") or now},
                        THREAD_COLS | {"created_at", "last_message_at"})
            cur = conn.execute(
                f"INSERT OR IGNORE INTO email_messages({','.join(['thread_id', *m])}) "
                f"VALUES ({','.join('?' * (len(m) + 1))})", (t["id"], *m.values()))
            if cur.rowcount:
                repo.emit(conn, "inbox.updated", f"New mail: “{m.get('subject') or '(no subject)'}” from "
                          f"{m.get('from_addr')}", agent_id=agent_id, task_id=task_id,
                          opportunity_id=t.get("opportunity_id"), data={"thread_id": t["id"], "message_id": m["id"]})
                if t.get("opportunity_id"):
                    out.touched_opps.add(t["opportunity_id"])
        elif op == "task.request":
            from hq.pipeline.state import priority_for
            from hq.worker import queue

            cap = eff["capability"]
            if cap not in REQUESTABLE:
                raise ValueError(f"adapters may not request {cap!r} tasks")
            queue.enqueue(conn, cap, payload=eff.get("payload") or {}, opportunity_id=eff.get("opportunity_id"),
                          priority=priority_for(cap), idempotency_key=eff["key"], parent_task_id=task_id,
                          source_agent=agent_id)
        elif op == "gmail.state":
            from hq.db.seed import get_setting, set_settings

            cur_state = get_setting(conn, "gmail_state", {}) or {}
            set_settings(conn, {"gmail_state": {**cur_state, **eff["values"]}}, by="worker")
        elif op == "followup.create":
            v = eff["values"]
            conn.execute("INSERT OR IGNORE INTO followups(id, application_id, opportunity_id, to_addr, due_at, status, "
                         "reason, created_at, updated_at) VALUES (?,?,?,?,?, 'scheduled', ?, ?, ?)",
                         (new_id(), v["application_id"], v.get("opportunity_id"), v.get("to_addr"), v["due_at"],
                          v.get("reason"), now, now))
        elif op == "notification":
            v = eff["values"]
            conn.execute("INSERT INTO notifications(id, severity, title, body, url, created_at) VALUES (?,?,?,?,?,?)",
                         (new_id(), v["severity"], v["title"], v.get("body"), v.get("url"), now))
            repo.emit(conn, "notification", v["title"], level="alert" if v["severity"] == "alert" else "info",
                      agent_id=agent_id, task_id=task_id,
                      data={"severity": v["severity"], "title": v["title"], "body": v.get("body"), "url": v.get("url")})
        elif op == "strategy_report":
            v = eff["values"]
            conn.execute(
                "INSERT INTO strategy_reports(date, report_md, proposed_actions_json, created_at) VALUES (?,?,?,?) "
                "ON CONFLICT(date) DO UPDATE SET report_md=excluded.report_md, "
                "proposed_actions_json=excluded.proposed_actions_json, created_at=excluded.created_at",
                (v["date"], v["report_md"], dumps(v.get("proposed_actions_json", [])), now))
        elif op == "event":
            if eff.get("type") not in EVENT_TYPES_ALLOWED:
                raise ValueError(f"adapters may not emit event type {eff.get('type')!r}")
            repo.emit(conn, eff["type"], eff["message"], level=eff.get("level", "info"), agent_id=agent_id,
                      task_id=task_id, opportunity_id=eff.get("opportunity_id") or opportunity_id,
                      data=eff.get("data"))
        else:
            raise ValueError(f"unknown effect op {op!r}")
    return out
