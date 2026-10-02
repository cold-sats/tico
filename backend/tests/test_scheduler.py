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
