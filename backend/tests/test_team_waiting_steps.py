"""A team's own waiting step holds the tickets a person parks there, and an upgrade never sends a ticket to a stale step."""
import sqlite3

from backend import hubdb as H, task_blocked
from backend.tests.test_review_gate import api, ticket, move, get
from backend.tests.test_github import post


def _park_step(api, task):
    with api.app.state.store.transaction() as c:
        typ = H.type_get(c, task['type_id'])
        H.type_update(c, H.KEEPER, typ['id'], steps=[*typ['steps'], {'name': 'Waiting On Dependency', 'status': 'waiting'}])
        return next(s['id'] for s in H.type_get(c, typ['id'])['steps'] if s['name'] == 'Waiting On Dependency')


def test_a_ticket_parked_by_hand_in_a_teams_waiting_step_stays_and_holds_never_land_there(api):
    parked = ticket(api)
    held = post(api, 'tasks', {'owner': 'cpo', 'title': 'Improve alerts', 'body': 'Build alerts.',
                               'type': parked['type_id'], 'step': 'In Progress'})
    step = _park_step(api, parked)
    assert move(api, parked, 'Waiting On Dependency').status_code == 200
    with api.app.state.store.transaction() as c:
        row = H.task(c, parked['id'])
        assert (row['step_id'], row['status'], row['blocked_kind']) == (step, 'waiting', 'manual')
        # Neither the hourly sweep nor a restart moves it out: a person parked it.
        H.sweep_stranded(c, H.shift(H.now(), hours=H.STRANDED_GRACE_HOURS + 1))
        H.migrate(c)
        assert H.task(c, parked['id'])['step_id'] == step
        assert any(s['id'] == step for s in H.type_get(c, parked['type_id'])['steps'])
        # A hold Tico finds goes to Blocked, never to the team's step.
        task_blocked.hold(c, held['id'], 'Waiting on a dependency')
        blocked = next(s['id'] for s in H.type_get(c, held['type_id'])['steps'] if s['name'] == 'Blocked')
        assert H.task(c, held['id'])['step_id'] == blocked
        # A status write on the parked ticket keeps it in its step.
        H._set_status(c, H.KEEPER, H.task(c, parked['id']), 'waiting', note='Still waiting')
        assert H.task(c, parked['id'])['step_id'] == step
    assert move(api, get(api, 'tasks/' + parked['id'])['task'], 'In Progress').status_code == 200
    with api.app.state.store.transaction() as c:
        row = H.task(c, parked['id'])
        assert (row['status'], row['blocked_since']) == ('doing', None)


def _dev(tmp_path):
    c = sqlite3.connect(tmp_path / 'hub.db', isolation_level=None)
    c.row_factory = sqlite3.Row
    H.migrate(c)
    c.execute("INSERT INTO task_types(id,name,created,updated) VALUES('dev','Dev tickets','x','x')")
    for position, (ident, name, status) in enumerate([
            ('deck', 'On Deck', 'open'), ('progress', 'In Progress', 'doing'),
            ('staging', 'Pending Push To Staging', 'doing'), ('closed', 'Closed', 'closed')]):
        c.execute('INSERT INTO task_steps(id,type_id,name,position,status) VALUES(?,?,?,?,?)',
                  (ident, 'dev', name, position, status))
    for ident in ('retired', 'chosen'):
        c.execute("INSERT INTO tasks(id,title,status,body,note,type_id,step_id) VALUES(?,?,'waiting','x','','dev','staging')",
                  (ident, 'A ticket'))
        H._task_event(c, ident, 'human:ana', 'step', 'progress', 'staging')
    # Retiring a waiting step put this one back in the step its history last named, weeks old.
    H._task_event(c, 'retired', H.KEEPER, 'step', 'old-waiting', 'staging', H.RETIRED_WAITING)
    return c


def test_a_return_step_an_upgrade_made_resumes_at_on_deck_and_a_chosen_one_is_kept(tmp_path):
    c = _dev(tmp_path)
    H.migrate(c)
    blocked = next(s['id'] for s in H.type_get(c, 'dev')['steps'] if s['name'] == 'Blocked')
    retired, chosen = H.task(c, 'retired'), H.task(c, 'chosen')
    assert retired['step_id'] == chosen['step_id'] == blocked
    assert (retired['blocked_from_step'], retired['blocked_from_status']) == (None, 'open')
    assert chosen['blocked_from_step'] == 'staging'
    events = c.execute('SELECT count(*) FROM task_events').fetchone()[0]
    H.migrate(c)
    assert c.execute('SELECT count(*) FROM task_events').fetchone()[0] == events
    for ident in ('retired', 'chosen'):
        c.execute("UPDATE tasks SET blocked_kind='dependency' WHERE id=?", (ident,))
        task_blocked.reconcile(c, ident)
    assert H.task(c, 'retired')['step_id'] == 'deck'
    assert H.task(c, 'chosen')['step_id'] == 'staging'
    c.close()
