"""The stall watcher (hubdb.wake_stalled; Ana, 2026-09-27: "ideally never stuck for more than 5
minutes"): a bot task nothing is going to move wakes its bot, spaced and capped, and BotOps takes
the ones waking does not move. Waiting, busy, blocked and routine-covered work is left alone."""
import json

import pytest

from backend.store import H
from backend.tests.test_api import api  # noqa: F401


def aged(c, task_id, minutes):
    c.execute("UPDATE tasks SET updated=? WHERE id=?", (H.shift(H.now(), seconds=-minutes * 60), task_id))


def wakes(c, task_id):
    return c.execute("SELECT count(*) FROM messages WHERE to_actor='bot:finance' AND refs_json LIKE ? "
                     "AND refs_json LIKE '%stalled%'", (f'%{task_id}%',)).fetchone()[0]


def test_a_task_nothing_will_move_wakes_its_bot_within_minutes_and_botops_takes_the_stubborn_ones(api):
    store = api.app.state.store
    with store.transaction() as c:
        c.execute("INSERT OR IGNORE INTO bots(slug,display_name,state) VALUES('botops','BotOps','active')")
        stuck = H.task_create(c, H.human_actor("ana"), "Recheck the cash warning", "Before the deadline.", "bot:finance")
        waiting = H.task_create(c, H.human_actor("ana"), "Wait for the bank", "Reply due Monday.", "bot:finance")
        later = H.task_create(c, H.human_actor("ana"), "Next time you run", "No hurry.", "bot:finance", next_run=True)
        H.task_update(c, "bot:finance", waiting["id"], status="waiting", note="The bank replies Monday.")
        c.execute("UPDATE jobs SET state='completed' WHERE bot='finance'")        # the creation wakes ran
        for t in (stuck, waiting, later):
            aged(c, t["id"], 6)
        # Six minutes quiet, nothing queued: the bot is woken on it; waiting work and a fresh
        # next-run task are left alone.
        out = H.wake_stalled(c)
        assert out["woke"] == [stuck["id"]] and wakes(c, stuck["id"]) == 1
        assert wakes(c, waiting["id"]) == 0 and wakes(c, later["id"]) == 0
        # The wake queued a run: nothing more while the bot is busy.
        assert c.execute("SELECT count(*) FROM jobs WHERE bot='finance' AND state='queued'").fetchone()[0] >= 1
        assert H.wake_stalled(c)["woke"] == []
        c.execute("UPDATE jobs SET state='completed' WHERE bot='finance'")
        # Not again within half an hour...
        assert H.wake_stalled(c)["woke"] == []
        # ...a next-run task gets half an hour before its first wake.
        aged(c, later["id"], 31)
        assert H.wake_stalled(c)["woke"] == [later["id"]]
        assert c.execute("SELECT next_run FROM tasks WHERE id=?", (later["id"],)).fetchone()[0] == 0
        # Three wakes in a day that did not move it: BotOps gets one task, and the bot is left be.
        c.execute("UPDATE events SET ts=? WHERE action='task.stall_wake' AND target=?",
                  (H.shift(H.now(), seconds=-3600), stuck["id"]))
        for _ in range(2):
            c.execute("INSERT INTO events(id,ts,actor,action,target,detail_json) VALUES(lower(hex(randomblob(8))),?,?,?,?,'{}')",
                      (H.shift(H.now(), seconds=-3600), H.KEEPER, "task.stall_wake", stuck["id"]))
        c.execute("UPDATE jobs SET state='completed' WHERE bot='finance'")
        aged(c, stuck["id"], 120)                # it has not moved since before those wakes
        out = H.wake_stalled(c)
        assert out["escalated"] == [stuck["id"]] and wakes(c, stuck["id"]) == 1
        assert c.execute("SELECT count(*) FROM tasks WHERE owner='bot:botops' AND title LIKE 'Find why finance%'").fetchone()[0] == 1
        assert H.wake_stalled(c)["escalated"] == []                              # once a day



def capped(c, task):
    aged(c, task['id'], 120)
    for _ in range(H.STALL_WAKES_PER_DAY):
        H.event(c, H.KEEPER, 'task.stall_wake', task['id'], {})
    c.execute("UPDATE events SET ts=? WHERE action='task.stall_wake' AND target=?",
              (H.shift(H.now(), hours=-1), task['id']))


def test_botops_cannot_be_its_own_last_resort_and_sources_do_not_share_a_repair_task(api):
    with api.app.state.store.transaction() as c:
        c.execute("INSERT OR IGNORE INTO bots(slug,display_name,state) VALUES('botops','BotOps','active')")
        first = H.task_create(c, 'bot:finance', 'Repair the mail registry', '', 'bot:botops')
        second = H.task_create(c, H.KEEPER, 'Investigate a stuck repair', '', 'bot:botops')
        for task in (first, second):
            capped(c, task)
        c.execute("UPDATE jobs SET state='completed' WHERE bot='botops'")
        assert H.wake_stalled(c)['escalated'] == [first['id'], second['id']]
        recoveries = [dict(r) for r in c.execute("SELECT * FROM tasks WHERE requester='keeper' AND id NOT IN (?,?)",
                                               (first['id'], second['id']))]
        assert len(recoveries) == 2
        assert {r['owner'] for r in recoveries} == {H.human_actor(H.default_human(c))}
        for task in (first, second):
            event = c.execute("SELECT detail_json FROM events WHERE action='task.stall_escalated' AND target=?",
                              (task['id'],)).fetchone()
            detail = json.loads(event[0])
            recovery = H.task(c, detail['recovery_task'])
            assert task['id'] in recovery['body']
            assert detail['owner'] == recovery['owner']
        assert H.wake_stalled(c) == {'woke': [], 'escalated': [], 'checked': [], 'stuck': []}
        assert not c.execute("SELECT 1 FROM jobs WHERE bot='botops' AND state='queued'").fetchone()


@pytest.mark.parametrize('state', ['paused'])
def test_unavailable_botops_routes_stalled_work_to_a_human(api, state):
    with api.app.state.store.transaction() as c:
        if state:
            c.execute("INSERT OR IGNORE INTO bots(slug,display_name,state) VALUES('botops','BotOps',?)", (state,))
        task = H.task_create(c, 'human:ben', 'Check the bank balance', '', 'bot:finance')
        capped(c, task)
        c.execute("UPDATE jobs SET state='completed' WHERE bot='finance'")
        assert H.wake_stalled(c)['escalated'] == [task['id']]
        assert c.execute("SELECT owner FROM tasks WHERE requester='keeper'").fetchone()[0] == 'human:ben'




def test_a_chat_task_gets_its_own_room_reports_once_and_a_quiet_session_is_checked_then_flagged(api):
    from backend.tests.test_api import post
    room = post(api, "chat/finance", {"text": "Can you look at cash?"})["conversation_id"]
    with api.app.state.store.transaction() as c:
        lines = lambda: [(r[0], json.loads(r[1])) for r in c.execute(
            "SELECT body,refs_json FROM messages WHERE conversation_id=? AND from_actor=? ORDER BY created", (room, H.KEEPER))]
        task = H.task_create(c, H.human_actor("ana"), "Recheck the cash warning", "Before the deadline.", "bot:finance",
                             conversation_id=room)
        assert task["conversation_id"] != room and H.conversation(c, task["conversation_id"])["kind"] == "task"
        assert [(b, r.get("task_started")) for b, r in lines()] == [("Started task: Recheck the cash warning", True)]
        # Its session ran 40 minutes ago and nothing moved since: one status check, no stall wake (it is busy).
        c.execute("INSERT INTO runners(id,label,operator,token_hash,created) VALUES('r1','r','ana','h','t')")
        job = c.execute("SELECT id FROM jobs WHERE bot='finance' ORDER BY created DESC LIMIT 1").fetchone()[0]
        c.execute("INSERT INTO attempts(id,job_id,bot,runner_id,generation,token_hash,state,lease_until,created,lane) "
                  "VALUES('a1',?,'finance','r1',1,'a1','running',?,?,?)",
                  (job, H.shift(H.now(), seconds=600), H.shift(H.now(), seconds=-2400), "task:" + task["id"]))
        aged(c, task["id"], 40)
        out = H.wake_stalled(c)
        assert out["checked"] == [task["id"]] and out["woke"] == [] and out["stuck"] == []
        assert H.wake_stalled(c)["checked"] == []                       # once per quiet stretch
        # Half an hour after the check, still nothing: reported stuck in the main chat, and Ana is asked.
        c.execute("UPDATE events SET ts=? WHERE action='task.stall_wake' AND target=?",
                  (H.shift(H.now(), seconds=-1900), task["id"]))
        assert H.wake_stalled(c)["stuck"] == [task["id"]]
        assert lines()[-1][1]["task_report"] == "stuck" and lines()[-1][0].startswith("Recheck the cash warning: stuck.")
        assert c.execute("SELECT count(*) FROM messages WHERE kind='ask' AND to_actor='human:ana' "
                         "AND refs_json LIKE '%stuck%'").fetchone()[0] == 1
        assert H.wake_stalled(c)["stuck"] == []
        # Done: one report line; the same state is not reported twice.
        H.task_update(c, "bot:finance", task["id"], status="done", note="Cash is fine.")
        H.task_report(c, H.task(c, task["id"]), "done", "Again.")
        assert [b for b, r in lines() if r.get("task_report") == "done"] == ["Recheck the cash warning: done. Cash is fine."]


def test_closing_what_the_bot_already_finished_does_not_wake_it_unless_the_note_says_something_new(api):
    with api.app.state.store.transaction() as c:
        def closed_wakes(task_id):
            rows = c.execute("SELECT m.id,(SELECT count(*) FROM jobs j WHERE j.message_id=m.id) FROM messages m "
                             "WHERE m.to_actor='bot:finance' AND m.body LIKE 'Closed:%' AND m.refs_json LIKE ?",
                             (f'%{task_id}%',)).fetchall()
            return [r[1] for r in rows]
        ana = H.human_actor("ana")
        same, new = (H.task_create(c, ana, title, "Review it.", "bot:finance") for title in ("Review the Q3 deck", "Review the Q4 deck"))
        for row in (same, new):
            H.task_update(c, "bot:finance", row["id"], status="done", note="Reviewed; two fixes made.")
        H.task_close(c, ana, same["id"], note="Reviewed; two fixes made.")
        H.task_close(c, ana, new["id"], note="Ship the fixes to the board too.")
        assert closed_wakes(same["id"]) == [] and closed_wakes(new["id"]) == [0]     # the new note lands without a run
