"""Lost handoffs recover once; execution holds stay visible without bypassing them."""
import pytest

from backend import assigned_start as A, health, health_monitor, queue_refusals
from backend.store import H
from backend.tests.test_api import api, claim, get, post  # noqa: F401
from backend.tests.test_auto_tasks import deck, finish, set_cap, take
from backend.tests.test_profiles import put
from backend.tests.test_task_lanes import new_task, task_bot


@pytest.fixture
def clock(monkeypatch):
    value = ['2026-10-20T00:00:00.000000Z']
    monkeypatch.setattr(H, 'now', lambda: value[0])
    return value


def advance(api, clock, hours):
    clock[0] = H.shift(clock[0], hours=hours)
    with api.app.state.store.transaction() as c:
        c.execute('UPDATE runners SET last_seen=?', (H.now(),))


def sweep(api):
    with api.app.state.store.transaction() as c:
        return A.sweep(c)


def cancel(api):
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE jobs SET state='cancelled'")


@pytest.mark.parametrize('profile', ['lead', 'doer'])
def test_cancelled_assignment_rewakes_once_at_one_hour_and_can_start(api, clock, profile):
    machine = task_bot(api, lanes=True)
    with api.app.state.store.transaction() as c:
        put(c, 'ops', profile)
    task = new_task(api, 'Lost assignment')
    cancel(api)
    advance(api, clock, 0.999)
    assert sweep(api) == []
    advance(api, clock, 0.001)
    assert sweep(api) == [task['id']]
    assert sweep(api) == []
    attempt = claim(api, machine)
    assert attempt['task']['id'] == task['id']
    assert get(api, 'tasks/' + task['id'])['task']['status'] == 'doing'
    advance(api, clock, 3)
    with api.app.state.store.read() as c:
        assert list(A.overdue(c)) == []


@pytest.mark.parametrize('hold', ['waiting', 'snoozed', 'blocked', 'question', 'attempt'])
def test_intentional_waits_and_any_attempt_are_not_rewoken(api, clock, hold):
    machine = task_bot(api, lanes=True)
    task = new_task(api, 'Held assignment')
    if hold == 'attempt':
        assert claim(api, machine)
        # Even a failed pre-start attempt is recovery work, never a lost assignment.
        with api.app.state.store.transaction() as c:
            c.execute("UPDATE tasks SET status='open' WHERE id=?", (task['id'],))
    else:
        with api.app.state.store.transaction() as c:
            if hold == 'waiting':
                c.execute("UPDATE tasks SET waiting_on='human:ana' WHERE id=?", (task['id'],))
            elif hold == 'snoozed':
                c.execute('UPDATE tasks SET snoozed_until=? WHERE id=?', (H.shift(H.now(), days=1), task['id']))
            elif hold == 'blocked':
                blocker = H.task_create(c, 'human:ana', 'Prerequisite', 'Finish first.', 'human:ana', lint=False)
                H.TR.add_blocker(c, H.KEEPER, task['id'], blocker['id'])
            else:
                H.task_ask(c, 'bot:ops', task['id'], 'Which date should I use?')
    cancel(api)
    advance(api, clock, 4)
    assert sweep(api) == []


def test_still_unstarted_health_and_manager_needs_you_show_task_and_actual_reason(api, clock):
    task_bot(api, lanes=True)
    with api.app.state.store.transaction() as c:
        put(c, 'ops', 'lead')
        c.execute("UPDATE bot_config SET reports_to='human:ana' WHERE bot='ops'")
    task = new_task(api, 'Publish the daily report')
    cancel(api)
    advance(api, clock, 1)
    assert sweep(api) == [task['id']]
    set_cap(api, 0)
    advance(api, clock, 1.999)
    assert not any(i.get('assigned_not_started') for i in get(api, 'needs-you')['items'])
    advance(api, clock, 0.001)
    page = get(api, 'health')
    check = next(x for x in page['checks'] if x['id'] == 'assigned_not_started')
    assert 'Publish the daily report' in check['summary'] and 'auto_start_off' in check['summary']
    card = next(x for x in get(api, 'needs-you')['items'] if x['id'] == task['id'])
    assert card['assigned_not_started'] and 'auto_start_off' in card['note']
    assert task['id'] not in {i['id'] for i in get(api, 'needs-you', token='ben-test')['items']}
    # A successful claim clears both read-time lists immediately.
    set_cap(api, 1)
    with api.app.state.store.transaction() as c:
        H._set_status(c, H.KEEPER, H.task(c, task['id']), 'doing')
    assert not any(x['id'] == 'assigned_not_started' for x in get(api, 'health')['checks'])


def test_private_assignment_does_not_grant_manager_access(api, clock):
    task_bot(api, lanes=True)
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bot_config SET reports_to='human:ben' WHERE bot='ops'")
    task = post(api, 'tasks', {'owner': 'ops', 'title': 'Private assigned work', 'body': 'Keep this private.', 'private': True})
    cancel(api)
    advance(api, clock, 1)
    assert sweep(api) == [task['id']]
    advance(api, clock, 2)
    assert task['id'] not in {i['id'] for i in get(api, 'needs-you', token='ben-test')['items']}
    assert 'Private assigned work' not in str(get(api, 'health', token='ben-test'))


def test_reassignment_gets_its_own_hour_not_the_last_comment_time(api, clock):
    task_bot(api, lanes=True)
    task = new_task(api, 'Reassigned work')
    cancel(api)
    advance(api, clock, 1)
    assert sweep(api) == [task['id']]
    with api.app.state.store.transaction() as c:
        H.task_update(c, 'human:ana', task['id'], owner='bot:finance')
    cancel(api)
    assert sweep(api) == []
    advance(api, clock, 1)
    assert sweep(api) == [task['id']]


def test_refused_recovery_is_recorded_once_instead_of_retried_each_tick(api, clock, monkeypatch):
    task_bot(api, lanes=True)
    task = new_task(api, 'Assignment whose delivery refuses')
    cancel(api)
    advance(api, clock, 1)
    calls = []

    def refused(*args, **kwargs):
        calls.append(True)
        raise H.Refused('cap', 'Synthetic delivery cap')

    monkeypatch.setattr(H, '_wake', refused)
    assert sweep(api) == [] and sweep(api) == [] and len(calls) == 1
    advance(api, clock, 2)
    with api.app.state.store.read() as c:
        [row] = A.overdue(c)
        assert row['id'] == task['id'] and row['rewake_refusal'] == 'cap'


def test_scheduler_restart_recovers_once_and_rehearsal_never_recovers(api, clock):
    from backend.scheduler import Scheduler
    task_bot(api, lanes=True)
    task = new_task(api, 'Scheduler assignment')
    cancel(api)
    advance(api, clock, 1)
    store = api.app.state.store
    store.settings.rehearsal = True
    Scheduler(store, api.app.state.execution).tick(H.parse_ts(H.now()))
    with store.read() as c:
        assert not c.execute('SELECT 1 FROM events WHERE action=?', (A.EVENT,)).fetchone()
    store.settings.rehearsal = False
    for _ in range(2):
        Scheduler(store, api.app.state.execution).tick(H.parse_ts(H.now()))
    with store.read() as c:
        assert c.execute('SELECT count(*) FROM events WHERE action=? AND target=?', (A.EVENT, task['id'])).fetchone()[0] == 1


def test_five_deck_tickets_progress_under_three_task_cap_without_lead_turns(api):
    machine = task_bot(api, lanes=True, capacity=8)
    tasks = deck(api, 5)
    set_cap(api, 3)
    first = [take(api, machine) for _ in range(3)]
    assert len({a['task']['id'] for a in first}) == 3 and take(api, machine) is None
    by_id = {t['id']: t for t in tasks}
    reached = {a['task']['id'] for a in first}
    for a in first[:2]:
        finish(api, machine, a, by_id[a['task']['id']])
        reached.add(take(api, machine)['task']['id'])
    assert reached == set(by_id)
    with api.app.state.store.read() as c:
        assert {r[0] for r in c.execute('SELECT DISTINCT bot FROM attempts')} == {'ops'}


@pytest.mark.parametrize('refusal', ['auto_start_off', 'task_wait', 'check_model', 'backoff'])
def test_running_lane_does_not_mask_other_lanes_refusal_and_twelve_hour_finding(api, clock, refusal):
    machine = task_bot(api, lanes=True)
    new_task(api, 'Running task')
    assert claim(api, machine)
    task = new_task(api, 'Unstarted task')
    if refusal == 'auto_start_off':
        set_cap(api, 0)
    with api.app.state.store.transaction() as c:
        if refusal == 'task_wait':
            c.execute("UPDATE tasks SET waiting_on='human:ana' WHERE id=?", (task['id'],))
        elif refusal == 'check_model':
            from backend import check_models
            check_models.record(c, 'bot:ops', task['id'], {'runtime': 'codex', 'model': 'gpt-6.1',
                                'harness': 'codex', 'effort': '', 'role': 'check'})
            check_models.hold(c, task['id'], 'codex', H.shift(H.now(), days=1))
        elif refusal == 'backoff':
            c.execute("INSERT INTO run_backoff(bot,fails,wait_until) VALUES('ops',1,?)", (H.shift(H.now(), days=1),))
    with api.app.state.store.transaction() as c:
        queue_refusals.observe(c, api.app.state.store.settings)
    advance(api, clock, 13)
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE jobs SET created=? WHERE state='queued'", (H.shift(H.now(), hours=-13),))
        online = {r['id'] for r in health._online_runners(c)}
        rows = [r for r in health._waiting(c, online, api.app.state.store.settings)[2] if r['bot'] == 'ops']
        assert [r['reason'] for r in rows] == [refusal]
        assert 'queue_refused' in {f['check_id'] for f in health_monitor.findings(c, api.app.state.store.settings)}
    check = next(x for x in get(api, 'health')['checks'] if x['id'] == 'queue_refused')
    assert check['items'][0]['reason'] == refusal
    # A newer claimable chat cannot hide the old refused task in the aged-job list.
    post(api, 'chat/ops', {'text': 'A quick question.'})
    with api.app.state.store.read() as c:
        assert health.refused_queues(c, api.app.state.store.settings)[0]['reason'] == refusal
    assert get(api, 'tasks/' + task['id'])['task']['status'] == 'open'


def test_old_queue_only_ages_refusal_from_observation_and_clearing_resets_it(api, clock):
    task_bot(api, lanes=True)
    new_task(api, 'Old queued task')
    set_cap(api, 0)
    advance(api, clock, 13)
    store = api.app.state.store
    with store.transaction() as c:
        queue_refusals.observe(c, store.settings)
        assert health.refused_queues(c, store.settings) == []
    advance(api, clock, 12)
    with store.transaction() as c:
        assert health.refused_queues(c, store.settings)
    set_cap(api, 1)
    with store.transaction() as c:
        queue_refusals.observe(c, store.settings)
        assert health.refused_queues(c, store.settings) == []
    set_cap(api, 0)
    with store.transaction() as c:
        queue_refusals.observe(c, store.settings)
        assert health.refused_queues(c, store.settings) == []
