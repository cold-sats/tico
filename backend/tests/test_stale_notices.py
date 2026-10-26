"""A notice that news has overtaken is dropped at claim, not run (backend/execution.obsolete_notices_sql): a status
check of a quiet task its owner has acted on since, and a pull request's checks result for a head the pull request
has moved past. A notice that is still news runs."""
import json

from backend.store import H
from backend.tests.test_api import api, assign, claim, ready, runner  # noqa: F401


def fleet(api):
    r = runner(api)
    assign(api, r, "ops")
    ready(api, r, ["ops"])
    return r


def task(c, title="Fix the connection"):
    return H.task_create(c, "human:ana", title, "Build.", "bot:ops")


def job(api, message):
    with api.app.state.store.read() as c:
        return c.execute("SELECT id FROM jobs WHERE message_id=?", (message["id"],)).fetchone()[0]


def queued(c, message):
    return c.execute("SELECT state FROM jobs WHERE message_id=?", (message["id"],)).fetchone()[0]


def test_a_status_check_the_owner_has_acted_on_since_is_dropped(api):
    r = fleet(api)
    with api.app.state.store.transaction() as c:
        row, other = task(c), task(c, "Fix the login")
        c.execute("UPDATE jobs SET state='cancelled' WHERE bot='ops'")         # the new-task notices are not this test
        c.execute("UPDATE task_events SET ts=? WHERE task_id IN (?,?)", (H.shift(H.now(), minutes=-10), row["id"], other["id"]))
        quiet, kept = (H._wake(c, t, "bot:ops", "Status check: no activity for 2 h.", {"wake": "step_status"},
                               trigger="stall_check") for t in (row, other))
        c.execute("UPDATE messages SET created=? WHERE id IN (?,?)", (H.shift(H.now(), minutes=-5), quiet["id"], kept["id"]))
        H.task_update(c, "bot:ops", row["id"], note="Pushed the fix.")
    handed = [claim(api, r), claim(api, r)]
    with api.app.state.store.read() as c:
        assert queued(c, quiet) == "cancelled"
    assert [a["job_id"] for a in handed if a] == [job(api, kept)], "a task nobody touched still gets its check"


def test_checks_news_for_a_head_the_pull_request_moved_past_is_dropped(api):
    r = fleet(api)
    with api.app.state.store.transaction() as c:
        row = task(c)
        c.execute("UPDATE jobs SET state='cancelled' WHERE bot='ops'")
        c.execute("INSERT INTO task_links(id,task_id,kind,url,state,added_by,created,detail_json) "
                  "VALUES('l1',?,'pr','https://github.example/acme/app/pull/7','open','bot:ops',?,?)",
                  (row["id"], H.now(), json.dumps({"head_sha": "b" * 40})))
        old = H._wake(c, row, "bot:ops", "Checks failed on aaaaaaa.",
                      {"wake": "pr_checks_done", "pr_head": "a" * 40, "pr_result": "fail"}, trigger="pr_checks")
        new = H._wake(c, row, "bot:ops", "Checks failed on bbbbbbb.",
                      {"wake": "pr_checks_done", "pr_head": "b" * 40, "pr_result": "fail"}, trigger="pr_checks")
    handed = [claim(api, r), claim(api, r)]
    with api.app.state.store.read() as c:
        assert queued(c, old) == "cancelled"
    assert [a["job_id"] for a in handed if a] == [job(api, new)], "the result for the head it is at still runs"
