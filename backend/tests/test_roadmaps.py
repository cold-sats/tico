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
