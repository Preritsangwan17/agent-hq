"""Auth, session cookie, Host allowlist, CSRF headers, loopback-only setup, login rate limit, SSE auth."""
from __future__ import annotations

import os

from conftest import MUTATE, PASSCODE
from fastapi.testclient import TestClient

from hq.api import auth


def test_scrypt_hash_roundtrip_and_format():
    encoded = auth.hash_passcode("hunter22")
    scheme, n, r, p, salt, digest = encoded.split("$")
    assert (scheme, n, r, p) == ("scrypt", str(2 ** 14), "8", "1") and salt and digest
    assert auth.verify_passcode("hunter22", encoded)
    assert not auth.verify_passcode("hunter23", encoded)
    assert not auth.verify_passcode("hunter22", None)
    assert not auth.verify_passcode("hunter22", "scrypt$abc")
    assert not auth.verify_passcode("hunter22", encoded.replace("scrypt$", "md5$"))
    assert auth.hash_passcode("same") != auth.hash_passcode("same")  # salted


def test_session_secret_created_on_first_run(hq_env):
    assert not os.environ.get("HQ_SESSION_SECRET")
    auth.ensure_session_secret()
    secret = os.environ["HQ_SESSION_SECRET"]
    assert len(secret) == 64
    assert f"HQ_SESSION_SECRET={secret}" in hq_env.env_file.read_text()
    assert oct(hq_env.env_file.stat().st_mode & 0o777) == "0o600"


def test_status_setup_and_login_cookie_flags(client, hq_env):
    assert client.get("/api/auth/status").json() == {"configured": False, "authenticated": False, "loopback": True}
    assert client.post("/api/auth/setup", json={"passcode": "short"}, headers=MUTATE).status_code == 400
    r = client.post("/api/auth/setup", json={"passcode": PASSCODE}, headers=MUTATE)
    assert r.status_code == 200
    assert "HQ_PASSCODE_HASH=scrypt$" in hq_env.env_file.read_text()
    assert PASSCODE not in hq_env.env_file.read_text()
    assert client.post("/api/auth/setup", json={"passcode": PASSCODE}, headers=MUTATE).status_code == 409

    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401
    bad = client.post("/api/auth/login", json={"passcode": "nope-nope"}, headers=MUTATE)
    assert bad.status_code == 401 and bad.json() == {"error": "wrong passcode"}
    r = client.post("/api/auth/login", json={"passcode": PASSCODE}, headers=MUTATE)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("hq_session=")
    for flag in ("HttpOnly", "SameSite=strict", "Path=/", "Max-Age=2592000"):
        assert flag.lower() in cookie.lower()
    me = client.get("/api/auth/me").json()
    assert me["ok"] is True and me["owner"]["email"] == "sangwanprerit40@gmail.com"
    assert client.get("/api/auth/status").json()["authenticated"] is True

    client.post("/api/auth/logout", headers=MUTATE)
    client.cookies.clear()
    assert client.get("/api/snapshot").status_code == 401


def test_tampered_cookie_rejected(authed):
    token = authed.cookies.get("hq_session")
    authed.cookies.clear()
    authed.cookies.set("hq_session", token[:-2] + ("AA" if not token.endswith("AA") else "BB"))
    assert authed.get("/api/auth/me").status_code == 401


def test_bad_host_gets_421(authed):
    r = authed.get("/api/health", headers={"Host": "evil.example"})
    assert r.status_code == 421
    assert authed.get("/", headers={"Host": "rebind.attacker.test:8765"}).status_code == 421
    assert authed.get("/api/health", headers={"Host": "127.0.0.1:8765"}).status_code == 200
    assert authed.get("/api/health", headers={"Host": "[::1]:8765"}).status_code == 200


def test_lan_hosts_only_when_enabled(authed, monkeypatch):
    monkeypatch.setenv("HQ_ALLOWED_HOSTS", "macbook.local")
    assert authed.get("/api/health", headers={"Host": "macbook.local"}).status_code == 421
    monkeypatch.setenv("HQ_LAN", "1")
    assert authed.get("/api/health", headers={"Host": "macbook.local:8765"}).status_code == 200


def test_mutations_need_x_hq_and_allowed_origin(authed):
    body = {"reason": "test"}
    assert authed.post("/api/control/pause-all", json=body).status_code == 403
    assert authed.post("/api/control/pause-all", json=body, headers={"X-HQ": "1"}).status_code == 403
    assert authed.post("/api/control/pause-all", json=body,
                       headers={"Origin": "http://localhost:5173"}).status_code == 403
    assert authed.post("/api/control/pause-all", json=body,
                       headers={"X-HQ": "1", "Origin": "https://evil.example"}).status_code == 403
    assert authed.patch("/api/settings", json={"sim_speed": 2}, headers={"X-HQ": "1", "Origin": "null"}).status_code == 403
    assert authed.post("/api/control/pause-all", json=body, headers=MUTATE).status_code == 200
    assert authed.post("/api/control/pause-all", json=body,
                       headers={"X-HQ": "1", "Origin": "http://127.0.0.1:8765"}).status_code == 200


def test_login_also_needs_csrf_headers(client):
    assert client.post("/api/auth/login", json={"passcode": PASSCODE}).status_code == 403


def test_setup_is_loopback_only(app):
    with TestClient(app, base_url="http://localhost", client=("192.168.1.50", 40000)) as lan:
        r = lan.post("/api/auth/setup", json={"passcode": PASSCODE}, headers=MUTATE)
        assert r.status_code == 403 and "loopback" in r.json()["error"]
        assert lan.get("/api/auth/status").json()["loopback"] is False
    assert not auth.is_configured()


def test_login_rate_limited_per_ip(authed):
    authed.cookies.clear()
    codes = [authed.post("/api/auth/login", json={"passcode": "wrong-one"}, headers=MUTATE).status_code
             for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    # even the right passcode is refused while limited
    assert authed.post("/api/auth/login", json={"passcode": PASSCODE}, headers=MUTATE).status_code == 429


def test_protected_routes_and_sse_require_cookie(client):
    assert client.get("/api/health").status_code == 200  # public
    for path in ("/api/snapshot", "/api/events", "/api/agents", "/api/stats", "/api/stream", "/api/needs",
                 "/api/opportunities", "/api/settings"):
        r = client.get(path)
        assert r.status_code == 401, path
        assert r.json() == {"error": "unauthorized"}
