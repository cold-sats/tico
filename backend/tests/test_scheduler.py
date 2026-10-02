from datetime import datetime, timezone

from backend.tests.test_api import api, get, post  # noqa: F401
from backend.scheduler import Scheduler
from backend.store import H


def test_schedule_survives_restart_without_duplicate_work(api):
    at = datetime(2026, 9, 10, 17, 0, tzinfo=timezone.utc)
    store = api.app.state.store
    with store.transaction() as c:
        c.execute("INSERT INTO schedules(id,bot,cron,title,playbook,last_fired,next_due) "
                  "VALUES('morning','coo','0 9 * * *','Review daily work','Review work',NULL,?)",
                  ('2026-09-09T16:00:00.000000Z',))
    first = Scheduler(store, api.app.state.execution).tick(at)
    second = Scheduler(store, api.app.state.execution).tick(at)
    assert len(first["fired"]) == 1
    assert not second["fired"]
    with store.read() as c:
        assert c.execute("SELECT count(*) FROM schedule_occurrences").fetchone()[0] == 1
        # The day's update request (backend/updates.py) is a job of its own, not the routine's.
        assert c.execute("SELECT count(*) FROM jobs j JOIN messages m ON m.id=j.message_id "
                         "WHERE json_extract(m.refs_json,'$.update_request') IS NULL").fetchone()[0] == 1
        assert c.execute("SELECT next_due FROM schedules").fetchone()[0] == '2026-09-11T16:00:00.000000Z'


def test_due_reminder_deduplicates_across_scheduler_restart(api):
    task = post(api, "tasks", {"owner": "coo", "title": "Review deadline", "body": "Review pending work", "due": "2026-09-10T15:00:00Z"})
    store = api.app.state.store
    for _ in range(2):
        Scheduler(store, api.app.state.execution).tick(datetime(2026, 9, 10, 17, tzinfo=timezone.utc))
    with store.read() as c:
        assert c.execute("SELECT count(*) FROM task_reminders").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM messages WHERE conversation_id=?", (task["conversation_id"],)).fetchone()[0] == 2


def test_idle_claims_do_not_take_the_write_lock_and_never_starve_leases(api):
    import threading, time
    from backend.tests.test_api import assign, headers, ready, runner
    runners = []
    for bot in ("ops", "finance", "cpo"):
        r = runner(api, label=bot)
        assign(api, r, bot)
        ready(api, r, [bot])
        runners.append(r)
        post(api, "jobs/claim", {"next_run": True}, token=r["token"])      # first contact stamps last_seen
    store = api.app.state.store
    # Another writer holds the lock for a second; an idle claim answers at once anyway.
    with store.read() as holder:
        holder.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        assert post(api, "jobs/claim", {"next_run": True}, token=runners[0]["token"]) == {"attempt": None}
        assert time.monotonic() - started < 1
        assert post(api, "jobs/claim", {"busy_bots": ["unknown-bot"]}, token=runners[0]["token"]) == {"attempt": None}
        holder.execute("ROLLBACK")
    post(api, "chat/ops", {"text": "Anything today?"})
    statuses, got = [], []
    def loop(r):
        for _ in range(15):
            res = api.post("/api/v2/jobs/claim", json={"next_run": True}, headers=headers(r["token"]))
            statuses.append(res.status_code)
            got.append(res.json().get("attempt"))
    threads = [threading.Thread(target=loop, args=(r,)) for r in runners]
    for t in threads:
        t.start()
    for _ in range(3):
        Scheduler(store, api.app.state.execution).tick()
    for t in threads:
        t.join()
    assert set(statuses) == {200}, "no storage_unavailable"
    assert len([a for a in got if a]) == 1
    with store.read() as c:
        assert c.execute("SELECT count(*) FROM attempts WHERE state='expired'").fetchone()[0] == 0


def test_legacy_done_parent_with_open_child_and_one_failed_close_do_not_stop_tick(api, monkeypatch):
    store = api.app.state.store
    with store.transaction() as c:
        parent = H.task_create(c, 'bot:ops', 'Accept existing work', 'x', 'bot:cpo', lint=False)
        child = H.task_create(c, 'bot:ops', 'Finish child work', 'x', 'bot:cpo', parent_id=parent['id'], lint=False)
        poisoned = H.task_create(c, 'bot:ops', 'Accept another delivery', 'x', 'bot:cpo', lint=False)
        for task in (parent, poisoned):
            c.execute("UPDATE tasks SET status='done',done_at='2026-01-01T00:00:00Z' WHERE id=?", (task['id'],))
    real = H.task_close
    def close(c, actor, task_id, *args, **kw):
        if task_id == poisoned['id']:
            c.execute("UPDATE tasks SET note='partial' WHERE id=?", (task_id,))
            raise RuntimeError('bad row')
        return real(c, actor, task_id, *args, **kw)
    monkeypatch.setattr(H, 'task_close', close)
    Scheduler(store, api.app.state.execution).tick(datetime(2026, 9, 10, 17, tzinfo=timezone.utc))
    with store.read() as c:
        assert H.task(c, parent['id'])['status'] == 'closed'
        assert H.task(c, child['id'])['status'] == 'open'
        assert H.task(c, poisoned['id'])['note'] == ''
        assert c.execute("SELECT last_success FROM service_health WHERE service='scheduler'").fetchone()[0]
def test_path_like_titles_and_a_failed_reminder_do_not_stop_other_rows(api, monkeypatch):
    store = api.app.state.store
    tasks = [post(api, "tasks", {"owner": "coo", "title": title, "body": "Review access",
                                   "due": "2026-09-10T15:00:00Z"})
             for title in ("Review secrets/prod access", "Review emp-ops/reports", "Broken reminder")]
    original = H.say
    def say(c, actor, target, body, **kw):
        if body == "Due: Broken reminder":
            H.event(c, H.KEEPER, "reminder.partial", tasks[-1]["id"])
            raise RuntimeError("broken row")
        return original(c, actor, target, body, **kw)
    monkeypatch.setattr(H, "say", say)
    with store.transaction() as c:
        c.execute("INSERT INTO registry_metadata VALUES('deployment-drain:broken','invalid json')")
        c.execute("INSERT INTO schedules(id,bot,cron,title,playbook,next_due) "
                  "VALUES('healthy','coo','0 9 * * *','Review daily work','Review work',?)",
                  ('2026-09-09T16:00:00Z',))
    result = Scheduler(store, api.app.state.execution).tick(datetime(2026, 9, 10, 17, tzinfo=timezone.utc))
    assert len(result["fired"]) == 1
    assert result["failures"] == [{"reminder": tasks[-1]["id"], "error": "RuntimeError"}]
    with store.read() as c:
        assert {r[0] for r in c.execute("SELECT task_id FROM task_reminders")} == {t["id"] for t in tasks[:2]}
        assert not c.execute("SELECT 1 FROM events WHERE action='reminder.partial'").fetchone()
        assert c.execute("SELECT count(*) FROM schedule_occurrences").fetchone()[0] == 1


def test_claim_query_skips_unready_queue_and_reuses_unchanged_selection(api, monkeypatch):
    from backend.tests.test_api import assign, ready, runner
    r = runner(api)
    assign(api, r, "ops")
    assign(api, r, "finance")
    ready(api, r, ["finance"])
    store, execution = api.app.state.store, api.app.state.execution
    with store.transaction() as c:
        for _ in range(40):
            H.say(c, H.KEEPER, "bot:ops", "Review queued work", kind="notice")
        expected = H.say(c, "human:ana", "bot:finance", "Review this first")
    calls = []
    candidate = execution.candidate
    def select(*args):
        calls.append(1)
        return candidate(*args)
    monkeypatch.setattr(execution, "candidate", select)
    result = post(api, "jobs/claim", {}, token=r["token"])["attempt"]
    assert result["message"]["id"] == expected["id"] and calls == [1]


def test_claim_reselects_when_database_changes_after_the_read(api, monkeypatch):
    from backend.tests.test_api import assign, ready, runner
    r = runner(api)
    assign(api, r, "ops")
    ready(api, r, ["ops"])
    post(api, "chat/ops", {"text": "Review work"})
    store, execution = api.app.state.store, api.app.state.execution
    idle = execution._idle_claim
    def drain_after_read(*args):
        result = idle(*args)
        with store.transaction() as c:
            c.execute("INSERT INTO bot_control(bot,draining) VALUES('ops',1) "
                      "ON CONFLICT(bot) DO UPDATE SET draining=1")
        return result
    monkeypatch.setattr(execution, "_idle_claim", drain_after_read)
    assert post(api, "jobs/claim", {}, token=r["token"])["attempt"] is None


def test_claim_sql_preserves_python_task_refs_and_unrelated_human_chats(api):
    from backend.tests.test_api import assign, ready, runner
    r = runner(api)
    assign(api, r, "ops")
    ready(api, r, ["ops"])
    store = api.app.state.store
    with store.transaction() as c:
        held = H.say(c, "human:ana", "bot:ops", "Interrupted request", refs={"task": "held-task"})
        c.execute("UPDATE jobs SET state='uncertain' WHERE message_id=?", (held["id"],))
        blocked = H.say(c, "human:ana", "bot:ops", "Continue that request",
                        conversation_id=held["conversation_id"], refs={"task": [None, "\u00a0held-task\u3000"]})
        unrelated = H.say(c, "human:ana", "bot:ops", "An unrelated request",
                          conversation_id=held["conversation_id"], refs={"task": 42})
    result = post(api, "jobs/claim", {}, token=r["token"])["attempt"]
    assert result["message"]["id"] == unrelated["id"]
    with store.read() as c:
        assert c.execute("SELECT state FROM jobs WHERE message_id=?", (blocked["id"],)).fetchone()[0] == 'queued'


def test_background_failures_are_rate_limited_and_visible_in_health(api, monkeypatch, caplog):
    from backend.batch_work import isolated, _logged
    _logged.clear()
    store = api.app.state.store
    for _ in range(3):
        with store.transaction() as c:
            with isolated(c, "expire", "broken-attempt"):
                raise ValueError("Invalid saved run")
    lines = [r for r in caplog.records if 'expire failed for broken-attempt' in r.message]
    assert len(lines) == 1 and lines[0].exc_info
    assert any('Invalid saved run' in i['detail'] for i in get(api, 'operations')['issues'])
    later = _logged[('expire', 'broken-attempt')] + 3601
    monkeypatch.setattr('backend.batch_work._clock', lambda: later)
    with store.transaction() as c:
        with isolated(c, "expire", "broken-attempt"):
            raise ValueError("Invalid saved run")
    lines = [r for r in caplog.records if 'expire failed for broken-attempt' in r.message]
    assert len(lines) == 2 and not lines[-1].exc_info
    with store.transaction() as c:
        with isolated(c, "expire", "broken-attempt"):
            pass
        assert not c.execute("SELECT 1 FROM service_health WHERE service='background:expire:broken-attempt'").fetchone()


def test_refused_reminder_is_recorded_and_not_retried(api, monkeypatch):
    task = post(api, "tasks", {"owner": "coo", "title": "Reminder", "body": "Review", "due": "2026-09-10T15:00:00Z"})
    original, refused = H.say, []
    def say(c, actor, target, body, **kw):
        if body == 'Due: Reminder':
            refused.append(body)
            raise H.Refused('reach', 'Task owner cannot receive this reminder')
        return original(c, actor, target, body, **kw)
    monkeypatch.setattr(H, 'say', say)
    scheduler = Scheduler(api.app.state.store, api.app.state.execution)
    for _ in range(2):
        scheduler.tick(datetime(2026, 9, 10, 17, tzinfo=timezone.utc))
    assert len(refused) == 1
    with api.app.state.store.read() as c:
        assert c.execute("SELECT 1 FROM task_reminders WHERE task_id=?", (task['id'],)).fetchone()
        assert c.execute("SELECT 1 FROM events WHERE action='task.reminder-refused' AND target=?", (task['id'],)).fetchone()


def test_database_failure_keeps_original_error_and_stops_work(tmp_path):
    import sqlite3
    import pytest
    from backend.batch_work import isolated
    c = sqlite3.connect(tmp_path / 'full.db', isolation_level=None)
    c.execute('CREATE TABLE data(x)')
    pages = c.execute('PRAGMA page_count').fetchone()[0]
    c.execute(f'PRAGMA max_page_count={pages + 2}')
    c.execute('BEGIN IMMEDIATE')
    with pytest.raises(sqlite3.DatabaseError, match='database or disk is full'):
        with isolated(c, 'disk', 'one'):
            c.execute('INSERT INTO data VALUES(?)', ('x' * 200000,))
    assert not c.in_transaction
    c.execute('BEGIN IMMEDIATE')
    with pytest.raises(sqlite3.DatabaseError, match='malformed'):
        with isolated(c, 'disk', 'two'):
            c.execute('INSERT INTO data VALUES(?)', ('written before corruption',))
            exc = sqlite3.DatabaseError('database disk image is malformed')
            exc.sqlite_errorcode = sqlite3.SQLITE_CORRUPT
            raise exc
    c.rollback()
    c.close()


def test_claim_query_matches_old_python_oracle_on_200_rows(api):
    import itertools
    import json
    from backend.auth import Identity
    from backend.models import Claim
    from backend.execution import bot_readiness, readiness_document
    from backend.statuses import PARKED
    from backend.tests.test_api import assign, ready, runner
    r = runner(api)
    for bot in ('ops', 'finance', 'cpo'):
        assign(api, r, bot)
    ready(api, r, ['ops', 'finance'])
    store, execution = api.app.state.store, api.app.state.execution
    who = Identity('runner:' + r['runner_id'], 'runner', runner_id=r['runner_id'])
    with store.transaction() as c:
        rooms = {}
        for bot, kind in itertools.product(('ops', 'finance', 'cpo'), ('chat', 'task')):
            rooms[bot, kind] = H.open_conversation(c, 'human:ana', ['bot:' + bot], kind=kind)['id']
        refs = ['held', [' ', None, '\u00a0held\u3000'], 42, ' \t\n', '', None, ['other']]
        for i in range(200):
            bot = ('ops', 'finance', 'cpo')[i % 3]
            kind = ('chat', 'task')[(i // 3) % 2]
            sender = ('human:ana', H.KEEPER)[(i // 6) % 2]
            m = H.say(c, sender, 'bot:' + bot, f'Generated request {i}', conversation_id=rooms[bot, kind],
                      refs={'task': refs[(i // 12) % len(refs)]})
            c.execute("UPDATE jobs SET created=?,state=? WHERE message_id=?", ('2026-09-01T00:00:00Z' if i % 5 == 0 else '2026-09-02T00:00:00Z', 'uncertain' if i % 17 == 0 else 'queued', m['id']))
        c.execute("UPDATE bot_config SET onboarding_state='needs_setup' WHERE bot='finance'")
        readiness = readiness_document(c.execute('SELECT readiness_json FROM runners WHERE id=?', (r['runner_id'],)).fetchone()[0])
        # The old candidate's Python predicate, with readiness and onboarding gates.
        def old_claimable(job):
            check = bot_readiness(readiness, job['bot'])
            if check.get('ready') is not True:
                return False
            msg = H.message(c, job['message_id'])
            conv = H.conversation(c, msg['conversation_id'])
            parked = c.execute('SELECT onboarding_state FROM bot_config WHERE bot=?', (job['bot'],)).fetchone()[0]
            if not msg['from_actor'].startswith('human:') and parked in PARKED:
                return False
            task = H.message_task_id(msg, conv)
            if not (msg['from_actor'].startswith('human:') and conv['kind'] == 'chat' and task is None):
                for held in c.execute("SELECT message_id FROM jobs WHERE bot=? AND state='uncertain'", (job['bot'],)):
                    other = H.message(c, held[0])
                    other_conv = H.conversation(c, other['conversation_id'])
                    if (task and H.message_task_id(other, other_conv) == task) or (not task and conv['kind'] == 'chat' and other['conversation_id'] == msg['conversation_id']):
                        return False
            return True
        # Compare the entire order, including tied and NULL timestamps, not just the first row.
        for _ in range(200):
            rows = c.execute("SELECT j.* FROM jobs j JOIN messages m ON m.id=j.message_id WHERE j.state='queued' ORDER BY CASE WHEN m.from_actor LIKE 'human:%' THEN 0 ELSE 1 END,j.created,j.id").fetchall()
            expected = next((j for j in rows if old_claimable(j)), None)
            actual = execution.candidate(c, who, Claim(), execution.runner(c, who))
            assert (actual['id'] if actual else None) == (expected['id'] if expected else None)
            if actual is None:
                break
            c.execute("UPDATE jobs SET state='completed' WHERE id=?", (actual['id'],))


def test_row_isolation_keeps_standalone_task_databases_working(tmp_path):
    import sqlite3
    from backend.batch_work import isolated
    c = sqlite3.connect(tmp_path / 'tasks.db', isolation_level=None)
    c.execute('CREATE TABLE data(x)')
    c.execute('BEGIN IMMEDIATE')
    with isolated(c, 'row', 'bad'):
        c.execute('INSERT INTO data VALUES(1)')
        raise ValueError('Bad row')
    with isolated(c, 'row', 'good'):
        c.execute('INSERT INTO data VALUES(2)')
    c.commit()
    assert c.execute('SELECT x FROM data').fetchall() == [(2,)]
    c.close()


def test_row_sql_error_rolls_back_row_and_keeps_next_row(api):
    from backend.batch_work import isolated
    store = api.app.state.store
    with store.transaction() as c:
        with isolated(c, 'json', 'bad'):
            c.execute("INSERT INTO registry_metadata VALUES('bad-row','{}')")
            c.execute("SELECT json_extract(?, '$.value')", ('{',))
        with isolated(c, 'json', 'good'):
            c.execute("INSERT INTO registry_metadata VALUES('good-row','{}')")
        assert not c.execute("SELECT 1 FROM registry_metadata WHERE key='bad-row'").fetchone()
        assert c.execute("SELECT 1 FROM registry_metadata WHERE key='good-row'").fetchone()
        assert c.execute("SELECT last_error FROM service_health WHERE service='background:json:bad'").fetchone()[0] == 'json: malformed JSON'
