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
