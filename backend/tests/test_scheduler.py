from datetime import datetime, timezone

from backend.tests.test_api import api, get, post  # noqa: F401
from backend.scheduler import Scheduler, next_due
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


def test_timezone_tracks_daylight_saving():
    winter = next_due("0 9 * * *", datetime(2026, 1, 10, tzinfo=timezone.utc), "America/Los_Angeles")
    summer = next_due("0 9 * * *", datetime(2026, 7, 10, tzinfo=timezone.utc), "America/Los_Angeles")
    assert winter.astimezone(timezone.utc).hour == 17
    assert summer.astimezone(timezone.utc).hour == 16


def test_due_reminder_deduplicates_across_scheduler_restart(api):
    task = post(api, "tasks", {"owner": "coo", "title": "Review deadline", "body": "Review pending work", "due": "2026-09-10T15:00:00Z"})
    store = api.app.state.store
    for _ in range(2):
        Scheduler(store, api.app.state.execution).tick(datetime(2026, 9, 10, 17, tzinfo=timezone.utc))
    with store.read() as c:
        assert c.execute("SELECT count(*) FROM task_reminders").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM messages WHERE conversation_id=?", (task["conversation_id"],)).fetchone()[0] == 2
