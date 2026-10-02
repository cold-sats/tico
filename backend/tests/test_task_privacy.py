"""Two-party privacy, transparency, defaults and conservative upgrade boundaries."""
import json

import pytest

from backend import hubdb as H
from backend.tests.test_tasks_board import api, bot_token, get, headers, post


@pytest.mark.parametrize('requester,owner', [
    ('human:ben', 'human:priya'), ('human:ben', 'bot:cpo'),
    ('bot:ops', 'human:priya'), ('bot:ops', 'bot:cpo')])
def test_private_two_party_matrix(api, requester, owner):
    tokens = {'human:ana': 'ana-test', 'human:ben': 'ben-test', 'human:priya': 'priya-test',
              **{'bot:' + slug: bot_token(api, slug) for slug in ('ops', 'cpo', 'cmo')}}
    with api.app.state.store.transaction() as c:
        task = H.task_create(c, requester, 'Review the sensitive packet', 'Sensitive packet.', owner,
                             private=True, lint=False)
        H.type_update(c, H.KEEPER, task['type_id'], bots='work')
        c.execute('INSERT INTO task_delegations(task_id,delegate,requested_by,message_id,expires) '
                  'VALUES(?,?,?,?,?)', (task['id'], 'bot:cmo', requester, None, H.shift(H.now(), hours=24)))
    for actor, token in tokens.items():
        response = api.get('/api/v2/tasks/' + task['id'], headers=headers(token))
        assert response.status_code == (200 if actor in (requester, owner) else 404), response.text
        listed = get(api, 'tasks', token=token)['tasks']
        assert (task['id'] in {row['id'] for row in listed}) == (actor in (requester, owner))
        response = api.post('/api/v2/sql', json={'sql': 'SELECT id,title FROM tasks'}, headers=headers(token))
        assert response.status_code == 200, response.text
        assert ('Sensitive packet' in response.text or task['id'] in response.text) == (actor in (requester, owner))


def test_company_read_does_not_grant_work_but_dev_type_does(api):
    token = bot_token(api, 'ops')
    task = post(api, 'tasks', {'owner': 'cpo', 'title': 'Build the board adapter', 'body': 'Implement the adapter.'})
    assert not task['private']
    assert get(api, 'tasks/' + task['id'], token=token)['task']['id'] == task['id']
    post(api, 'tasks/' + task['id'], {'version': task['version'], 'owner': 'ops'}, token=token, expected=403)
    typ = post(api, 'task-types', {'name': 'Dev', 'bots': 'work', 'steps': [
        {'name': 'Todo', 'status': 'open'}, {'name': 'PR Review', 'status': 'review'}]})['type']
    task = post(api, 'tasks/' + task['id'], {'version': task['version'], 'type': typ['id']})
    found = get(api, 'tasks?type=' + typ['id'], token=token)['tasks']
    assert task['id'] in {row['id'] for row in found}
    post(api, 'tasks/' + task['id'] + '/links', {'url': 'https://github.com/acme/example/pull/7'}, token=token)
    task = get(api, 'tasks/' + task['id'], token=token)['task']
    task = post(api, 'tasks/' + task['id'], {'version': task['version'], 'step': 'PR Review'}, token=token)
    assert task['status'] == 'review'
    task = post(api, 'tasks/' + task['id'], {'version': task['version'], 'private': True})
    get(api, 'tasks/' + task['id'], token=token, expected=404)


def test_private_defaults_reassignment_and_human_publication(api):
    ops = bot_token(api, 'ops')
    cpo = bot_token(api, 'cpo')
    with api.app.state.store.transaction() as c:
        config = json.loads(c.execute("SELECT config_json FROM bot_config WHERE bot='ops'").fetchone()[0])
        config['private_tasks_default'] = True
        c.execute("UPDATE bot_config SET config_json=? WHERE bot='ops'", (json.dumps(config),))
    assigned = post(api, 'tasks', {'owner': 'ops', 'title': 'Review the request', 'body': 'Review it.', 'private': False})
    created = post(api, 'tasks', {'owner': 'cpo', 'title': 'Draft the response', 'body': 'Draft it.'}, token=ops)
    assert assigned['private'] and created['private']
    post(api, 'tasks/' + assigned['id'], {'version': assigned['version'], 'private': False}, token=ops, expected=422)
    changed = post(api, 'tasks/' + assigned['id'], {'version': assigned['version'], 'owner': 'cpo'})
    assert changed['private']
    get(api, 'tasks/' + assigned['id'], token=ops, expected=404)
    assert get(api, 'tasks/' + assigned['id'], token=cpo)['task']['private']
    published = post(api, 'tasks/' + assigned['id'], {'version': changed['version'], 'private': False})
    assert not published['private']
    assert get(api, 'tasks/' + assigned['id'], token=ops)['task']['id'] == assigned['id']
    post(api, 'tasks/' + created['id'], {'version': created['version'], 'private': False}, token=cpo, expected=422)


def test_private_parent_has_no_ancestry_bypass_and_requires_detachment(api):
    parent = post(api, 'tasks', {'owner': 'ben', 'title': 'Review the packet', 'body': 'Review it.', 'private': True})
    child = post(api, 'tasks', {'owner': 'priya', 'title': 'Check the packet', 'body': 'Check it.',
                               'parent_id': parent['id']}, token='ben-test')
    assert child['private'] and child['requester'] == 'human:ben'
    get(api, 'tasks/' + child['id'], expected=404)
    detail = get(api, 'tasks/' + parent['id'])
    assert not detail['children'] and detail['task']['parts']['total'] == 0
    post(api, 'tasks/' + child['id'], {'version': child['version'], 'private': False}, token='ben-test', expected=422)
    published = post(api, 'tasks/' + child['id'], {'version': child['version'], 'private': False, 'parent_id': ''}, token='ben-test')
    assert not published['private'] and published['parent_id'] is None


def test_cached_comment_response_cannot_bypass_reassignment(api):
    task = post(api, 'tasks', {'owner': 'ben', 'title': 'Review the private draft', 'body': 'Review it.', 'private': True})
    replay_headers = headers('ben-test')
    url = '/api/v2/tasks/' + task['id'] + '/comments'
    first = api.post(url, json={'text': 'Sensitive response.'}, headers=replay_headers)
    assert first.status_code == 200, first.text
    task = get(api, 'tasks/' + task['id'])['task']
    post(api, 'tasks/' + task['id'], {'version': task['version'], 'owner': 'priya'})
    response = api.post(url, json={'text': 'Sensitive response.'}, headers=replay_headers)
    assert response.status_code == 404 and 'Sensitive response.' not in response.text


def test_cloud_upgrade_keeps_legacy_tasks_private_and_files_intact(api):
    task = post(api, 'tasks', {'owner': 'cpo', 'title': 'Review the older work', 'body': 'Older content.'})
    post(api, 'tasks/' + task['id'] + '/files', {'name': 'legacy-brief.md', 'text': 'Legacy attachment bytes.'})
    with api.app.state.store.transaction() as c:
        counts = {name: c.execute('SELECT count(*) FROM ' + name).fetchone()[0]
                  for name in ('tasks', 'blobs', 'task_assets', 'bot_files')}
        c.execute('ALTER TABLE tasks DROP COLUMN private')
        c.execute('DELETE FROM cloud_migrations WHERE version=57')
    api.app.state.store.initialize(seed_market=False)
    with api.app.state.store.read() as c:
        assert H.task(c, task['id'])['private'] == 1
        assert c.execute('SELECT 1 FROM cloud_migrations WHERE version=57').fetchone()
        assert all(c.execute('SELECT count(*) FROM ' + name).fetchone()[0] == count for name, count in counts.items())
        assert c.execute('SELECT 1 FROM cloud_migrations WHERE version=53').fetchone()
    api.app.state.store.initialize(seed_market=False)
    assert get(api, 'tasks/' + task['id'])['task']['private']
