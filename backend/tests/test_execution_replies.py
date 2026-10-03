"""Completion delivers new input answers without repeating this attempt's tool sends."""
import pytest

from backend.store import H, encode
from backend.tests.test_api import api, setup_attempt, post, get, ready, claim


def start(api, runner, attempt):
    post(api, f"attempts/{attempt['id']}/started", {"thread_id": "fixture-thread"}, runner["token"])


def finish(api, runner, attempt, text="No matching items.", replay=True):
    body = {"outcome": "completed", "last_seq": 0, "text": text}
    path = f"attempts/{attempt['id']}/complete"
    done = post(api, path, body, runner["token"], key="completion")
    if replay:
        assert post(api, path, body, runner["token"], key="completion") == done
    return done["message"]


@pytest.mark.parametrize("kind", ["say", "ask", "task", "folded"])
def test_equal_answers_to_distinct_inputs_are_delivered_once(api, kind):
    runner, first, attempt = setup_attempt(api)
    start(api, runner, attempt)
    assert finish(api, runner, attempt)["in_reply_to"] == first["id"]
    ready(api, runner, ["ops"])
    if kind == "task":
        task = post(api, "tasks", {"owner": "ops", "title": "Check the second folder", "body": "Check its contents"})
        with api.app.state.store.read() as c:
            second = H.message(c, c.execute("SELECT message_id FROM jobs WHERE state='queued' AND bot='ops'").fetchone()[0])
    else:
        second = post(api, "messages", {"to": "ops", "kind": "ask" if kind == "ask" else "say",
                      "text": "Check the second folder", "conversation_id": first["conversation_id"]})
    attempt = claim(api, runner)
    start(api, runner, attempt)
    if kind == "task":
        post(api, "tasks/" + task["id"], {"version": task["version"], "status": "done", "quiet": True}, attempt["token"])
    if kind == "folded":
        folded = post(api, "chat/ops", {"text": "Include the archive"})
        inputs = post(api, f"attempts/{attempt['id']}/inputs", {}, runner["token"])["messages"]
        assert [m["id"] for m in inputs] == [folded["id"]]
        post(api, f"attempts/{attempt['id']}/inputs/{folded['id']}/ack", {}, runner["token"])
    reply = finish(api, runner, attempt, replay=kind != "task")
    assert reply and reply["in_reply_to"] == second["id"]
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM messages WHERE from_actor='bot:ops' AND in_reply_to=?", (second["id"],)).fetchone()[0] == 1
        if kind == "folded":
            assert H.message(c, reply["id"])["refs"]["answers"] == [second["id"], folded["id"]]


@pytest.mark.parametrize("route", ["linked", "unlinked", "conversation"])
def test_current_attempt_tool_reply_is_not_duplicated(api, route):
    runner, origin, attempt = setup_attempt(api)
    start(api, runner, attempt)
    body = {"text": "Tool answer"}
    if route == "conversation":
        sent = post(api, f"conversations/{origin['conversation_id']}/messages", body, attempt["token"])["message"]
    else:
        body.update(to="human:ana", conversation_id=origin["conversation_id"])
        if route == "linked":
            body["in_reply_to"] = origin["id"]
        sent = post(api, "messages", body, attempt["token"])
    assert finish(api, runner, attempt, "Different summary" if route == "linked" else "Tool answer") is None
    rows = get(api, f"conversations/{origin['conversation_id']}/messages")
    assert [m["id"] for m in rows if m["from_actor"] == "bot:ops"] == [sent["id"]]
    ready(api, runner, ["ops"])
    second = post(api, "chat/ops", {"text": "Check again"})
    attempt = claim(api, runner)
    start(api, runner, attempt)
    assert finish(api, runner, attempt, "Tool answer")["in_reply_to"] == second["id"]


def test_untrusted_attempt_reference_cannot_suppress_a_new_answer(api):
    runner, origin, attempt = setup_attempt(api)
    start(api, runner, attempt)
    old = finish(api, runner, attempt)
    ready(api, runner, ["ops"])
    second = post(api, "chat/ops", {"text": "Check again"})
    attempt = claim(api, runner)
    # Even an old bot message naming the new attempt is not trusted provenance.
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE messages SET refs_json=? WHERE id=?", (encode({"turn_id": attempt["id"]}), old["id"]))
    start(api, runner, attempt)
    assert finish(api, runner, attempt)["in_reply_to"] == second["id"]
