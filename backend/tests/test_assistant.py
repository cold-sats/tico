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
    made = post(api, "tasks", {"owner": "human:ben", "title": "Draft the launch post", "body": "For Oct 1."}, token=token)
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
    with api.app.state.store.transaction() as c:      # archived before the assistant was built in
        c.execute("UPDATE bots SET state='archived' WHERE slug='coo'")
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


def running_proposal(api, person="ana-test"):
    """A proposal as if the person had clicked Confirm and it is still being run."""
    action = post(api, "assistant/actions", {"summary": "Archive the Ops bot", "path": "/api/v2/bots/ops/archive",
                                             "body": {"expected_revision": 1}}, token=person)["action"]
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE assistant_actions SET status='running', running_since=?, confirm_hash=? WHERE id=?",
                  (H.now(), "0" * 64, action["id"]))
    return action


def test_a_proposal_cannot_smuggle_a_route_and_never_stores_an_answer(api):
    for path in ("/api/v2//me/tokens", "/api/v2/me/tokens", "/api/v2/tasks/../me/tokens", "/api/v2/me%2Ftokens",
                 "/api/v2/tasks\\x", "/api/v2/tasks/", "/api/v2/runners/enrollments", "/auth/token", "/api/v2/assistant/turn-on"):
        post(api, "assistant/actions", {"summary": "Do it", "path": path}, token="ana-test", expected=422)
    # The stored path is exactly what runs; only the status and an error detail are kept, never the answer.
    action = post(api, "assistant/actions", {"summary": "File it", "path": "/api/v2/tasks",
                                             "body": {"title": "Draft the launch plan", "body": "Two pages.", "owner": "human:ana"}})["action"]
    done = post(api, f"assistant/actions/{action['id']}/confirm", {})["action"]
    assert done["status"] == "done" and set(done["result"]) == {"status_code", "error"}
    assert "Draft the launch plan" not in str(get(api, f"assistant/actions/{action['id']}")["action"]["result"])


def test_the_assistant_cannot_confirm_its_own_proposal(api):
    r, attempt = assistant_turn(api, "ana-test")
    token = attempt["token"]
    action = running_proposal(api)
    for header in (action["id"], action["id"] + ".guess", action["id"] + "." + "0" * 64):
        forged = api.post("/api/v2/bots/ops/archive", json={"expected_revision": 1},
                          headers={**headers(token), "x-tico-assistant-action": header})
        assert forged.status_code == 403
    with api.app.state.store.read() as c:
        assert H.bot(c, "ops")["state"] != "archived"
    # A confirm that never settled cannot stay a bypass: after two minutes it has failed.
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE assistant_actions SET running_since=? WHERE id=?", (H.shift(H.now(), seconds=-200), action["id"]))
    assert get(api, "assistant")["pending"] == []
    assert get(api, f"assistant/actions/{action['id']}")["action"]["status"] == "failed"


def test_an_assistant_message_never_lends_the_persons_authority_to_botops(api):
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO bots(slug,display_name,runtime,model,effort,cwd,host,state,created) "
                  "VALUES('botops','BotOps','fake','','','','keeper','active',?)", (H.now(),))
        c.execute("INSERT INTO bot_config(bot,config_json,team,operator) VALUES('botops','{}',NULL,'ana')")
        H.VIA.set("assistant")
        via = H.say(c, "human:ana", "bot:botops", "Rename the Ops bot to Operations", kind="say")
        H.VIA.set("")
        plain = H.say(c, "human:ana", "bot:botops", "Rename the Ops bot to Operations, please", kind="say")
    assert via["refs"].get("via") == "assistant" and "via" not in plain["refs"]
    r = runner(api)
    assign(api, r, "botops")
    ready(api, r, ["botops"])
    token = claim(api, r, "botops")["token"]
    body = {"display_name": "Operations", "expected_revision": 1}
    refused = post(api, "bots/ops/definition", {**body, "on_behalf_of": via["id"]}, token=token, expected=403)
    assert "written by the Assistant" in refused["error"]["detail"]
    other = api.post("/api/v2/bots/ops/definition", json={**body, "on_behalf_of": plain["id"]}, headers=headers(token))
    assert "written by the Assistant" not in other.text


def test_the_proposal_says_what_it_will_do_in_the_servers_words(api):
    with api.app.state.store.transaction() as c:
        task = H.task_create(c, "human:ben", "Pick the launch date", "Oct 1 or Oct 8?", "human:ana")
    action = post(api, "assistant/actions", {"summary": "Just a small change", "path": "/api/v2/tasks/" + task["id"],
                                             "body": {"version": task["version"], "status": "done", "note": "ok"}})["action"]
    assert "Pick the launch date" in action["description"] and "small change" not in action["description"]
    assert {"field": "status", "old": "open", "new": "done"} in action["diff"]
    archive = post(api, "assistant/actions", {"summary": "Housekeeping", "path": "/api/v2/bots/ops/archive",
                                              "body": {"expected_revision": 1}})["action"]
    assert archive["description"] == "Archive bot ops"


def test_direct_writes_only_ever_touch_the_person_themself(api):
    with api.app.state.store.transaction() as c:
        theirs = H.task_create(c, "human:ana", "Review the plan", "Please review.", "human:ben")
        anas = H.task_create(c, "human:ben", "Ana's own item", "For Ana to decide.", "human:ana")
    r, attempt = assistant_turn(api, "ben-test")
    token = attempt["token"]
    # Nothing that reaches someone else, or a bot, runs directly.
    post(api, "tasks", {"owner": "ops", "title": "Draft the launch post", "body": "For Oct 1."}, token=token, expected=403)
    post(api, "tasks", {"owner": "human:cara", "title": "Review the plan", "body": "Please."}, token=token, expected=403)
    post(api, "messages", {"to": "ops", "text": "Hello"}, token=token, expected=403)
    post(api, "chat/ops", {"text": "Hello"}, token=token, expected=403)
    post(api, f"tasks/{theirs['id']}/run-now", {}, token=token, expected=403)
    post(api, f"tasks/{theirs['id']}", {"version": theirs["version"], "owner": "ops"}, token=token, expected=403)
    post(api, f"tasks/{anas['id']}", {"version": anas["version"], "note": "x"}, token=token, expected=403)   # not ben's
    # Their own work, comments and reading updates are theirs to do.
    post(api, "tasks", {"owner": "human:ben", "title": "Draft my week", "body": "Monday first."}, token=token)
    post(api, f"tasks/{theirs['id']}", {"version": theirs["version"], "note": "On it"}, token=token)
    post(api, f"tasks/{theirs['id']}/comments", {"text": "Started"}, token=token)
    post(api, "updates/read", {"all": True}, token=token)


def test_the_assistant_and_botops_cannot_be_archived_or_deleted_but_can_be_paused(api):
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO bots(slug,display_name,runtime,model,effort,cwd,host,state,created) "
                  "VALUES('botops','BotOps','fake','','','','keeper','active',?)", (H.now(),))
        c.execute("INSERT INTO bot_config(bot,config_json,team,operator) VALUES('botops','{}',NULL,'ana')")
    for bot in ("coo", "botops"):
        for token in ("ana-test", "ben-test"):                       # the owner too
            refused = post(api, f"bots/{bot}/archive", {"expected_revision": 1}, token=token, expected=409)
            assert refused["error"]["code"] == "system_bot"
        assert api.delete(f"/api/v2/bots/{bot}", headers=headers()).status_code in (404, 405)
        with api.app.state.store.read() as c:
            revision = c.execute("SELECT revision FROM bot_config WHERE bot=?", (bot,)).fetchone()[0]
        post(api, f"bots/{bot}/definition", {"status": "paused", "expected_revision": revision})
        with api.app.state.store.read() as c:
            assert H.bot(c, bot)["state"] == "paused"
