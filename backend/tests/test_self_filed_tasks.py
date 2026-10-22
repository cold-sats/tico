"""A bot that files a task for itself in one of its turns, and a turn Tico woke that changed nothing (Dev 359).

The task's own turn starts once the filing turn has ended, never beside it: a task the filing turn finished by then
starts no turn at all. A turn Tico woke on a task already finished that wrote nothing posts no reply to the person;
its text stays on the run."""
from backend.store import H
from backend.tests.test_api import api, claim, get, post  # noqa: F401  (api is a fixture)
from backend.tests.test_run_triggers import finish, machine, start
from backend.tests.test_task_lanes import new_task, task_bot


def busy(api, machine):
    """ops's turn on a task a person filed, started."""
    new_task(api, "plan the week")
    active = claim(api, machine)
    post(api, f"attempts/{active['id']}/started", {"thread_id": active["lane"]}, machine["token"])
    return active


def done(api, task_id, token):
    version = get(api, "tasks/" + task_id, token)["task"]["version"]
    post(api, "tasks/" + task_id, {"version": version, "status": "done"}, token)


def complete(api, machine, attempt, text="Done."):
    post(api, f"attempts/{attempt['id']}/complete", {"outcome": "completed", "last_seq": 0, "text": text},
         machine["token"])


def test_a_task_a_bot_files_for_itself_starts_once_the_filing_turn_ends(api):
    machine = task_bot(api, lanes=True)
    active = busy(api, machine)
    mine = post(api, "tasks", {"owner": "ops", "title": "Tidy the roadmap", "body": "Close stale items."},
                token=active["token"])
    assert claim(api, machine) is None
    # A task a person files still starts beside the turn.
    other = new_task(api, "release notes")
    assert claim(api, machine)["lane"] == "task:" + other["id"]
    complete(api, machine, active)
    after = claim(api, machine)
    assert (after["lane"], H.message_task_id(after["message"])) == ("task:" + mine["id"], mine["id"])


def test_a_task_the_filing_turn_finished_starts_no_turn(api):
    machine = task_bot(api, lanes=True)
    active = busy(api, machine)
    order = post(api, "tasks", {"owner": "ops", "title": "Spec to top of roadmap when ready",
                                "body": "Standing order: move it when routines land."}, token=active["token"])
    # Claims come between the filing and the finishing: none starts the task beside the turn that filed it.
    assert claim(api, machine) is None
    done(api, order["id"], active["token"])
    complete(api, machine, active)
    assert claim(api, machine) is None
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM turns WHERE task_id=?", (order["id"],)).fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM events WHERE action='job.suppress' AND json_extract(detail_json,"
                         "'$.task_id')=?", (order["id"],)).fetchone()[0] == 1


def replies(api, task):
    with api.app.state.store.read() as c:
        return [b for (b,) in c.execute("SELECT body FROM messages WHERE from_actor='bot:ops' AND to_actor LIKE "
                                        "'human:%' AND conversation_id=? ORDER BY rowid", (task["conversation_id"],))]


def test_a_tico_wake_on_a_finished_task_that_changed_nothing_posts_no_reply(api):
    r = machine(api)
    task = post(api, "tasks", {"owner": "ops", "title": "Hold the spec", "body": "Hold it until routines land."})
    first = claim(api, r)
    start(api, r, first)
    done(api, task["id"], first["token"])
    finish(api, r, first, "Held: it moves when routines land.")
    assert replies(api, task) == ["Held: it moves when routines land."]
    with api.app.state.store.transaction() as c:
        H._wake(c, H.task(c, task["id"]), "bot:ops", "Unblocked: Hold the spec")
    again = claim(api, r)
    start(api, r, again)
    finish(api, r, again, "Nothing changed: still holding.")
    assert replies(api, task) == ["Held: it moves when routines land."]
    with api.app.state.store.read() as c:
        assert c.execute("SELECT final_text FROM attempts WHERE id=?", (again["id"],)).fetchone()[0] \
            == "Nothing changed: still holding."
        assert c.execute("SELECT count(*) FROM events WHERE action='reply.withheld' AND target=?",
                         (again["id"],)).fetchone()[0] == 1
    # A turn that wrote something still reports it.
    with api.app.state.store.transaction() as c:
        H._wake(c, H.task(c, task["id"]), "bot:ops", "Routines landed")
    third = claim(api, r)
    start(api, r, third)
    post(api, f"tasks/{task['id']}/comments", {"text": "Moved to Approved."}, third["token"])
    finish(api, r, third, "Moved it to Approved.")
    assert replies(api, task)[-1] == "Moved it to Approved."


def test_an_answer_on_an_open_task_still_reaches_the_person(api):
    """A turn whose reply is its whole work (a question filed as a task) writes nothing and still answers."""
    r = machine(api)
    task = post(api, "tasks", {"owner": "ops", "title": "Which bank feed is late?", "body": "Just tell me."})
    attempt = claim(api, r)
    start(api, r, attempt)
    finish(api, r, attempt, "The Monzo feed, by two days.")
    assert replies(api, task) == ["The Monzo feed, by two days."]
