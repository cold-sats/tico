"""Blocked work has one state across gates, dependencies, clocks and the board."""
import json

import pytest

from backend import hubdb as H
from backend.tests.test_review_gate import api, ticket, move, HEAD, get
from backend.tests.test_github import post


def test_blocked_step_survives_restart_and_is_before_work(api):
    task = ticket(api)
    with api.app.state.store.transaction() as c:
        typ = H.type_get(c, task['type_id'])
        assert [s['name'] for s in typ['steps']][:2] == ['Blocked', 'In Progress']
        H.migrate(c)
        assert H.type_get(c, typ['id'])['steps'] == typ['steps']


def test_owner_block_keeps_reason_time_and_resume_step(api):
    task = ticket(api)
    with api.app.state.store.transaction() as c:
        H.task_update(c, task['owner'], task['id'], step='Blocked', note='Waiting for the test machine')
        blocked = H.task(c, task['id'])
        assert blocked['status'] == 'waiting'
        assert blocked['blocked_reason'] == 'Waiting for the test machine'
        assert blocked['blocked_since']
        H.task_update(c, task['owner'], task['id'], note='Still waiting')
        assert H.task(c, task['id'])['blocked_since'] == blocked['blocked_since']
        H.task_update(c, task['owner'], task['id'], status='doing')
        resumed = H.task(c, task['id'])
        assert resumed['step_id'] == task['step_id']
        assert resumed['blocked_since'] is None


def test_gate_refusal_commits_block_without_advancing_review(api):
    task = ticket(api)
    assert move(api, task).status_code == 422
    current = get(api, 'tasks/' + task['id'])['task']
    assert current['step']['name'] == 'Blocked'
    assert current['status'] == 'waiting'
    assert 'receipt' in current['blocked_reason']
    assert current['version'] > task['version']
    with api.app.state.store.transaction() as c:
        from backend import task_blocked
        H.task_update(c, task['owner'], task['id'], note=f'Tests: head {HEAD}: 9 passed, 0 failed')
        task_blocked.reconcile(c, task['id'])
        assert H.task(c, task['id'])['step_id'] == task['step_id']


def test_two_dependencies_block_until_both_clear(api):
    task = ticket(api)
    children = [post(api, 'tasks', {'owner': 'cmo', 'title': f'Prepare resource {i}', 'body': 'Prepare it.'}) for i in range(2)]
    from backend import task_relations as TR
    with api.app.state.store.transaction() as c:
        for child in children:
            TR.add_blocker(c, H.KEEPER, task['id'], child['id'])
        assert H.task(c, task['id'])['status'] == 'waiting'
        H.task_update(c, task['owner'], task['id'], step='In Progress')
        assert H.task(c, task['id'])['status'] == 'waiting', 'an explicit move cannot bypass a live dependency'
        TR.remove_blocker(c, H.KEEPER, task['id'], children[0]['id'])
        assert H.task(c, task['id'])['status'] == 'waiting'
        H.task_update(c, H.KEEPER, children[1]['id'], status='done')
        assert H.task(c, task['id'])['step_id'] == task['step_id']


def test_blocked_time_pauses_build_clock_and_age_alert_is_once(api, monkeypatch):
    task = ticket(api)
    from backend import task_blocked
    at = '2026-10-26T01:00:00.000000Z'
    monkeypatch.setattr(H, 'now', lambda: at)
    with api.app.state.store.transaction() as c:
        c.execute('UPDATE tasks SET building_started_at=? WHERE id=?', ('2026-10-26T00:00:00.000000Z', task['id']))
        H.task_update(c, task['owner'], task['id'], step='Blocked', note='Waiting for a machine')
        at = '2026-10-26T06:00:00.000000Z'
        blocked = H.task(c, task['id'])
        assert task_blocked.clocks(blocked, at)['building_seconds'] == 3600
        assert task_blocked.clocks(blocked, at)['blocked_seconds'] == 18000
        # A type manager gets one alert for this blocked episode.
        c.execute('UPDATE task_types SET manager=? WHERE id=?', ('cmo', task['type_id']))
        task_blocked.sweep(c, at)
        task_blocked.sweep(c, at)
        assert c.execute("SELECT count(*) FROM events WHERE action='task.blocked_age' AND target=?", (task['id'],)).fetchone()[0] == 1
        H.task_update(c, task['owner'], task['id'], status='doing')
        at = '2026-10-26T07:00:00.000000Z'
        assert task_blocked.clocks(H.task(c, task['id']), at)['building_seconds'] == 7200


def test_fresh_ci_refusal_cannot_be_cleared_by_older_cached_green(api):
    from backend import review_gate, task_blocked
    task = ticket(api, f'Tests: head {HEAD}: 9 passed, 0 failed')
    with api.app.state.store.transaction() as c:
        row = H.task(c, task['id'])
        pr = review_gate.links(c, row)[0]
        with pytest.raises(H.Refused) as refused:
            review_gate.check(c, row['owner'], row, {pr['id']: {
                'head_sha': HEAD, 'checks': {'python': 'failing'}, 'at': H.now()}})
        review_gate.notify(c, row['owner'], refused.value.review_gate)
        event_count = c.execute('SELECT count(*) FROM events').fetchone()[0]
        task_blocked.reconcile(c, task['id'])
        assert H.task(c, task['id'])['blocked_since']
        assert c.execute('SELECT count(*) FROM events').fetchone()[0] == event_count, 'probing never records another refusal'
        c.execute('UPDATE task_links SET updated=?,detail_json=? WHERE id=?', (
            H.shift(H.now(), seconds=1), json.dumps({'head_sha': HEAD, 'checks': {'python': 'passing'}}), pr['id']))
        task_blocked.reconcile(c, task['id'])
        assert H.task(c, task['id'])['step_id'] == task['step_id']


def test_person_dependency_resumes_the_previous_review_step(api):
    from backend import task_blocked, task_relations as TR
    task = ticket(api, f'Tests: head {HEAD}: 9 passed, 0 failed')
    assert move(api, task, 'Review 2').status_code == 200
    with api.app.state.store.transaction() as c:
        review_step = H.task(c, task['id'])['step_id']
        answer = H.task_create(c, 'human:ana', 'Choose a test machine', 'Choose a machine.', 'human:ana', parent_id=task['id'])
        TR.add_blocker(c, H.KEEPER, task['id'], answer['id'])
        blocked = H.task(c, task['id'])
        assert blocked['status'] == 'waiting' and blocked['blocked_from_step'] == review_step
        H.task_update(c, 'human:ana', answer['id'], status='done')
        task_blocked.reconcile(c, task['id'])
        assert H.task(c, task['id'])['step_id'] == review_step
        assert H.task(c, task['id'])['status'] == 'review'


def test_explicit_milestone_wait_blocks_and_resumes_without_a_task_completion(api):
    from backend import milestone_waits as MW
    task = ticket(api)
    with api.app.state.store.transaction() as c:
        MW.add(c, task['owner'], H.task(c, task['id']), 'release:acme/app@v1.2.3')
        blocked = H.task(c, task['id'])
        assert blocked['status'] == 'waiting' and blocked['blocked_since']
        MW.happened(c, 'release_published', 'acme/app@v1.2.3')
        assert H.task(c, task['id'])['step_id'] == task['step_id']
        assert H.task(c, task['id'])['blocked_since'] is None


def test_sweep_discovers_person_wait_and_keeps_private_age_alert_private(api):
    from backend import task_blocked
    task = ticket(api)
    with api.app.state.store.transaction() as c:
        answer = H.task_create(c, 'human:ana', 'Choose a machine', 'Choose one.', 'human:ana', parent_id=task['id'])
        c.execute('UPDATE tasks SET private=1 WHERE id=?', (task['id'],))
        c.execute('UPDATE task_types SET manager=? WHERE id=?', ('cmo', task['type_id']))
        task_blocked.sweep(c, H.now())
        row = H.task(c, task['id'])
        assert row['status'] == 'waiting' and row['blocked_kind'] == 'dependency'
        task_blocked.sweep(c, H.shift(row['blocked_since'], hours=5))
        assert not c.execute("SELECT 1 FROM events WHERE action='task.blocked_age' AND target=?", (task['id'],)).fetchone()
        H.task_update(c, 'human:ana', answer['id'], status='done')
        task_blocked.sweep(c, H.now())
        assert H.task(c, task['id'])['step_id'] == task['step_id']
