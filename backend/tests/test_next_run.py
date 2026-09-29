"""Next-run tasks: work filed for a bot's next run instead of waking it.

Ben's release audit filed one task per monitor bot every morning, and each one started a run
there and then, to read a note the monitor only needed on its own daily check. A next-run task
waits: nothing is queued, and the next run the bot has for any reason carries it in the same
prompt as a task of its own. Closing it before then is a cancel and wakes nobody. (2026-09-24.)
"""

from backend.tests.test_api import api, assign, get, headers, post, ready, runner  # noqa: F401
from backend.store import H


def claim(api, r, next_run=True):
    return post(api, "jobs/claim", {"next_run": next_run}, token=r["token"])["attempt"]


def later(api, **more):
    return post(api, "tasks", {"owner": "ops", "title": "Watch the new refund requests",
                               "body": "Released today; check the counts on your next run.",
                               "next_run": True, **more})


def setup(api):
    r = runner(api)
    assign(api, r, "ops")
    ready(api, r, ["ops"])
    return r


def jobs(api, bot="ops"):
    with api.app.state.store.read() as c:
        return c.execute("SELECT count(*) FROM jobs WHERE bot=?", (bot,)).fetchone()[0]


def listed(api, slug="ops"):
    return next(row for row in get(api, "bots") if row["slug"] == slug)


def test_filing_one_starts_nothing_and_shows_as_waiting(api):
    r = setup(api)
    task = later(api)
    assert task["next_run"] is True and task["next_run_waiting"] is True
    assert jobs(api) == 0, "no run was queued for it"
    assert claim(api, r) is None
    assert listed(api)["next_run"] == 1
    # The board lists it with the same word, one query for the page.
    listed_task = next(t for t in get(api, "tasks?owner=bot:ops&status=open")["tasks"] if t["id"] == task["id"])
    assert listed_task["next_run"] is True and listed_task["next_run_waiting"] is True
    assert listed(api)["queued"] == 0, "and it is not counted as queued work"
    # The notice is still in the bot's room, written quietly.
    messages = get(api, f"conversations/{task['conversation_id']}/messages")
    assert any(m["body"].startswith("New task from") and (m.get("refs") or {}).get("quiet") for m in messages)


def test_the_next_run_carries_it_in_the_same_prompt(api):
    r = setup(api)
    task = later(api)
    post(api, "chat/ops", {"text": "How are the numbers today?"})
    attempt = claim(api, r)
    assert attempt["message"]["body"] == "How are the numbers today?", "what woke it is still the message"
    assert [t["id"] for t in attempt["next_run"]] == [task["id"]]
    assert attempt["next_run"][0]["title"] == "Watch the new refund requests"
    assert get(api, "tasks/" + task["id"])["task"]["next_run_waiting"] is False
    assert listed(api)["next_run"] == 0


def test_a_runner_that_cannot_carry_them_never_takes_them(api):
    # An older runner claims with `{}`: marking its run as the carrier would lose the task.
    r = setup(api)
    task = later(api)
    post(api, "chat/ops", {"text": "Anything new?"})
    attempt = claim(api, r, next_run=False)
    assert attempt["next_run"] == []
    assert get(api, "tasks/" + task["id"])["task"]["next_run_waiting"] is True


def test_a_run_that_fails_gives_it_back(api):
    r = setup(api)
    task = later(api)
    post(api, "chat/ops", {"text": "First"})
    first = claim(api, r)
    post(api, f"attempts/{first['id']}/started", {"thread_id": "t1"}, token=r["token"])
    post(api, f"attempts/{first['id']}/complete", {"outcome": "failed", "text": "boom", "last_seq": 0},
         token=r["token"])
    assert get(api, "tasks/" + task["id"])["task"]["next_run_waiting"] is True
    with api.app.state.store.transaction() as c:   # clear the review hold the failure left
        c.execute("UPDATE jobs SET state='cancelled' WHERE state='uncertain'")
    post(api, "chat/ops", {"text": "Second"})
    assert [t["id"] for t in claim(api, r)["next_run"]] == [task["id"]]


def test_a_finished_run_does_not_carry_it_twice(api):
    r = setup(api)
    later(api)
    post(api, "chat/ops", {"text": "First"})
    first = claim(api, r)
    post(api, f"attempts/{first['id']}/started", {"thread_id": "t1"}, token=r["token"])
    post(api, f"attempts/{first['id']}/complete", {"outcome": "completed", "text": "Done.", "last_seq": 0},
         token=r["token"])
    post(api, "chat/ops", {"text": "Second"})
    assert claim(api, r)["next_run"] == []


def test_closing_it_before_a_run_is_a_cancel_that_wakes_nobody(api):
    setup(api)
    task = later(api)
    post(api, "tasks/" + task["id"], {"version": task["version"], "close": True, "note": "Not needed after all"})
    assert jobs(api) == 0, "a note on a close would normally wake the owner; not for a task it never saw"
    assert listed(api)["next_run"] == 0


def test_only_a_bot_has_a_next_run(api):
    r = api.post("/api/v2/tasks", json={"owner": "human:ben", "title": "Decide the price",
                                        "body": "Pick one of the two.", "next_run": True},
                 headers=headers())
    assert r.status_code >= 400
    assert "next run" in r.text


def test_an_ordinary_task_still_wakes_as_before(api):
    r = setup(api)
    task = post(api, "tasks", {"owner": "ops", "title": "Check the counts now", "body": "Today."})
    assert task["next_run"] is False and "next_run_waiting" not in task
    attempt = claim(api, r)
    assert attempt["task"]["id"] == task["id"]
    assert attempt["next_run"] == []


def test_waiting_is_worked_out_the_same_way_in_sql_and_python(api):
    setup(api)
    task = later(api)
    with api.app.state.store.read() as c:
        row = H.task(c, task["id"])
        assert H.next_run_waiting(c, row) is True
        assert [t["id"] for t in H.next_run_tasks(c, "ops")] == [task["id"]]
        assert H.next_run_tasks(c, "ops", exclude=task["id"]) == []


# ---- running one now (Ben, 2026-09-24: "it should just be able to just run it")

def test_run_now_starts_it_as_the_task_not_as_a_chat(api):
    r = setup(api)
    task = later(api)
    got = post(api, f"tasks/{task['id']}/run-now", {})
    assert got["queued"] is True
    assert got["task"]["next_run"] is False, "it is an ordinary task now"
    attempt = claim(api, r)
    assert attempt["task"]["id"] == task["id"], "the run is the task"
    assert attempt["task"]["body"].startswith("Released today"), "and carries its own text"
    assert attempt["message"]["body"].startswith("Run now: Watch the new refund requests")
    assert attempt["message"]["from_actor"] != "human:ana", "no chat message in the person's name"
    assert attempt["next_run"] == [], "and it is not carried a second time"


def test_run_now_twice_queues_one_run(api):
    setup(api)
    task = later(api)
    assert post(api, f"tasks/{task['id']}/run-now", {})["queued"] is True
    assert post(api, f"tasks/{task['id']}/run-now", {})["queued"] is False
    assert jobs(api) == 1


def test_run_now_needs_an_open_bot_task(api):
    setup(api)
    task = later(api)
    post(api, "tasks/" + task["id"], {"version": task["version"], "close": True, "note": "Not needed"})
    r = api.post(f"/api/v2/tasks/{task['id']}/run-now", json={}, headers=headers())
    assert r.status_code >= 400 and "closed" in r.text
