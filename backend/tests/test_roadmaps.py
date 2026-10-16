"""Roadmap privacy boundaries and the existing parent/child flow."""

from backend import hubdb as H
from backend.tests.test_tasks_board import api, get, post


def test_engineering_children_drive_approved_roadmap_and_reopen(api):
    roadmap = post(api, 'tasks', {'owner': 'cpo', 'title': 'Improve exports', 'body': 'Research exports.',
                                 'type': 'Product roadmap', 'step': 'Approved'})
    child = post(api, 'tasks', {'owner': 'ops', 'title': 'Build exports', 'body': 'Implement exports.',
                               'type': 'Engineering', 'relations': [{'task': roadmap['id'], 'kind': 'parent'}]})
    assert get(api, 'tasks/' + roadmap['id'])['task']['step']['name'] == 'Building'
    child = post(api, 'tasks/' + child['id'], {'version': child['version'], 'status': 'done'})
    assert get(api, 'tasks/' + roadmap['id'])['task']['step']['name'] == 'Shipped'
    post(api, 'tasks/' + child['id'], {'version': child['version'], 'status': 'open'})
    assert get(api, 'tasks/' + roadmap['id'])['task']['step']['name'] == 'Building'


def test_visibility_defaults_do_not_rewrite_tasks_and_private_never_publishes(api):
    task = post(api, 'tasks', {'owner': 'cpo', 'title': 'Research search', 'body': 'Internal draft',
                              'type': 'Product roadmap'})
    assert task['visibility'] == 'public' and task['public_summary'] == 'Internal draft'
    post(api, 'task-types/product-roadmap', {'default_visibility': 'private'})
    task = get(api, 'tasks/' + task['id'])['task']
    assert task['visibility'] == 'public'
    changed = post(api, 'tasks/' + task['id'], {'version': task['version'], 'body': 'Internal revision'})
    assert changed['public_summary'] == 'Internal draft'
    private = post(api, 'tasks', {'owner': 'cpo', 'title': 'Sensitive research', 'body': 'Secret',
                                 'type': 'Product roadmap', 'private': True})
    post(api, 'tasks/' + private['id'], {'version': private['version'], 'visibility': 'public'}, expected=422)


def test_bot_public_text_and_comment_need_exact_single_use_approval(api):
    from backend.tests.test_tasks_board import bot_token
    token = bot_token(api, 'cpo')
    task = post(api, 'tasks', {'owner': 'cpo', 'title': 'Improve search', 'body': 'Draft', 'type': 'Product roadmap'})
    changes = {'public_summary': 'Search improvements'}
    post(api, 'tasks/' + task['id'], {'version': task['version'], **changes}, token=token, expected=422)
    preview = post(api, 'tasks/' + task['id'] + '/publication-preview', changes, token=token)
    approval = post(api, 'approvals', {'kind': 'publish', 'task_id': task['id'], 'payload': preview['payload']}, token=token)
    post(api, 'approvals/' + approval['id'], {'decision': 'approved'})
    task = post(api, 'tasks/' + task['id'], {'version': task['version'], **changes, 'approval_id': approval['id']}, token=token)
    assert task['public_summary'] == changes['public_summary']
    post(api, 'tasks/' + task['id'] + '/comments', {'text': 'Now available', 'public': True}, token=token, expected=422)
    preview = post(api, 'tasks/' + task['id'] + '/publication-preview', {'comment': 'Now available'}, token=token)
    approval = post(api, 'approvals', {'kind': 'publish', 'task_id': task['id'], 'payload': preview['payload']}, token=token)
    post(api, 'approvals/' + approval['id'], {'decision': 'approved'})
    result = post(api, 'tasks/' + task['id'] + '/comments', {'text': 'Now available', 'public': True,
                                                        'approval_id': approval['id']}, token=token)
    assert result['comment']['public'] == 1
    post(api, 'tasks/' + task['id'] + '/comments', {'text': 'Now available', 'public': True,
                                                'approval_id': approval['id']}, token=token, expected=422)


def public_setup(api, limit=10):
    post(api, 'tags', {'key': 'roadmap'})
    post(api, 'tags', {'key': 'internal'})
    post(api, 'roadmaps/settings', {'labels': ['roadmap'], 'cors_origins': ['https://acme.example'],
                                  'action_limit': limit})
    return post(api, 'tasks', {'owner': 'cpo', 'title': 'Internal title', 'body': 'Internal summary',
                               'type': 'Product roadmap', 'labels': ['roadmap']})


ORIGIN = {'Origin': 'https://acme.example'}


def test_public_projection_moderation_and_no_label_enumeration(api):
    task = public_setup(api)
    task = post(api, 'tasks/' + task['id'], {'version': task['version'], 'public_title': 'Search',
                                          'public_summary': 'Find things faster'})
    post(api, 'tasks/' + task['id'] + '/comments', {'text': 'Internal discussion'})
    public = post(api, 'tasks/' + task['id'] + '/comments', {'text': 'Team update', 'public': True})['comment']
    post(api, 'tasks/' + task['id'] + '/requesters', {'email': 'private@acme.example', 'name': 'Private Name'})
    child = post(api, 'tasks', {'owner': 'cpo', 'title': 'Secret child', 'body': 'Internal work',
                              'visibility': 'public', 'labels': ['roadmap'],
                              'relations': [{'task': task['id'], 'kind': 'parent'}]})
    path = '/public/roadmaps/roadmap/tasks/' + task['id']
    response = api.get(path, headers=ORIGIN)
    assert response.status_code == 200, response.text
    result = response.json()
    assert set(result['task']) == {'id', 'title', 'summary', 'step', 'requester_count', 'parts'}
    assert result['task']['title'] == 'Search' and result['task']['requester_count'] == 1
    assert result['comments'][0]['author'] == 'Team'
    assert all(secret not in response.text for secret in ('private@', 'Private Name', 'Internal', 'Secret child', child['id']))
    assert len(api.get('/public/roadmaps/roadmap', headers=ORIGIN).json()['tasks']) == 1
    assert api.get('/public/roadmaps/internal', headers=ORIGIN).status_code == 404
    post(api, 'tasks/' + task['id'] + '/comments/' + public['id'] + '/moderate', {'action': 'hide'})
    assert api.get(path, headers=ORIGIN).json()['comments'] == []
    post(api, 'tasks/' + task['id'] + '/comments/' + public['id'] + '/moderate', {'action': 'show'})
    assert len(api.get(path, headers=ORIGIN).json()['comments']) == 1
    post(api, 'tasks/' + task['id'], {'version': task['version'], 'visibility': 'private'})
    assert api.get(path, headers=ORIGIN).status_code == 404


def test_cors_and_ip_limit_shared_across_actions_and_tokens_are_task_bound(api):
    task = public_setup(api, limit=4)
    base = '/public/roadmaps/roadmap/tasks/' + task['id']
    assert api.get(base).status_code == 403
    assert api.post(base + '/requesters', json={}, headers={'Origin': 'https://evil.example'}).status_code == 403
    preflight = api.options(base + '/requesters', headers={**ORIGIN, 'Access-Control-Request-Method': 'POST',
                                                         'Access-Control-Request-Headers': 'Content-Type'})
    assert preflight.status_code == 204 and preflight.headers['access-control-allow-origin'] == ORIGIN['Origin']
    assert 'access-control-allow-credentials' not in preflight.headers
    token = api.post(base + '/requesters', json={'email': 'customer@acme.example'}, headers=ORIGIN).json()['requester_token']
    other = post(api, 'tasks', {'owner': 'cpo', 'title': 'Other', 'body': 'Research it', 'type': 'Product roadmap', 'labels': ['roadmap']})
    assert api.delete('/public/roadmaps/roadmap/tasks/' + other['id'] + '/requesters/' + token, headers=ORIGIN).status_code == 404
    with api.app.state.store.read() as c:
        assert c.execute('SELECT token_hash FROM task_requesters').fetchone()[0] != token
    assert api.post(base + '/comments', json={'text': 'Please add this'}, headers=ORIGIN).status_code == 200
    assert api.delete(base + '/requesters/' + token, headers=ORIGIN).status_code == 200
    assert api.delete(base + '/requesters/' + token, headers=ORIGIN).status_code == 404
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bot_config SET config_json=json_set(config_json,'$.template','product-manager') WHERE bot='cpo'")
    suggested = api.post('/public/roadmaps/roadmap/suggest', json={'title': 'New idea', 'summary': 'Details'}, headers=ORIGIN)
    assert suggested.status_code == 200, suggested.text
    with api.app.state.store.read() as c:
        row = H.task(c, suggested.json()['id'])
        assert row['visibility'] == 'private'
    assert api.post(base + '/requesters', json={}, headers=ORIGIN).status_code == 429
    post(api, 'roadmaps/settings', {'labels': ['roadmap'], 'cors_origins': ['*']}, expected=422)
