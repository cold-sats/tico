"""An unanswered ask leaves a person's queue when a newer ask or the task's end replaces it, or when it grows old."""
from backend.tests.test_api import api, headers, post  # noqa: F401
from backend.store import H


def needs(api, who="ana-test"):
    response = api.get("/api/v2/needs-you", headers=headers(who))
    assert response.status_code == 200, response.text
    return response.json()


def bot_ask(c, tid, text, refs=None):
    task = H.task(c, tid)
    return H.say(c, "bot:ops", "human:ana", text, kind="ask", conversation_id=task["conversation_id"],
                 refs={"task": tid, **(refs or {})})


def test_a_newer_ask_or_the_tasks_end_supersedes_and_old_asks_fold_out(api):
    tid = post(api, "tasks", {"owner": "ops", "title": "Pick a vendor", "body": "x"})["id"]
    other = post(api, "tasks", {"owner": "ops", "title": "Pick a venue", "body": "x"})["id"]
    with api.app.state.store.transaction() as c:
        first = bot_ask(c, tid, "Which vendor, A or B?")
        second = bot_ask(c, tid, "Vendor B is out of stock; is A fine?")
        assert [a["id"] for a in H.open_task_asks(c, H.task(c, tid))] == [second["id"]]
        assert H.message(c, first["id"])["superseded_at"] and not H.message(c, second["id"])["superseded_at"]
        assert H.waiting_for(c, H.task(c, tid)) == "an unanswered question"
        review = bot_ask(c, tid, "Approve the order?", {"questions": [{"id": "ok", "question": "Approve?"}]})
        H.task_update(c, "bot:ops", tid, status="done", note="Ordered")
        # done keeps the structured review question open; closing ends every one
        assert [a["id"] for a in H.open_task_asks(c, H.task(c, tid))] == [review["id"]]
        H.task_close(c, "human:ana", tid)
        assert H.open_task_asks(c, H.task(c, tid)) == []
        old = bot_ask(c, other, "Indoor or outdoor?")
        c.execute("UPDATE messages SET created=? WHERE id=?", (H.shift(H.now(), days=-4), old["id"]))
    queue = needs(api)
    assert tid not in [i["id"] for i in queue["items"]] + [i["id"] for i in queue["older"]]
    assert other not in [i["id"] for i in queue["items"]] and [i["id"] for i in queue["older"]] == [other]
    assert api.get("/api/v2/needs-you?count=1", headers=headers()).json()["count"] == len(queue["items"])
