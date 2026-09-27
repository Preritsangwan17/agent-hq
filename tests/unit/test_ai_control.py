"""AI control uses real settings and telemetry; provider execution is always faked."""
import pytest

from hq.db.conn import tx
from hq.db.seed import get_settings, set_settings
from hq.llm import cloud, modes, policy
from hq.llm.claude import ClaudeRateLimited
from hq.llm.router import EscalationExhausted, Router
from hq.util.timeutil import today_ist
from hq.worker import budget
from tests.conftest import MUTATE
from tests.unit.test_llm import FakeManager, make_chat, _setup_roles, SCHEMA
from tests.unit.test_providers import Fake, runner, put, MSGS


@pytest.mark.parametrize('mode', list(modes.MODES))
async def test_every_mode_requires_local_and_dispatches_only_allowed_providers(db, mode):
    put(db, ai_mode=mode)
    s = get_settings(db)
    r = runner(db)
    assert modes.enabled(s, 'local') and 'local' in modes.MODES[mode]['providers']
    await r.check_all()
    for p in cloud.PROVIDERS:
        assert r.runners[p].checks == int(p in modes.MODES[mode]['providers'])
        if not modes.enabled(s, p):
            with pytest.raises(Exception, match='switched off'):
                await r.run('p', schema=SCHEMA, system_prompt='s', model=cloud.model_for(s, p))
            assert r.runners[p].calls == 0


def test_mode_api_validates_and_keeps_switches_consistent(authed):
    for bad in ('claude', [], None, 'local_grok'):
        assert authed.patch('/api/settings', json={'ai_mode': bad}, headers=MUTATE).status_code == 400
    assert authed.patch('/api/settings', json={'llm_local_enabled': False}, headers=MUTATE).status_code == 400
    assert authed.patch('/api/settings', json={'ai_mode': 'local', 'llm_codex_enabled': True}, headers=MUTATE).status_code == 400
    r = authed.patch('/api/settings', json={'ai_mode': 'local_codex'}, headers=MUTATE)
    assert r.status_code == 200
    s = r.json()['settings']
    assert s['llm_local_enabled'] and s['llm_codex_enabled'] and not s['llm_claude_enabled'] and not s['llm_xai_enabled']
    r = authed.patch('/api/settings', json={'llm_xai_enabled': True}, headers=MUTATE)
    assert r.json()['settings']['ai_mode'] == 'local_codex_xai'
    r = authed.patch('/api/settings', json={'ai_mode': 'auto'}, headers=MUTATE)
    assert r.json()['settings']['llm_claude_enabled'] is False  # Auto cannot silently re-enable a provider


async def test_successful_local_result_never_checks_cloud_even_with_a_cloud_pin(db):
    _setup_roles(db)
    r = runner(db)
    chat = make_chat({'mlx:q/Qwen3-4B': ['{"verdict":"yes","confidence":0.99}']})
    res = await Router(db, FakeManager(), r, chat_fn=chat).route('eligibility', MSGS, SCHEMA, pinned_model='codex:default')
    assert res.model_id.startswith('mlx:')
    assert all(f.checks == f.calls == 0 for f in r.runners.values())
    row = db.execute('SELECT * FROM agent_runs WHERE id=?', (res.run_id,)).fetchone()
    assert row['execution'] == 'local' and 'Local AI first' in row['route_reason']
    assert not db.execute('SELECT 1 FROM claude_usage').fetchone()


async def test_mode_change_during_local_failure_prevents_cloud_dispatch(db):
    _setup_roles(db)
    r = runner(db)
    async def chat(*args, **kw):
        from hq.llm.client import LLMError
        put(db, ai_mode='local')
        raise LLMError('local failure after mode change')
    with pytest.raises(EscalationExhausted):
        await Router(db, FakeManager(), r, chat_fn=chat).route('eligibility', MSGS, SCHEMA)
    assert all(f.calls == f.checks == 0 for f in r.runners.values())


async def test_rate_limit_falls_back_and_records_both_attempts(db):
    r = runner(db, claude=Fake(exc=ClaudeRateLimited('usage limit')))
    res = await Router(db, None, r).route('summarizer', MSGS, SCHEMA, task_type='planning')
    assert res.model_id == 'codex:default'
    rows = db.execute('SELECT * FROM agent_runs ORDER BY rowid').fetchall()
    assert [x['status'] for x in rows] == ['failed', 'succeeded']
    assert rows[1]['escalated_from_run_id'] == rows[0]['id']
    assert 'Fallback' in rows[1]['route_reason']
    assert r.rest_reason('claude')
    assert budget.usage_today(db)['calls'] == 1  # failed, unbilled attempt releases its reservation


async def test_cloud_respects_custom_confidence_threshold(db):
    from hq.llm.claude import ClaudeResult
    class Low(Fake):
        async def run(self, *a, **kw):
            return ClaudeResult({'verdict': 'yes', 'confidence': .85}, .01, 10, 5, None, 1, kw['model'], 'success')
    put(db, ai_mode='local_claude')
    with pytest.raises(EscalationExhausted):
        await Router(db, None, runner(db, claude=Low())).route('eligibility', MSGS, SCHEMA, confidence_threshold=.95)
    assert db.execute('SELECT status FROM agent_runs').fetchone()[0] == 'failed'


def test_telemetry_uses_ist_usage_and_excludes_released_reservations(authed, db):
    day = today_ist().isoformat()
    r = budget.reserve(db, 'coding')
    budget.commit(db, r, cost_usd=.1234, model='codex:default', input_tokens=20, output_tokens=10)
    r = budget.reserve(db, 'coding')
    budget.release(db, r)
    control = authed.get('/api/ai/control')
    assert control.status_code == 200, control.text
    d = control.json()
    assert len(d['modes']) == 9
    assert d['today']['codex']['calls'] == d['month']['codex']['calls'] == 1
    assert d['today']['codex']['estimated_cost_usd'] == .1234
    assert d['budget']['date_ist'] == day
    assert all(p['account_quota'] is None for p in d['providers'])
    assert authed.get('/api/ai/plan?workflow=coding').json()['preview'] is True
    assert authed.get('/api/ai/plan?workflow=unknown').status_code == 422
    assert authed.get('/api/ai/runs?limit=201').status_code == 422


async def test_history_exposes_provenance_without_prompt_or_output(authed, db):
    put(db, ai_mode='local_codex')
    await Router(db, None, runner(db)).route('summarizer', MSGS, SCHEMA)
    out = authed.get('/api/ai/runs').json()
    assert out['total'] == 1
    item = out['items'][0]
    assert item['execution'] == 'cloud' and item['ai_mode'] == 'local_codex'
    assert item['estimated_cost_usd'] == .01
    assert 'output_json' not in item and 'prompt' not in item
    assert authed.get('/api/ai/runs?task_id=not-a-task').json()['total'] == 0


def test_control_requires_authentication(client):
    for path in ('/api/ai/control', '/api/ai/runs', '/api/ai/plan'):
        assert client.get(path).status_code == 401


def test_capability_ranking_and_recommendations_do_not_enable_disabled_providers(db):
    s = get_settings(db)
    assert policy.cloud_order(s, 'coding')[0] == 'codex'
    assert policy.cloud_order(s, 'polish.final')[0] == 'claude'
    assert policy.cloud_order(s, 'external_reasoning')[0] == 'xai'
    put(db, ai_mode='local', claude_state={'providers': {'claude': {'available': True}}})
    assert policy.recommendation(get_settings(db))['mode'] == 'local'
