"""A refused review move is retried by Tico once what refused it clears (Dev 534 C, criterion 8)."""
import json

from backend import hubdb as H, move_retry
from backend.tests.test_github import api, get  # noqa: F401
from backend.tests.test_review_gate import ticket, move, HEAD, BASE

RECEIPT = f'Tests: base {BASE} head {HEAD}: 9 passed, 0 failed'


def managed(api, task):
    """The type is managed by cmo, as Dev tickets are by Head of Engineering."""
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE task_types SET manager='cmo' WHERE id=?", (task['type_id'],))


def step(api, task):
    return get(api, 'tasks/' + task['id'])['task']['step']['name']


def retries(api, task):
    with api.app.state.store.read() as c:
        return [json.loads(r[0]) for r in c.execute(
            "SELECT new FROM task_events WHERE task_id=? AND field='move_retry' ORDER BY ts, rowid", (task['id'],))]


def tick(api):
    return move_retry.tick(api.app.state.github_app, force=True)


def owned_by(api, slug):
    with api.app.state.store.read() as c:
        return [r[0] for r in c.execute("SELECT title FROM tasks WHERE owner=?", (H.bot_actor(slug),))]


def test_refused_for_missing_receipt_moves_itself_when_the_receipt_is_posted(api):
    task = ticket(api)
    managed(api, task)
    refused = move(api, task)
    assert refused.status_code == 422
    assert 'Tico retries this move itself when a passing test receipt' in refused.json()['detail']
    assert [r['step'] for r in retries(api, task)] == ['Review 1']
    # Nothing changed: no retry, no new refusal.
    assert tick(api) == [] and step(api, task) == 'In Progress'
    with api.app.state.store.transaction() as c:
        c.execute('UPDATE tasks SET note=? WHERE id=?', (RECEIPT, task['id']))
    assert tick(api) == [task['id']]
    assert step(api, task) == 'Review 1'
    with api.app.state.store.read() as c:
        mover = c.execute("SELECT actor FROM task_events WHERE task_id=? AND field='step' ORDER BY ts DESC, rowid DESC",
                          (task['id'],)).fetchone()[0]
    assert mover == H.KEEPER
    assert owned_by(api, 'cmo') == []       # the type's manager heard nothing
    assert tick(api) == []                  # done once


def test_refused_for_failing_checks_moves_when_the_checks_pass(api):
    task = ticket(api, RECEIPT)
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE task_links SET detail_json=json_set(detail_json,'$.checks',json(?)) WHERE task_id=? AND kind='pr'",
                  (json.dumps({'python': 'failing'}), task['id']))
    refused = move(api, task)
    assert refused.status_code == 422 and 'Tico retries this move itself when the checks' in refused.json()['detail']
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE task_links SET detail_json=json_set(detail_json,'$.checks',json(?)) WHERE task_id=? AND kind='pr'",
                  (json.dumps({'python': 'passing'}), task['id']))
    assert tick(api) == [task['id']] and step(api, task) == 'Review 1'


def test_a_retry_still_refused_waits_for_the_next_change_and_stops_when_the_ticket_moves(api):
    task = ticket(api)
    assert move(api, task).status_code == 422
    with api.app.state.store.transaction() as c:   # a change, but not a receipt
        c.execute('UPDATE tasks SET note=? WHERE id=?', ('Still building the fix.', task['id']))
    assert tick(api) == [] and step(api, task) == 'In Progress'
    tries = retries(api, task)
    assert len(tries) == 2 and tries[-1]['tries'] == 1 and tries[-1]['state'] == 'waiting'
    assert tick(api) == [] and len(retries(api, task)) == 2      # same inputs: not tried again
    # The builder moves it elsewhere: the remembered move is dropped even when a receipt then arrives.
    fresh = get(api, 'tasks/' + task['id'])['task']
    with api.app.state.store.transaction() as c:
        H.task_update(c, H.KEEPER, task['id'], step='Done')
        c.execute('UPDATE tasks SET note=? WHERE id=?', (RECEIPT, task['id']))
    assert fresh['step']['name'] == 'In Progress'
    assert tick(api) == [] and step(api, task) == 'Done'


def test_hint_names_what_clears_each_refusal():
    assert 'checks on the current head pass' in move_retry.hint('ci', 'CI failing at head x')
    assert 'GitHub can be read again' in move_retry.hint('ci', 'cannot verify the current head and CI for x')
    assert move_retry.hint('other') == ''
