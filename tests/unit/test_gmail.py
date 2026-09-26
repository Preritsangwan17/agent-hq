"""Gmail plumbing (CONTRACT_D §1, §3): OAuth loopback flow, token refresh, client error mapping, the net guard, the
startup refusal, SELF-TEST equality, and duplicate-send recovery. No test ever talks to Google: the real client runs
against httpx MockTransports and everything else uses hq/gmail/fake.py."""
from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from hq import settings as paths
from hq.db.conn import tx
from hq.db.seed import set_settings
from hq.gmail import auth as gauth
from hq.gmail.api import GmailError, GmailNotFound, GmailTransient
from hq.gmail.client import GmailClient
from hq.gmail.fake import FakeGmail
from hq.gmail.sender import build_mime
from hq.pipeline.apply import guard
from hq.util import netguard

SEND = ("https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.compose")


@pytest.fixture
def oauth_client(hq_env):
    paths.set_env_value("HQ_GMAIL_CLIENT_ID", "1234-abc.apps.googleusercontent.com")
    paths.set_env_value("HQ_GMAIL_CLIENT_SECRET", "GOCSPX-test-secret")
    return hq_env


def token_api(calls: list, *, scope: str = "https://www.googleapis.com/auth/gmail.readonly", status: int = 200):
    def handler(req: httpx.Request) -> httpx.Response:
        form = parse_qs(req.content.decode())
        calls.append({k: v[0] for k, v in form.items()})
        if status != 200:
            return httpx.Response(status, json={"error": "invalid_grant"})
        return httpx.Response(200, json={"access_token": "ya29.test-access-token-abcdefghijklmnop",
                                         "refresh_token": "1//test-refresh-token-abcdefghijk", "expires_in": 3599,
                                         "scope": scope, "token_type": "Bearer"})
    return httpx.MockTransport(handler)


# ── OAuth ────────────────────────────────────────────────────────────────────────────────────────────
async def _redirect(url: str, query: str) -> str:
    port = urlparse(url).port
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET /?{query} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode())
    await writer.drain()
    data = await reader.read()
    writer.close()
    return data.decode()


async def test_oauth_loopback_flow_stores_only_readonly_grant_in_env(oauth_client):
    calls: list = []
    flow = gauth.OAuthFlow(transport=token_api(calls))
    url = await flow.start("readonly")
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert q["scope"] == gauth.SCOPE_READONLY and q["code_challenge_method"] == "S256" and q["access_type"] == "offline"
    assert urlparse(q["redirect_uri"]).hostname == "127.0.0.1"
    page = await _redirect(q["redirect_uri"], f"code=4%2Fabc&state={q['state']}")
    assert "Gmail connected" in page and flow.status == "done"
    assert calls[0]["grant_type"] == "authorization_code" and calls[0]["code_verifier"]
    env = paths.read_env_file()
    assert env["HQ_GMAIL_REFRESH_TOKEN"].startswith("1//") and env["HQ_GMAIL_SCOPES"] == gauth.SCOPE_READONLY
    assert gauth.connected() and not gauth.has_send_scope()


async def test_oauth_rejects_state_mismatch_and_cancelled_consent(oauth_client):
    flow = gauth.OAuthFlow(transport=token_api([]))
    url = await flow.start("readonly")
    redirect = parse_qs(urlparse(url).query)["redirect_uri"][0]
    await _redirect(redirect, "code=x&state=forged")
    assert flow.status == "error" and "state" in flow.error
    assert "HQ_GMAIL_REFRESH_TOKEN" not in paths.read_env_file()
    url = await flow.start("readonly")
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    await _redirect(q["redirect_uri"], f"error=access_denied&state={q['state']}")
    assert flow.status == "error" and "access_denied" in flow.error
    await flow.close()


async def test_send_consent_asks_for_send_and_compose(oauth_client):
    flow = gauth.OAuthFlow(transport=token_api([]))
    url = await flow.start("send")
    assert set(parse_qs(urlparse(url).query)["scope"][0].split()) == set(SEND)
    await flow.close()


async def test_token_refresh_and_revoked_grant(oauth_client):
    paths.set_env_value("HQ_GMAIL_REFRESH_TOKEN", "1//stored")
    calls: list = []
    tp = gauth.TokenProvider(transport=token_api(calls))
    assert (await tp.access_token()).startswith("ya29.") and await tp.access_token()
    assert len(calls) == 1 and calls[0]["grant_type"] == "refresh_token"
    with pytest.raises(gauth.GmailAuthError, match="reconnect"):
        await gauth.TokenProvider(transport=token_api([], status=400)).access_token()


# ── client ───────────────────────────────────────────────────────────────────────────────────────────
class FixedTokens:
    def __init__(self):
        self.invalidated = 0

    async def access_token(self) -> str:
        return "ya29.fixed"

    def invalidate(self) -> None:
        self.invalidated += 1


async def test_client_maps_errors_and_retries_once_after_401():
    seen: list[httpx.Request] = []
    replies = iter([httpx.Response(401), httpx.Response(200, json={"emailAddress": "p@x", "historyId": "9"})])

    def handler(req):
        seen.append(req)
        return next(replies)

    toks = FixedTokens()
    c = GmailClient(toks, transport=httpx.MockTransport(handler))
    assert (await c.profile())["historyId"] == "9" and toks.invalidated == 1 and len(seen) == 2
    for status, exc in ((404, GmailNotFound), (500, GmailTransient), (429, GmailTransient), (400, GmailError)):
        c2 = GmailClient(FixedTokens(), transport=httpx.MockTransport(lambda r, s=status: httpx.Response(s, json={})))
        with pytest.raises(exc):
            await c2.history("1")


async def test_client_send_is_blocked_by_the_net_guard_in_dry_run(monkeypatch):
    c = GmailClient(FixedTokens(), transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"id": "x"})))
    with pytest.raises(netguard.NetGuardError):
        await c.send(b"raw")
    monkeypatch.setenv("HQ_FORCE_DRY_RUN", "0")
    monkeypatch.setenv("HQ_MODE", "live")
    assert (await c.send(b"raw"))["id"] == "x"


def test_net_guard_allows_the_token_endpoint_but_nothing_else_on_google():
    netguard.check("POST", "https://oauth2.googleapis.com/token")
    with pytest.raises(netguard.NetGuardError):
        netguard.check("POST", "https://oauth2.googleapis.com/revoke")
    with pytest.raises(netguard.NetGuardError):
        netguard.check("POST", "https://gmail.googleapis.com/gmail/v1/users/me/drafts")
    netguard.check("GET", "https://gmail.googleapis.com/gmail/v1/users/me/history")


def test_mime_has_our_message_id_threading_and_attachment(tmp_path):
    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    raw = build_mime(from_addr="sangwanprerit40@gmail.com", to_addr="hr@fakeco.ai", subject="Re: hi", body="Hello",
                     message_id="<hq-abc@agenthq.local>", attachments=[{"name": "r.pdf", "path": str(pdf)}],
                     in_reply_to="<m1@x>")
    text = raw.decode(errors="replace")
    assert "Message-ID: <hq-abc@agenthq.local>" in text and "In-Reply-To: <m1@x>" in text
    assert 'filename="r.pdf"' in text and "application/pdf" in text


# ── startup refusal ─────────────────────────────────────────────────────────────────────────────────
def test_worker_refuses_to_start_with_send_scope_while_forced_dry_run(db, monkeypatch):
    from hq.db.seed import get_setting
    from hq.worker import __main__ as worker_main

    monkeypatch.delenv("HQ_FORCE_DRY_RUN", raising=False)
    paths.set_env_value("HQ_GMAIL_SCOPES", " ".join(SEND))
    assert "HQ_FORCE_DRY_RUN" in (gauth.startup_refusal() or "")
    assert worker_main.main() == worker_main.REFUSE_EXIT
    assert "send mail" in get_setting(db, "worker_refusal")["reason"]
    paths.set_env_value("HQ_GMAIL_SCOPES", gauth.SCOPE_READONLY)
    assert gauth.startup_refusal() is None


# ── sending: modes, self-test, recovery ──────────────────────────────────────────────────────────────
def _app(db, email="careers@fakeco.ai"):
    from hq.db import repo

    with tx(db):
        oid = repo.insert_opportunity(db, {"canonical_key": f"t:{email}", "company_name": "Fakeco", "title": "ML Intern",
                                           "url": "https://fakeco.ai/careers", "apply_email": email,
                                           "apply_email_quote": f"Send your CV to {email}", "stage": "checked"},
                                      is_simulated=False)
        db.execute("INSERT INTO applications(id, opportunity_id, channel, status, mode, created_at, updated_at) "
                   "VALUES (?, ?, 'email', 'queued', 'dry_run', '2026-09-01', '2026-09-01')", (f"app-{oid}", oid))
    return oid, f"app-{oid}"


@pytest.fixture
def live(db, monkeypatch):
    monkeypatch.setenv("HQ_FORCE_DRY_RUN", "0")
    monkeypatch.setenv("HQ_MODE", "live")
    with tx(db):
        set_settings(db, {"mode": "live"})
    return FakeGmail(scopes=SEND)


def _kw(app_id, **over):
    return {"kind": "application", "to_addr": "careers@fakeco.ai", "subject": "Application: ML Intern",
            "body": "Dear Hiring Team, …", "attachments": [], "content_sha": "sha-1", "application_id": app_id,
            **over}


async def test_live_send_goes_through_gmail_once_and_records_the_thread(db, live):
    _, app = _app(db)
    res = await guard.send(db, live, **_kw(app))
    again = await guard.send(db, live, **_kw(app))
    assert res.status == "sent" and again.status == "duplicate" and len(live.sent()) == 1
    sent = live.sent()[0]
    assert sent.rfc822_id == res.message_id and sent.to_addrs == ["careers@fakeco.ai"]
    row = db.execute("SELECT status, submission_ref, gmail_thread_id FROM applications WHERE id=?", (app,)).fetchone()
    assert row["status"] == "submitted" and row["submission_ref"].startswith("gmail:") and row["gmail_thread_id"]
    assert db.execute("SELECT COUNT(*) FROM email_messages WHERE direction='outbound'").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM mock_mailbox").fetchone()[0] == 0


async def test_self_test_mode_only_ever_writes_to_prerit(db, live):
    _, app = _app(db)
    with tx(db):
        set_settings(db, {"mode": "self_test"})
    with pytest.raises(guard.GuardBlocked) as e:
        await guard.send(db, live, **_kw(app))
    assert e.value.kind == "mode" and not live.sent()
    res = await guard.self_test(db, live)
    assert res.status == "sent" and live.sent()[0].to_addrs == [guard.PRERIT_EMAIL]
    with pytest.raises(guard.GuardBlocked):
        await guard.send(db, live, kind="self_test", to_addr="someone@else.com", subject="x", body="y",
                         attachments=[], content_sha="z")


async def test_self_test_refused_while_env_forces_dry_run(db, monkeypatch):
    monkeypatch.delenv("HQ_FORCE_DRY_RUN", raising=False)
    with pytest.raises(guard.GuardBlocked, match="go-live"):
        await guard.self_test(db, FakeGmail(scopes=SEND))


async def test_reset_after_the_request_is_resolved_from_sent_not_resent(db, live):
    _, app = _app(db)
    live.fail_next_send = "crash_after_send"
    res = await guard.send(db, live, **_kw(app))
    assert res.status == "sent" and len(live.sent()) == 1          # found in Sent → recorded, no ambiguity
    assert (await guard.send(db, live, **_kw(app))).status == "duplicate" and len(live.sent()) == 1


async def test_crash_recovery_checks_sent_before_any_resend(db, live):
    """The worker died after writing the intent. Case A: the message did go out → recovery marks it sent and the
    retried task sees a duplicate. Case B: it never went out → recovery marks it failed and the retry sends once."""
    _, app_a = _app(db, "careers@fakeco.ai")
    p = guard.prepare(db, **_kw(app_a))                                  # intent written …
    live._store("s-crash", build_mime(from_addr=guard.PRERIT_EMAIL, to_addr=p.to_addr, subject=p.subject,
                                      body=p.body, message_id=p.message_id), "t-crash", ["SENT"])  # … and delivered
    _, app_b = _app(db, "jobs@otherco.ai")
    with tx(db):
        db.execute("UPDATE opportunities SET company_name='Otherco', url='https://otherco.ai' WHERE id="
                   "(SELECT opportunity_id FROM applications WHERE id=?)", (app_b,))
    guard.prepare(db, **_kw(app_b, to_addr="jobs@otherco.ai", content_sha="sha-b"))   # intent, never sent
    res = await guard.recover(db, live, older_than_s=0)
    assert res == {"sent": 1, "failed": 1, "ambiguous": 0}
    assert (await guard.send(db, live, **_kw(app_a))).status == "duplicate"
    assert (await guard.send(db, live, **_kw(app_b, to_addr="jobs@otherco.ai", content_sha="sha-b"))).status == "sent"
    assert len(live.sent()) == 2
    assert db.execute("SELECT status FROM applications WHERE id=?", (app_a,)).fetchone()[0] == "submitted"


async def test_unknown_outcome_becomes_ambiguous_and_is_never_retried(db, live, authed):
    from conftest import MUTATE

    _, app = _app(db)
    live.fail_next_send = "timeout"
    with pytest.raises(guard.GuardBlocked) as e:
        await guard.send(db, live, **_kw(app))
    assert e.value.kind == "ambiguous"
    out = db.execute("SELECT * FROM outbound_log").fetchone()
    assert out["status"] == "ambiguous"
    need = db.execute("SELECT * FROM needs_prerit WHERE json_extract(payload_json,'$.decision')='outbound_ambiguous'"
                      ).fetchone()
    assert need and "rfc822msgid" in need["instructions_md"]
    assert (await guard.send(db, live, **_kw(app))).status == "duplicate" and not live.sent()   # never auto-retried
    r = authed.patch(f"/api/needs/{need['id']}", json={"status": "done", "choice": "not_sent"}, headers=MUTATE)
    assert r.status_code == 200
    assert db.execute("SELECT status FROM outbound_log WHERE id=?", (out["id"],)).fetchone()[0] == "failed"


async def test_definite_gmail_refusal_is_failed_not_ambiguous(db, live):
    _, app = _app(db)
    live.fail_next_send = "400"
    with pytest.raises(guard.GuardBlocked) as e:
        await guard.send(db, live, **_kw(app))
    assert e.value.kind == "failed"
    assert db.execute("SELECT status FROM outbound_log").fetchone()[0] == "failed"
    assert not db.execute("SELECT 1 FROM needs_prerit").fetchone()


def test_readonly_fake_cannot_send():
    g = FakeGmail()
    with pytest.raises(GmailError):
        asyncio.run(g.send(b"x"))
    assert json.dumps(g.calls)
