"""The Assistant (backend/assistant.py, docs/assistant.md): a private room per person, a fast path that
needs no bot turn, a bot turn that acts as the person and never more, and side effects that wait for the
person's own click."""

import pytest

from backend.tests.test_api import api, assign, claim, get, headers, post, ready, runner  # noqa: F401
from backend.store import H


def room(api, token="ana-test"):
    return get(api, "assistant", token)


def say(api, text, token="ana-test", expected=200):
    return post(api, "assistant/messages", {"text": text}, token=token, expected=expected)


def jobs(api):
    with api.app.state.store.read() as c:
        return c.execute("SELECT count(*) FROM jobs").fetchone()[0]


def assistant_turn(api, person, text="Please plan my week around the launch"):
    """The assistant bot's runner turn for a message this person sent in their Assistant room."""
    r = runner(api)
    assign(api, r, "coo")
    ready(api, r, ["coo"])
    said = say(api, text, person)
    assert said["fast"] is False
    return r, claim(api, r)


def test_only_the_owner_of_an_assistant_room_reads_or_posts_in_it(api):
    ana, ben = room(api, "ana-test"), room(api, "ben-test")
    assert ana["available"] and ana["room_id"] and ana["room_id"] != ben["room_id"]
    assert room(api, "ana-test")["room_id"] == ana["room_id"]          # one room each, however often asked
    say(api, "My private question about the launch", "ana-test", expected=200)
    # Not the other person, and not the company owner either.
    get(api, f"conversations/{ana['room_id']}/messages", "ben-test", expected=403)
    get(api, f"conversations/{ben['room_id']}/messages", "ana-test", expected=403)
    post(api, "messages", {"to": "coo", "text": "Injected", "conversation_id": ana["room_id"]}, token="ben-test",
         expected=403)
    post(api, "messages", {"to": "coo", "text": "Injected", "conversation_id": ben["room_id"]}, token="ana-test",
         expected=403)
    post(api, "chat/coo", {"text": "Anywhere else"}, token="ben-test", expected=403)
    assert [m["body"] for m in room(api, "ben-test")["messages"]] == []
    # The owner of the room may also use the generic message route; the server marks the turn.
    ok = post(api, "messages", {"to": "coo", "text": "Also fine", "conversation_id": ana["room_id"]})
    assert ok["refs"]["assistant"] is True


def test_the_assistant_acts_as_the_person_and_never_more(api):
    with api.app.state.store.transaction() as c:      # the private inbox bot's work: ana's, not ben's
        secret = H.task_create(c, "human:ana", "Review the private mail", "Nothing for ben.", "bot:inbox")["id"]
    r, attempt = assistant_turn(api, "ben-test")
    token = attempt["token"]
    assert get(api, "me", token)["actor"] == "human:ben"           # its tools are ben's, not the bot's
    # What ben may not see or touch, his Assistant may not.
    get(api, "tasks/" + secret, token, expected=403)
    post(api, "tasks/" + secret + "/comments", {"text": "Looking"}, token=token, expected=403)
    # Nothing that changes settings, people or bots runs on its own, whoever it acts for.
    post(api, "bots/ops/archive", {"expected_revision": 1}, token=token, expected=403)
    assert api.put("/api/v2/providers", json={}, headers=headers(token)).json()["error"]["code"] == "confirm_required"
    # Settling a task is deciding a Needs-you item: it is proposed, never done directly.
    mine = post(api, "tasks", {"owner": "human:ben", "title": "Pick the launch date", "body": "Oct 1 or Oct 8?"}, token=token)
    post(api, "tasks/" + mine["id"], {"version": mine["version"], "status": "done"}, token=token, expected=403)
    # A low-risk write runs directly, as ben, and says so in the record.
    made = post(api, "tasks", {"owner": "ops", "title": "Draft the launch post", "body": "For Oct 1."}, token=token)
    assert made["requester"] == "human:ben"
    with api.app.state.store.read() as c:
        assert c.execute("SELECT via FROM task_events WHERE task_id=? ORDER BY ts LIMIT 1", (made["id"],)).fetchone()[0] == "assistant"
        assert c.execute("SELECT count(*) FROM events WHERE detail_json LIKE '%\"via\": \"assistant\"%'").fetchone()[0] > 0
    # The runner's own lease calls are still the runner's.
    post(api, f"attempts/{attempt['id']}/renew", {}, token=r["token"], expected=200)


def test_a_side_effect_runs_only_after_the_person_confirms(api):
    r, attempt = assistant_turn(api, "ana-test")
    token = attempt["token"]
    with api.app.state.store.read() as c:
        revision = c.execute("SELECT revision FROM bot_config WHERE bot='ops'").fetchone()[0]
    operation = {"summary": "Archive the Ops bot", "method": "POST", "path": "/api/v2/bots/ops/archive",
                 "body": {"expected_revision": revision}}
    # The bot cannot do it itself, and only proposes.
    post(api, "bots/ops/archive", operation["body"], token=token, expected=403)
    action = post(api, "assistant/actions", operation, token=token)["action"]
    assert action["status"] == "pending" and action["owner"] == "human:ana"
    post(api, "assistant/actions", {**operation, "path": "/api/v2/me/tokens"}, token=token, expected=422)

    def archived():
        with api.app.state.store.read() as c:
            return H.bot(c, "ops")["state"] == "archived"
    assert not archived()
    # It cannot confirm its own proposal, nobody else can see it, and nothing has run.
    post(api, f"assistant/actions/{action['id']}/confirm", {}, token=token, expected=403)
    post(api, f"assistant/actions/{action['id']}/confirm", {}, token="ben-test", expected=404)
    post(api, f"assistant/actions/{action['id']}/cancel", {}, token=token, expected=403)
    assert not archived()
    # The person's own click runs it, as them, via the assistant.
    done = post(api, f"assistant/actions/{action['id']}/confirm", {}, token="ana-test")["action"]
    assert done["status"] == "done" and done["result"]["status_code"] == 200, done["result"]
    assert archived()
    post(api, f"assistant/actions/{action['id']}/confirm", {}, token="ana-test", expected=409)   # once
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM events WHERE action='assistant.action.confirmed'").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM events WHERE action LIKE 'bot.%' AND detail_json LIKE '%\"via\": \"assistant\"%'"
                         ).fetchone()[0] >= 1
    # A cancelled proposal never runs.
    other = post(api, "assistant/actions", {"summary": "Archive Finance", "path": "/api/v2/bots/finance/archive",
                                            "body": {"expected_revision": 1}}, token="ana-test")["action"]
    post(api, f"assistant/actions/{other['id']}/cancel", {}, token="ana-test")
    post(api, f"assistant/actions/{other['id']}/confirm", {}, token="ana-test", expected=409)


def test_the_fast_path_answers_without_a_bot_turn(api):
    post(api, "tasks", {"owner": "ana", "title": "Pick a launch date", "body": "Which date: Oct 1 or Oct 8?"},
         token="ben-test")
    before = jobs(api)
    waiting = say(api, "What's waiting on me?")
    assert waiting["fast"] and waiting["intent"] == "waiting"
    assert "[Pick a launch date](#/task/" in waiting["reply"]["body"]
    how = say(api, "How do I import a meeting?")
    assert how["fast"] and how["intent"] == "help"
    assert "github.com/ticoteam/tico/blob/main/docs/" in how["reply"]["body"]
    found = say(api, "find launch date")
    assert found["fast"] and "Pick a launch date" in found["reply"]["body"]
    assert jobs(api) == before                                      # no runner turn, no model
    # Anything that asks for something to be done is the bot's.
    turn = say(api, "Please ask Ops to draft the launch post")
    assert not turn["fast"] and jobs(api) == before + 1
    assert [m["body"] for m in room(api)["messages"]][-1] == "Please ask Ops to draft the launch post"


def test_the_owner_turns_an_archived_assistant_back_on_for_everyone(api):
    """A company that set the assistant aside at setup (v0.2.1) gets it back with one owner action."""
    from backend.settings_admin import archive_bot
    with api.app.state.store.transaction() as c:
        archive_bot(c, "human:ana", "coo", "")
    off = room(api, "ben-test")
    assert not off["available"] and off["state"] == "archived" and off["room_id"] is None
    assert not off["can_turn_on"] and room(api, "ana-test")["can_turn_on"]          # only the owner is offered it
    say(api, "Hello?", "ben-test", expected=409)                                     # off is a plain answer, not a crash
    post(api, "assistant/turn-on", {}, token="ben-test", expected=403)
    # No computer yet: restored (planned again, history kept) and waiting for one.
    waiting = post(api, "assistant/turn-on", {}, token="ana-test")
    assert waiting["restored"] and waiting["state"] == "planned" and not waiting["placed"]
    assert not room(api, "ben-test")["available"] and room(api, "ana-test")["can_turn_on"]
    runner(api)                                                                       # a computer enrolls
    on = post(api, "assistant/turn-on", {}, token="ana-test")
    assert on["state"] == "active" and on["placed"]
    for person in ("ana-test", "ben-test"):                                           # everyone's Assistant works
        view = room(api, person)
        assert view["available"] and view["room_id"] and not view["can_turn_on"]
        assert say(api, "What's waiting on me?", person)["fast"]
    assert post(api, "assistant/turn-on", {}, token="ana-test")["state"] == "active"  # idempotent
