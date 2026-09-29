"""The stall watcher (hubdb.wake_stalled; Ana, 2026-09-27: "ideally never stuck for more than 5
minutes"): a bot task nothing is going to move wakes its bot, spaced and capped, and BotOps takes
the ones waking does not move. Waiting, busy, blocked and routine-covered work is left alone."""
from backend.store import H, encode
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


def test_a_routine_due_soon_or_an_open_blocker_covers_the_task(api):
    store = api.app.state.store
    with store.transaction() as c:
        blocker = H.task_create(c, H.human_actor("ana"), "Get the statement", "From the bank.", "bot:ops")
        t = H.task_create(c, H.human_actor("ana"), "Reconcile the statement", "After it arrives.", "bot:finance")
        c.execute("UPDATE tasks SET blocked_by=? WHERE id=?", (blocker["id"], t["id"]))
        c.execute("UPDATE jobs SET state='completed'")
        aged(c, t["id"], 10)
        aged(c, blocker["id"], 1)
        assert t["id"] not in H.wake_stalled(c)["woke"]
        c.execute("UPDATE tasks SET blocked_by=NULL WHERE id=?", (t["id"],))
        c.execute("INSERT INTO schedules(id,bot,cron,title,playbook,next_due) VALUES('finance:sweep','finance','*/30 * * * *','Sweep','',?)",
                  (H.shift(H.now(), seconds=600),))
        assert t["id"] not in H.wake_stalled(c)["woke"]


def test_a_task_due_later_is_left_alone_until_its_due_date(api):
    # bot:seo, 2026-09-27: follow-ups that wait for Google's crawl carry a due date; the "Due:"
    # notice wakes the bot then, so the stall watcher does not nag it every 30 minutes before.
    store = api.app.state.store
    with store.transaction() as c:
        later = H.task_create(c, H.human_actor("ana"), "Measure after the crawl", "When Google has recrawled.",
                              "bot:finance", due=H.shift(H.now(), seconds=5 * 86400))
        overdue = H.task_create(c, H.human_actor("ana"), "Measure the finished week", "The week is over.",
                                "bot:finance", due=H.shift(H.now(), seconds=-3600))
        c.execute("UPDATE jobs SET state='completed'")
        aged(c, later["id"], 60)
        aged(c, overdue["id"], 60)
        woke = H.wake_stalled(c)["woke"]
        assert later["id"] not in woke and overdue["id"] in woke


def test_a_task_that_moves_after_each_wake_is_not_handed_to_botops(api):
    # A bot worked through hundreds of sites a batch per wake; three wakes in a day were
    # counted as stuck although the task moved after each.
    store = api.app.state.store
    with store.transaction() as c:
        c.execute("INSERT OR IGNORE INTO bots(slug,display_name,state) VALUES('botops','BotOps','active')")
        t = H.task_create(c, H.human_actor("ana"), "Load the sites in batches", "One batch a run.", "bot:finance")
        c.execute("UPDATE jobs SET state='completed'")
        for hours in (5, 3, 1):          # woken three times, and it moved after each
            c.execute("INSERT INTO events(id,ts,actor,action,target,detail_json) VALUES(lower(hex(randomblob(8))),?,?,?,?,'{}')",
                      (H.shift(H.now(), seconds=-hours * 3600), H.KEEPER, "task.stall_wake", t["id"]))
        aged(c, t["id"], 40)             # last moved 40 minutes ago, after the third wake
        out = H.wake_stalled(c)
        assert out["woke"] == [t["id"]] and out["escalated"] == []


def test_the_daily_stuck_sweep_also_leaves_a_task_alone_until_its_due_date(api):
    store = api.app.state.store
    with store.transaction() as c:
        later = H.task_create(c, H.human_actor("ana"), "Measure after the crawl", "When Google has recrawled.",
                              "bot:finance", due=H.shift(H.now(), seconds=5 * 86400))
        late = H.task_create(c, H.human_actor("ana"), "Reconcile last month", "The month is closed.", "bot:finance")
        c.execute("UPDATE jobs SET state='completed'")
        for t in (later, late):
            c.execute("UPDATE tasks SET updated=? WHERE id=?", (H.shift(H.now(), seconds=-2 * 86400), t["id"]))
        ids = [t["id"] for t in H.stuck_tasks(c)]
        assert later["id"] not in ids and late["id"] in ids
