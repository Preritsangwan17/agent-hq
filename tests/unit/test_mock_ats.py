"""The browser adapter against the local mock ATS (real Chromium, loopback only). Skipped when Chromium or port
8799 isn't available. Checks it fills a clean form and STOPS at CAPTCHA, login walls, sensitive IDs and fees."""
from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest

from hq.db.conn import tx
from hq.pipeline.apply import browser


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


@pytest.fixture
def mock_ats(tmp_path, monkeypatch):
    if browser._chromium_path() is None:
        pytest.skip("no Chromium for Playwright")
    if not _port_free(8799):
        pytest.skip("port 8799 busy")
    import uvicorn

    monkeypatch.setenv("HQ_MOCK_ATS_DIR", str(tmp_path / "mock_ats"))
    import importlib

    import mock_ats.app as app_mod

    app_mod = importlib.reload(app_mod)
    server = uvicorn.Server(uvicorn.Config(app_mod.app, host="127.0.0.1", port=8799, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if not _port_free(8799):
            break
        time.sleep(0.05)
    yield tmp_path / "mock_ats"
    server.should_exit = True
    t.join(timeout=5)


async def test_browser_fills_only_what_it_may_and_stops_otherwise(db, mock_ats, tmp_path):
    from hq.profile.fields import update_field

    resume = tmp_path / "r.pdf"
    resume.write_bytes(b"%PDF-1.4 test")
    kw = dict(conn=db, letter="Dear Hiring Team, hello.", resume_path=str(resume), shot=tmp_path / "s.png")
    stops = {}
    for jid in ("1001", "1002", "1003", "1004", "1005"):
        try:
            await browser.fill_and_submit(f"http://127.0.0.1:8799/jobs/{jid}", **kw)
        except browser.Stop as e:
            stops[jid] = e.reason
    assert "Phone" in stops["1001"]                    # unconfirmed phone → stop, never guessed
    assert "CAPTCHA" in stops["1002"]
    assert "login" in stops["1003"]
    assert "sensitive" in stops["1004"]
    assert "fee" in stops["1005"]
    assert not (mock_ats / "submissions.jsonl").exists()   # nothing was submitted on any stopped form
    with tx(db):
        update_field(db, "phone", "+91 90000 11111")
    res = await browser.fill_and_submit("http://127.0.0.1:8799/jobs/1001", **kw)
    assert res["ref"].startswith("MOCK-1001-") and Path(res["screenshot"]).exists()
    lines = (mock_ats / "submissions.jsonl").read_text().splitlines()
    assert len(lines) == 1 and '"email": "sangwanprerit40@gmail.com"' in lines[0] and '"resume": "r.pdf"' in lines[0]
    with pytest.raises(browser.Stop, match="only fills the local mock ATS"):
        await browser.fill_and_submit("https://boards.greenhouse.io/x/jobs/1", **kw)
