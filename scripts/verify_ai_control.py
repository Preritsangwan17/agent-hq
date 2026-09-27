"""Browser regression check against the real API in a temporary, offline database."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/test/ai-control'
OUT.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='hq-ai-browser-') as folder:
    tmp = Path(folder)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    env = {**os.environ, 'HQ_DATA_DIR': folder, 'HQ_ENV_FILE': str(tmp / '.env'),
           'HQ_DB_PATH': str(tmp / 'hq.db'), 'HQ_RUN_DIR': str(tmp / 'run'),
           'HQ_LOG_DIR': str(tmp / 'logs'), 'HQ_AGENTS_DIR': str(tmp / 'agents'),
           'HQ_PORT': str(port), 'HQ_OFFLINE': '1', 'HQ_CLAUDE_BIN': str(tmp / 'no-claude'),
           'HQ_CODEX_BIN': str(tmp / 'no-codex')}
    for key in ('HQ_PASSCODE_HASH', 'HQ_SESSION_SECRET', 'HQ_LAN'):
        env.pop(key, None)
    with (OUT / 'browser-server.log').open('w') as log:
        server = subprocess.Popen([sys.executable, '-m', 'hq.api'], cwd=ROOT, env=env, stdout=log, stderr=log)
        try:
            for _ in range(100):
                try:
                    if urlopen(base + '/api/health', timeout=1).status == 200:
                        break
                except Exception:
                    time.sleep(.1)
            else:
                raise RuntimeError('Temporary API did not start')
            db = sqlite3.connect(tmp / 'hq.db')
            for rid, mid, status, reason, parent in (
                ('ui-local', 'ollama:test-local', 'failed', 'Local AI first. Test output failed validation.', None),
                ('ui-cloud', 'codex:test', 'succeeded', 'Fallback after local validation failed. Codex matches coding.', 'ui-local')):
                db.execute("INSERT INTO agent_runs(id, agent_id, adapter, model_id, status, started_at, finished_at, "
                           "ai_mode, task_type, route_reason, execution, duration_ms, escalated_from_run_id) "
                           "VALUES (?, 'router', 'test', ?, ?, '2026-09-27T10:00:00Z', '2026-09-27T10:00:01Z', "
                           "'local_codex', 'coding', ?, ?, 1200, ?)",
                           (rid, mid, status, reason, 'local' if rid == 'ui-local' else 'cloud', parent))
            db.commit()
            db.close()
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='chrome', headless=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                errors = []
                page = context.new_page()
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
                headers = {'X-HQ': '1', 'Origin': base}
                assert context.request.post(base + '/api/auth/setup', data={'passcode': 'ui-test-passcode'}, headers=headers).status == 200
                page.goto(base + '/ai')
                expect(page.get_by_role('heading', name='AI Control', exact=True)).to_be_visible()
                expect(page.get_by_label('Active mode')).to_be_visible()
                modes = context.request.get(base + '/api/ai/control').json()['modes']
                for mode in modes:
                    page.get_by_label('Active mode').select_option(mode['id'])
                    expect(page.get_by_text('Saved · applies to the next dispatch', exact=True)).to_be_visible()
                    expect(page.get_by_label('Active mode')).to_be_enabled()
                    actual = context.request.get(base + '/api/ai/control').json()
                    assert actual['current_mode'] == mode['id']
                    assert actual['providers'][0]['enabled'] is True
                page.get_by_label('Active mode').select_option('local')
                expect(page.get_by_label('Active mode')).to_be_enabled()
                page.get_by_role('switch', name='Enable ChatGPT / Codex CLI').click()
                expect(page.get_by_label('Active mode')).to_have_value('local_codex')
                page.reload()
                expect(page.get_by_label('Active mode')).to_have_value('local_codex')
                expect(page.get_by_role('switch', name='Enable ChatGPT / Codex CLI')).to_be_checked()
                page.get_by_label('Workflow preview').select_option('coding')
                expect(page.get_by_role('heading', name='Propose code and debugging changes')).to_be_visible()
                page.get_by_label('Workflow preview').select_option('job_search')
                expect(page.get_by_role('heading', name='Filter and rank opportunities')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                expect(page.get_by_text('Fallback', exact=True)).to_be_visible()
                page.screenshot(path=str(OUT / 'desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.reload()
                page.wait_for_timeout(500)
                expect(page.get_by_label('Active mode')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(OUT / 'mobile.png'))
                page.get_by_role('heading', name='Task & subtask history').scroll_into_view_if_needed()
                page.screenshot(path=str(OUT / 'mobile-history.png'))
                page.goto(base + '/settings?tab=budget')
                expect(page.get_by_role('switch', name='Use Local models')).to_be_disabled()
                assert not errors, errors
                browser.close()
                (OUT / 'result.json').write_text(json.dumps({'passed': True, 'modes_verified': len(modes), 'viewports': [1440, 390], 'console_errors': errors}, indent=2))
                print('Browser checks passed: nine modes, provider switch, persistence, workflow previews, desktop/mobile layout, locked Local AI control.')
        finally:
            server.terminate()
            server.wait(timeout=10)
