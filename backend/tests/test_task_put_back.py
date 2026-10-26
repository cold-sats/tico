"""Owners can return work to the queue without an immediate automatic restart."""
import pytest

from backend import auto_tasks
from backend.store import H
from backend.tests.test_api import api, get, post  # noqa: F401
from backend.tests.test_auto_tasks import deck, take
from backend.tests.test_task_lanes import task_bot


def update(api, task, token, status, note=None, expected=200):
    version = get(api, 'tasks/' + task['id'])['task']['version']
    return post(api, 'tasks/' + task['id'], {'version': version, 'status': status,
                **({'note': note} if note is not None else {})}, token, expected=expected)


def settle(api, machine, attempt):
    post(api, f"attempts/{attempt['id']}/started", {'thread_id': attempt['lane']}, machine['token'])
    post(api, f"attempts/{attempt['id']}/complete", {'outcome': 'completed', 'last_seq': 0}, machine['token'])


def test_owner_put_back_requires_note_and_holds_queued_and_missing_starts_for_an_hour(api, monkeypatch):
    machine = task_bot(api, lanes=True)
    [task] = deck(api, 1)
    attempt = take(api, machine)
    update(api, task, attempt['token'], 'open', expected=422)
    update(api, task, attempt['token'], 'open', '   ', expected=422)
    result = update(api, task, attempt['token'], 'open', 'Wait until the next work slot.')
    assert result['status'] == 'open' and result['step']['name'] == 'On Deck'
    settle(api, machine, attempt)
    with api.app.state.store.transaction() as c:
        row = H.task(c, task['id'])
        returned = H.now()
        # Both a retained notice and the idle claim's missing-job path must obey the hold.
        H._wake(c, row, row['owner'], 'Start assigned task', {'auto_start': True})
    monkeypatch.setattr(H, 'now', lambda: H.shift(returned, minutes=59))
    with api.app.state.store.transaction() as c:
        c.execute('UPDATE runners SET last_seen=?', (H.now(),))
    assert take(api, machine) is None
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE jobs SET state='cancelled' WHERE state='queued'")
    assert take(api, machine) is None
    monkeypatch.setattr(H, 'now', lambda: H.shift(returned, minutes=60))
    with api.app.state.store.transaction() as c:
        c.execute('UPDATE runners SET last_seen=?', (H.now(),))
    assert take(api, machine)['task']['id'] == task['id']


@pytest.mark.parametrize('status', ['open', 'doing'])
def test_owner_reopens_done_and_preserves_human_closure(api, status):
    machine = task_bot(api, lanes=True)
    [task] = deck(api, 1)
    attempt = take(api, machine)
    update(api, task, attempt['token'], 'done', 'Delivered the requested change.')
    result = update(api, task, attempt['token'], status, 'More work remains.')
    assert result['status'] == status and result['done_at'] is None
    post(api, 'tasks/' + task['id'], {'version': result['version'], 'close': True})
    result = update(api, task, attempt['token'], status, 'More work remains.', expected=403)
    assert 'file a new task' in result['error']['detail']
    assert get(api, 'tasks/' + task['id'])['task']['status'] == 'closed'


@pytest.mark.parametrize('change', ['comment', 'link', 'blocker_done'])
def test_substantive_changes_release_the_put_back_hold(api, change):
    machine = task_bot(api, lanes=True)
    [task] = deck(api, 1)
    blocker = post(api, 'tasks', {'owner': 'ana', 'title': 'Supply the prerequisite', 'body': 'Supply it.'})
    attempt = take(api, machine)
    if change == 'blocker_done':
        # An explicit working move means linking the blocker does not auto-return it first.
        update(api, task, attempt['token'], 'waiting', 'Waiting for a prerequisite.')
        update(api, task, attempt['token'], 'doing')
        post(api, 'tasks/' + task['id'] + '/relations', {'kind': 'blocked_by', 'task': blocker['id']})
    update(api, task, attempt['token'], 'open', 'Ready for a later work slot.')
    settle(api, machine, attempt)
    assert take(api, machine) is None
    if change == 'comment':
        post(api, 'tasks/' + task['id'] + '/comments', {'text': 'The inputs are ready.'})
    elif change == 'link':
        post(api, 'tasks/' + task['id'] + '/links', {'url': 'https://acme.example/inputs'})
    else:
        update(api, blocker, 'ana-test', 'done')
    with api.app.state.store.read() as c:
        assert not auto_tasks.put_back_held(c, H.task(c, task['id']))
    assert take(api, machine)['task']['id'] == task['id']


def test_linking_a_blocker_reverses_only_an_automatic_start_before_a_finished_run(api):
    machine = task_bot(api, lanes=True)
    tasks = deck(api, 3)
    attempts = [take(api, machine) for _ in tasks]
    by_task = {a['task']['id']: a for a in attempts}
    # A completed run and an explicit owner move each protect their working state.
    settle(api, machine, by_task[tasks[0]['id']])
    update(api, tasks[1], by_task[tasks[1]['id']]['token'], 'waiting', 'Waiting for input.')
    update(api, tasks[1], by_task[tasks[1]['id']]['token'], 'doing')
    blocker = post(api, 'tasks', {'owner': 'ana', 'title': 'Finish prerequisite', 'body': 'Finish it.'})
    with api.app.state.store.read() as c:
        jobs = c.execute('SELECT count(*) FROM jobs').fetchone()[0]
        turns = c.execute('SELECT count(*) FROM turns').fetchone()[0]
    for task in tasks:
        post(api, 'tasks/' + task['id'] + '/relations', {'kind': 'blocked_by', 'task': blocker['id']})
    rows = [get(api, 'tasks/' + t['id'])['task'] for t in tasks]
    assert [t['status'] for t in rows] == ['doing', 'doing', 'open']
    assert rows[2]['step']['name'] == 'On Deck'
    with api.app.state.store.read() as c:
        assert c.execute('SELECT count(*) FROM jobs').fetchone()[0] == jobs
        assert c.execute('SELECT count(*) FROM turns').fetchone()[0] == turns
        assert auto_tasks.waiting(c, H.task(c, tasks[2]['id']))


def test_done_task_question_refusal_gives_owner_command_and_nonowner_route(api):
    machine = task_bot(api, lanes=True)
    [task] = deck(api, 1)
    attempt = take(api, machine)
    update(api, task, attempt['token'], 'done', 'Finished the requested change.')
    result = post(api, 'tasks/' + task['id'] + '/ask', {'text': 'Which date should I use?'},
                  attempt['token'], expected=422)
    assert f"hub task update {task['id']} --status doing" in result['error']['detail']
    assert 'or file a new task' in result['error']['detail']
    with api.app.state.store.transaction() as c:
        other = H.task_create(c, 'human:ana', 'Another owners task', 'Leave with its owner.', 'bot:finance', lint=False)
        with pytest.raises(H.Refused) as refused:
            H.task_update(c, 'bot:ops', other['id'], status='open', note='Put back.')
        assert 'ask the owner' in refused.value.detail.lower()
        assert 'file a new task' in refused.value.detail


def test_dev_return_prefers_on_deck_over_backlog_and_owner_can_reopen_steps_only_done(api):
    machine = task_bot(api, lanes=True)
    typ = post(api, 'task-types', {'name': 'Dev tickets', 'steps_only': True, 'steps': [
        {'name': 'Backlog', 'status': 'open'}, {'name': 'On Deck', 'status': 'open'},
        {'name': 'In Progress', 'status': 'doing'}, {'name': 'Done', 'status': 'done'}]})['type']
    task = post(api, 'tasks', {'owner': 'ops', 'title': 'Build requested feature',
                             'body': 'Build the requested feature.', 'type': typ['id'], 'step': 'On Deck'})
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE jobs SET state='cancelled'")
    attempt = take(api, machine)
    result = update(api, task, attempt['token'], 'open', 'Defer until inputs are ready.')
    assert result['step']['name'] == 'On Deck'
    result = post(api, 'tasks/' + task['id'], {'version': result['version'], 'step': 'Done'}, attempt['token'])
    result = update(api, task, attempt['token'], 'doing')
    assert result['step']['name'] == 'In Progress' and result['done_at'] is None
    result = post(api, 'tasks/' + task['id'], {'version': result['version'], 'step': 'Done'}, attempt['token'])
    result = update(api, task, attempt['token'], 'open', 'Another input arrived.')
    assert result['step']['name'] == 'On Deck' and result['done_at'] is None
