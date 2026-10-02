"""Phase 3 API contracts; temporary schema fixture replaced by tasks' v2 migration at merge."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend import hubdb as H
from backend.tests.test_github_app import api, gh, auth, connect, runner_token  # noqa: F401
from backend.tests.test_repositories import catalog, put


@pytest.fixture
def prepared(api, gh):
    catalog(api, gh)
    runner_token(api, 'cmo')
    put(api, 'repositories/Acme/product', {'enabled': True})
    put(api, 'bots/cmo/repositories', {'mode': 'all'})
    with api.app_state.store.transaction() as c:
        # TEMPORARY: task_links v2 is owned by the tasks engineer. Drop this block at merge.
        columns = {'repo': 'TEXT', 'number': 'INTEGER', 'branch': 'TEXT', 'computer_id': 'TEXT', 'path': 'TEXT',
                   'checks': 'TEXT', 'mergeable': 'TEXT', 'review_state': 'TEXT', 'pending_comments': 'INTEGER',
                   'detail_json': 'TEXT', 'updated': 'TEXT'}
        have = {r[1] for r in c.execute('PRAGMA table_info(task_links)')}
        for name, kind in columns.items():
            if name not in have:
                c.execute(f'ALTER TABLE task_links ADD COLUMN {name} {kind}')
        c.execute("UPDATE runners SET readiness_json=? WHERE id='r1'", (json.dumps({'schema_version': 1, 'bots': {}, 'worktrees': True}),))
        task = H.task_create(c, 'human:ana', 'Build product', 'Implement product', 'bot:cmo')
        other = H.task_create(c, 'human:ana', 'Other work', 'Implement docs', 'bot:cpo')
        until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        c.execute("INSERT INTO messages(id,from_actor,to_actor,kind,body,created) VALUES('m1','human:ana','bot:cmo','say','Work',?)", (H.now(),))
        job = c.execute("SELECT id FROM jobs WHERE message_id='m1'").fetchone()[0]
        c.execute("INSERT INTO attempts(id,job_id,bot,runner_id,generation,token_hash,state,lease_until,created) VALUES('a1',?,'cmo','r1',1,'synthetic','running',?,?)", (job, until, H.now()))
    return api, task['id'], other['id']


def post(api, path, body, token='owner-test'):
    return api.post('/api/v2/' + path, json=body, headers={**auth(token), 'Idempotency-Key': uuid.uuid4().hex})


def test_create_permissions_limit_old_computer_and_attach(prepared):
    api, tid, other = prepared
    path = f'tasks/{tid}/worktrees'
    assert post(api, f'tasks/{other}/worktrees', {'repo': 'Acme/product'}, 'bot-test').status_code == 403
    put(api, 'bots/cmo/repositories', {'mode': 'all', 'all_access': 'read'})
    assert post(api, path, {'repo': 'Acme/product'}).status_code == 403
    put(api, 'bots/cmo/repositories', {'mode': 'all', 'all_access': 'write'})
    with api.app_state.store.transaction() as c:
        c.execute("UPDATE runners SET readiness_json='{}' WHERE id='r1'")
    response = post(api, path, {'repo': 'Acme/product'})
    assert response.status_code == 409 and 'Update this computer' in response.text
    with api.app_state.store.transaction() as c:
        c.execute("UPDATE runners SET readiness_json=? WHERE id='r1'", (json.dumps({'schema_version': 1, 'bots': {}, 'worktrees': True}),))
    response = post(api, path, {'repo': 'Acme/product'}, 'bot-test')
    assert response.status_code == 200, response.text
    link = response.json()
    assert link['path'] == f'tasks/{tid[:8]}/Acme__product'
    assert link['branch'].startswith('tico/' + tid[:8])
    assert post(api, path, {'repo': 'Acme/product'}, 'bot-test').json() == link
    for i in range(9):
        response = post(api, f'tasks/{tid}/worktrees/attach', {'path': f'tasks/{tid[:8]}/extra{i}', 'repo': 'Acme/product'}, 'bot-test')
        assert response.status_code == 200, response.text
    assert post(api, f'tasks/{tid}/worktrees/attach', {'path': 'tasks/eleven', 'repo': 'Acme/product'}, 'bot-test').status_code == 409
    assert post(api, f'tasks/{tid}/worktrees/attach', {'path': '../escape', 'repo': 'Acme/product'}, 'bot-test').status_code == 422
    response = api.patch(f'/api/v2/tasks/{tid}/links/{link["link_id"]}', json={'state': 'present', 'computer_id': 'elsewhere'}, headers={**auth('runner-test'), 'Idempotency-Key': uuid.uuid4().hex})
    assert response.status_code == 403


def test_heartbeat_cleanup_waits_for_prs_restore_and_old_report(prepared):
    api, tid, _ = prepared
    link = post(api, f'tasks/{tid}/worktrees', {'repo': 'Acme/product'}).json()
    body = {'version': '0.3.2', 'platform': 'linux', 'readiness': {'schema_version': 1, 'bots': {}, 'worktrees': True},
            'worktrees': [{'link_id': link['link_id'], 'state': 'present', 'branch': link['branch'], 'ahead': 2, 'dirty_files': 1, 'last_commit': 'abc'}]}
    response = post(api, 'runners/heartbeat', body, 'runner-test')
    assert response.status_code == 200, response.text
    assert response.json()['worktree_actions'] == []
    with api.app_state.store.transaction() as c:
        row = c.execute('SELECT * FROM task_links WHERE id=?', (link['link_id'],)).fetchone()
        assert row['state'] == 'present' and json.loads(row['detail_json'])['ahead'] == 2
        H.task_link(c, 'bot:cmo', tid, 'https://github.com/Acme/product/pull/1')
        c.execute("UPDATE task_links SET state='open' WHERE kind='pr'")
        c.execute("UPDATE tasks SET status='closed' WHERE id=?", (tid,))
    assert post(api, 'runners/heartbeat', body, 'runner-test').json()['worktree_actions'] == []
    with api.app_state.store.transaction() as c:
        c.execute("UPDATE task_links SET state='merged' WHERE kind='pr'")
    actions = post(api, 'runners/heartbeat', body, 'runner-test').json()['worktree_actions']
    assert len(actions) == 1 and actions[0]['action'] == 'remove'
    body['worktrees'][0]['state'] = 'removed'
    assert post(api, 'runners/heartbeat', body, 'runner-test').json()['worktree_actions'] == []
    with api.app_state.store.transaction() as c:
        c.execute("UPDATE tasks SET status='open' WHERE id=?", (tid,))
    assert post(api, 'runners/heartbeat', body, 'runner-test').json()['worktree_actions'][0]['action'] == 'restore'
    body.pop('worktrees')
    body['readiness'].pop('worktrees')
    assert post(api, 'runners/heartbeat', body, 'runner-test').json()['worktree_actions'] == []


def test_archived_cleanup_token_is_repository_scoped_and_stale_wakes_once(prepared, gh):
    api, tid, _ = prepared
    link = post(api, f'tasks/{tid}/worktrees', {'repo': 'Acme/product'}).json()
    body = {'version': '0.3.2', 'platform': 'linux', 'readiness': {'schema_version': 1, 'worktrees': True},
            'worktrees': [{'link_id': link['link_id'], 'state': 'missing'}]}
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    with api.app_state.store.transaction() as c:
        c.execute('UPDATE task_links SET detail_json=? WHERE id=?', (json.dumps({'missing_since': old}), link['link_id']))
    for _ in range(2):
        assert post(api, 'runners/heartbeat', body, 'runner-test').status_code == 200
    with api.app_state.store.transaction() as c:
        assert c.execute("SELECT count(*) FROM messages WHERE body LIKE 'Worktree missing for a day:%'").fetchone()[0] == 1
        c.execute("UPDATE bots SET state='archived' WHERE slug='cmo'")
        c.execute("DELETE FROM assignments WHERE bot='cmo'")
    token_path = 'runners/me/worktrees/' + link['link_id'] + '/token'
    response = post(api, token_path, {}, 'runner-test')
    assert response.status_code == 200, response.text
    assert gh.of('/access_tokens')[-1][2] == {'repositories': ['product'], 'permissions': {'contents': 'write', 'metadata': 'read'}}
    put(api, 'bots/cmo/repositories', {'mode': 'own'})
    assert post(api, token_path, {}, 'runner-test').status_code == 403


def test_attached_worktree_branch_follows_computer_report(prepared):
    api, tid, _ = prepared
    response = post(api, f'tasks/{tid}/worktrees/attach', {'path': 'custom/any-folder'}, 'bot-test')
    assert response.status_code == 200, response.text
    link = response.json()
    body = {'version': '0.3.2', 'platform': 'linux', 'readiness': {'schema_version': 1, 'worktrees': True},
            'worktrees': [{'link_id': link['link_id'], 'state': 'present', 'branch': 'feature/custom', 'repo': 'Acme/product'}]}
    assert post(api, 'runners/heartbeat', body, 'runner-test').status_code == 200
    with api.app_state.store.read() as c:
        row = c.execute('SELECT * FROM task_links WHERE id=?', (link['link_id'],)).fetchone()
        assert row['branch'] == 'feature/custom' and row['repo'] == 'Acme/product'


def test_human_request_is_created_on_next_computer_heartbeat(prepared):
    api, tid, _ = prepared
    link = post(api, f'tasks/{tid}/worktrees', {'repo': 'Acme/product'}).json()
    body = {'version': '0.3.2', 'platform': 'linux', 'readiness': {'schema_version': 1, 'worktrees': True},
            'worktrees': [{'link_id': link['link_id'], 'state': 'missing'}]}
    response = post(api, 'runners/heartbeat', body, 'runner-test')
    assert response.status_code == 200, response.text
    assert response.json()['worktree_actions'][0]['action'] == 'restore'
