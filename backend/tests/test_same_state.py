"""Token saving 3/9 (Dev 141): a stall or status check about a task that stands exactly as at its owner's last
checkpoint starts no run (backend/wake_rules.py same_state). Anything that differs, or anyone asking, still does."""

import json

from backend import hubdb as H
from backend import wake_rules as W
from backend.tests.test_api import api, assign, get, post, ready, runner  # noqa: F401
from backend.tests.test_wake_rules import skips


def jobs(c, bot):
    """Runs waiting to start (the checkpointing turn's own job is done)."""
    return c.execute("SELECT count(*) FROM jobs WHERE bot=? AND id NOT IN (SELECT job_id FROM attempts)",
                     (bot,)).fetchone()[0]


def setup(api):
    r = runner(api)
    assign(api, r, "ops")
    assign(api, r, "cpo")
    ready(api, r, ["ops", "cpo"])
    return r


def checkpointed(api, r, title="Build 3/9"):
    """A task of cpo's whose last completed turn left a checkpoint; returns the task id."""
    task = post(api, "tasks", {"owner": "cpo", "title": title, "body": "Build it."})
    attempt = post(api, "jobs/claim", {"next_run": True, "bot": "cpo"}, token=r["token"])["attempt"]
    assert attempt["task"]["id"] == task["id"]
    post(api, f"attempts/{attempt['id']}/started", {"thread_id": "t1"}, token=r["token"])
    post(api, f"attempts/{attempt['id']}/complete", {"outcome": "completed", "text": "Waiting on review.",
                                                     "last_seq": 0}, token=r["token"])
    return task["id"]


def check(c, tid, wake="status_check"):
    """The stall check the scheduler writes for a task that has not moved."""
    c.execute("DELETE FROM jobs WHERE id NOT IN (SELECT job_id FROM attempts)")
    task = H.task(c, tid)
    msg = H._wake(c, task, task["owner"], "Status check: anything to report?", {"wake": wake}, trigger="stall_check")
    return msg


def test_a_check_on_a_task_that_stands_as_at_the_checkpoint_is_skipped_and_logged(api):
    r = setup(api)
    tid = checkpointed(api, r)
    with api.app.state.store.transaction() as c:
        assert H.task(c, tid)["checkpoint_state"]
        msg = check(c, tid)
        assert jobs(c, "cpo") == 0
        assert msg["refs"]["quiet"] is True and msg["refs"][W.MARK] == "same_state"
        [logged] = skips(c)
        assert {k: logged["detail"][k] for k in ("bot", "task", "rule", "trigger")} == {
            "bot": "cpo", "task": tid, "rule": "same_state", "trigger": "stall_check"}
        # Nothing to carry to the next run: the check only asked whether anything moved.
        assert c.execute("SELECT count(*) FROM notes WHERE message_id=?", (msg["id"],)).fetchone()[0] == 0
        # And the skip itself changes nothing: the next check is skipped as well.
        check(c, tid, "stalled")
        assert jobs(c, "cpo") == 0 and len(skips(c)) == 2


def test_the_task_view_does_not_carry_the_stored_state(api):
    r = setup(api)
    tid = checkpointed(api, r)
    assert "checkpoint_state" not in get(api, "tasks/" + tid)["task"]


def test_no_checkpoint_means_the_check_runs(api):
    setup(api)
    with api.app.state.store.transaction() as c:
        task = H.task_create(c, "bot:ops", "Fresh", "Nothing yet", "bot:cpo")
        assert not H.task(c, task["id"])["checkpoint_state"]
        check(c, task["id"])
        assert jobs(c, "cpo") == 1 and skips(c) == []


def test_a_checkpoint_without_a_stored_state_means_the_check_runs(api):
    r = setup(api)
    tid = checkpointed(api, r)
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE tasks SET checkpoint_state=NULL WHERE id=?", (tid,))
        check(c, tid)
        assert jobs(c, "cpo") == 1


def changes(c, tid):
    """One change per entry, each made the way it happens, none by cpo itself."""
    other = H.task_create(c, "bot:ops", "Docs " + tid[:8], "Write them", "bot:ops")

    def comment():
        H.task_comment(c, "bot:ops", tid, "Heads up: the spec moved.")

    def status():
        c.execute("UPDATE tasks SET status='blocked' WHERE id=?", (tid,))

    def step():
        c.execute("UPDATE tasks SET step_id=(SELECT id FROM task_steps LIMIT 1) WHERE id=?", (tid,))

    def relation():
        c.execute("INSERT INTO task_relations(from_task,to_task,kind,created) VALUES(?,?,'related',?)",
                  (*sorted((other["id"], tid)), H.now()))

    def relation_state():
        relation()
        c.execute("DELETE FROM jobs WHERE id NOT IN (SELECT job_id FROM attempts)")
        c.execute("UPDATE tasks SET status='done' WHERE id=?", (other["id"],))

    def pr_head():
        c.execute("INSERT INTO task_links(id,task_id,kind,url,title,state,added_by,created,pr_sha,checks) "
                  "VALUES(?,?,'pr','https://github.com/o/r/pull/9','PR','open','bot:cpo',?,'abc','pending')",
                  ("lk" + tid[:8], tid, H.now()))

    def pr_checks():
        pr_head()
        c.execute("DELETE FROM jobs WHERE id NOT IN (SELECT job_id FROM attempts)")
        c.execute("UPDATE tasks SET checkpoint_state=? WHERE id=?", (W.state_of(c, H.task(c, tid)), tid))
        c.execute("UPDATE task_links SET checks='passing' WHERE task_id=?", (tid,))

    return {"comment": comment, "status": status, "step": step, "relation": relation,
            "relation state": relation_state, "pr head": pr_head, "pr checks": pr_checks}


def test_any_one_field_changed_means_the_check_runs(api):
    r = setup(api)
    for name in ("comment", "status", "step", "relation", "relation state", "pr head", "pr checks"):
        tid = checkpointed(api, r, "Task " + name)
        with api.app.state.store.transaction() as c:
            changes(c, tid)[name]()
            check(c, tid)
            assert jobs(c, "cpo") == 1, name
            assert not [s for s in skips(c) if s["detail"]["task"] == tid], name


def test_a_persons_comment_with_otherwise_the_same_state_runs(api):
    r = setup(api)
    tid = checkpointed(api, r)
    post(api, f"tasks/{tid}/comments", {"text": "Any update?"})          # the person who made the task
    with api.app.state.store.transaction() as c:
        check(c, tid)
        assert jobs(c, "cpo") == 1


def test_an_ask_a_person_made_is_never_held(api):
    r = setup(api)
    tid = checkpointed(api, r)
    with api.app.state.store.transaction() as c:
        c.execute("DELETE FROM jobs WHERE id NOT IN (SELECT job_id FROM attempts)")
        task = H.task(c, tid)
        msg = H._wake(c, task, "bot:cpo", "Status check", {"wake": "status_check", "needs_action": True},
                      trigger="stall_check")
        assert W.MARK not in msg["refs"] and jobs(c, "cpo") == 1


def test_wakes_that_are_not_plain_checks_still_run(api):
    r = setup(api)
    tid = checkpointed(api, r)
    for wake in ("stuck_retry", "stuck_cause", "restate_ask"):
        with api.app.state.store.transaction() as c:
            check(c, tid, wake)
            assert jobs(c, "cpo") == 1, wake


def test_someone_changing_the_task_during_the_turn_leaves_no_state_to_compare(api):
    r = setup(api)
    task = post(api, "tasks", {"owner": "cpo", "title": "Busy", "body": "Build it."})
    attempt = post(api, "jobs/claim", {"next_run": True, "bot": "cpo"}, token=r["token"])["attempt"]
    post(api, f"attempts/{attempt['id']}/started", {"thread_id": "t1"}, token=r["token"])
    post(api, f"tasks/{task['id']}/comments", {"text": "While you work: use blue."})   # a person, mid-turn
    post(api, f"attempts/{attempt['id']}/complete", {"outcome": "completed", "text": "Done.", "last_seq": 0},
         token=r["token"])
    with api.app.state.store.transaction() as c:
        assert H.task(c, task["id"])["checkpoint"] == "Done."
        assert not H.task(c, task["id"])["checkpoint_state"]
        check(c, task["id"])
        assert jobs(c, "cpo") == 1


def test_another_bots_task_is_not_held_for_this_bots_checkpoint(api):
    r = setup(api)
    tid = checkpointed(api, r)
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE tasks SET owner='bot:ops' WHERE id=?", (tid,))
        c.execute("DELETE FROM jobs WHERE id NOT IN (SELECT job_id FROM attempts)")
        task = H.task(c, tid)
        H._wake(c, task, "bot:ops", "Status check", {"wake": "status_check"}, trigger="stall_check")
        assert jobs(c, "ops") == 1
