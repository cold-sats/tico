"""The Librarian (backend/librarian.py, docs/librarian.md): a person's question goes to a private docs
conversation with the built-in bot, a bot asks with an ask message, and the Librarian acts as itself."""

import pytest

from backend import librarian
from backend.store import H
from backend.tests.test_api import api, assign, claim, get, headers, post, ready, runner  # noqa: F401

RESULTS = [{"type": "internal", "id": "d1", "path": "finance/refunds.md", "title": "Refund policy",
            "excerpt": "Refunds within 14 days", "score": 1.0},
           {"type": "linked", "id": "l1", "title": "Help centre", "url": "https://help.example.com",
            "kind": "website", "description": "", "score": 0.5}]


@pytest.fixture
def desk(api, monkeypatch):
    """A company with an active Librarian on a computer, and the docs search stubbed (stream A's route)."""
    seen = []

    async def search(request, question):
        seen.append(question)
        return RESULTS
    monkeypatch.setattr(librarian, "_search", search)
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO bots(slug,display_name,runtime,model,effort,cwd,host,state,created) "
                  "VALUES('librarian','Librarian','fake','','','','keeper','active',?)", (H.now(),))
        c.execute("INSERT INTO bot_config(bot,config_json,team,operator) VALUES('librarian','{}',NULL,'ana')")
    r = runner(api)
    assign(api, r, "librarian")
    ready(api, r, ["librarian"])
    api.seen, api.runner = seen, r
    return api


def ask(api, question, token="ana-test", expected=200, **more):
    return post(api, "docs/ask", {"question": question, **more}, token=token, expected=expected)


def test_a_question_goes_to_the_persons_private_docs_conversation_and_is_answered_there(desk):
    sent = ask(desk, "How long do refunds take?")
    assert sent["results"] == RESULTS and desk.seen == ["How long do refunds take?"]
    again = ask(desk, "And for gift cards?", conversation_id=sent["conversation_id"])
    assert again["conversation_id"] == sent["conversation_id"]                      # one conversation, follow-ups too
    # The Librarian takes the question as itself: its token is the bot's, never the person's.
    attempt = claim(desk, desk.runner)
    assert get(desk, "me", attempt["token"])["actor"] == "bot:librarian"
    post(desk, f"attempts/{attempt['id']}/started", {"thread_id": "t"}, token=desk.runner["token"])
    post(desk, f"attempts/{attempt['id']}/complete",
         {"outcome": "completed", "text": "14 days. [Internal doc · Refund policy](doc:d1)", "last_seq": 0},
         token=desk.runner["token"])
    snapshot = get(desk, f"conversations/{sent['conversation_id']}/snapshot")
    reply = next(m for m in snapshot["messages"] if m["from_actor"] == "bot:librarian")
    assert reply["in_reply_to"] in (sent["message_id"], again["message_id"])
    assert "Refund policy" in reply["body"]


def test_nobody_else_reads_or_posts_in_a_persons_docs_conversation_the_owner_included(desk):
    ana, ben = ask(desk, "What is our refund policy?"), ask(desk, "What is Ben's private question?", token="ben-test")
    assert ana["conversation_id"] != ben["conversation_id"]
    get(desk, f"conversations/{ben['conversation_id']}/messages", "ana-test", expected=403)      # the owner too
    get(desk, f"conversations/{ana['conversation_id']}/messages", "ben-test", expected=403)
    get(desk, f"conversations/{ana['conversation_id']}/snapshot", "cara-test", expected=403)
    ask(desk, "Sneaking in", token="ben-test", expected=403, conversation_id=ana["conversation_id"])
    post(desk, "messages", {"to": "librarian", "text": "Injected", "conversation_id": ana["conversation_id"]},
         token="ben-test", expected=403)
    # A conversation that is not a docs conversation is not a place to ask.
    other = post(desk, "chat/ops", {"text": "hi"})["conversation_id"]
    ask(desk, "Wrong room", expected=422, conversation_id=other)


def test_a_bot_asks_the_librarian_with_an_ask_message_and_the_final_text_is_the_answer(desk):
    ops = runner(desk, label="Ops Mac")
    assign(desk, ops, "ops")
    ready(desk, ops, ["ops"])
    post(desk, "chat/ops", {"text": "Please look at the refund docs"})
    turn = claim(desk, ops)
    question = post(desk, "messages", {"to": "librarian", "text": "How long do refunds take?", "kind": "ask",
                                       "wait_s": 60}, token=turn["token"])
    attempt = claim(desk, desk.runner)
    assert attempt["bot"] == "librarian"
    post(desk, f"attempts/{attempt['id']}/started", {"thread_id": "t"}, token=desk.runner["token"])
    post(desk, f"attempts/{attempt['id']}/complete", {"outcome": "completed", "text": "Not in the docs.", "last_seq": 0},
         token=desk.runner["token"])
    with desk.app.state.store.read() as c:
        assert H.answers_to(c, [question["id"]])[question["id"]]["body"] == "Not in the docs."
    ask(desk, "A bot uses hub docs ask, not this route", token=turn["token"], expected=403)


def test_asking_is_refused_plainly_when_the_librarian_is_off_and_only_the_owner_turns_it_on(api, monkeypatch):
    async def search(request, question):
        return []
    monkeypatch.setattr(librarian, "_search", search)
    assert get(api, "librarian")["available"] is False and get(api, "librarian")["can_turn_on"] is True
    assert get(api, "librarian", "ben-test")["can_turn_on"] is False
    assert ask(api, "Anyone there?", expected=409)["error"]["code"] == "librarian_off"
    post(api, "librarian/turn-on", {}, token="ben-test", expected=403)


def test_the_librarian_is_built_in_and_cannot_be_archived_but_can_be_paused(desk):
    for token in ("ana-test", "ben-test"):
        assert post(desk, "bots/librarian/archive", {"expected_revision": 1}, token=token,
                    expected=409)["error"]["code"] == "system_bot"
    with desk.app.state.store.read() as c:
        revision = c.execute("SELECT revision FROM bot_config WHERE bot='librarian'").fetchone()[0]
    post(desk, "bots/librarian/definition", {"status": "paused", "expected_revision": revision})
    assert get(desk, "librarian")["state"] == "paused"
    assert ask(desk, "Still there?", expected=409)["error"]["code"] == "librarian_off"


def test_a_new_conversation_closes_the_old_one_and_never_mixes_them(desk):
    first = ask(desk, "How long do refunds take?", new_conversation=True)
    second = ask(desk, "Who signs contracts?", new_conversation=True)
    assert second["conversation_id"] != first["conversation_id"]
    with desk.app.state.store.read() as c:
        assert H.conversation(c, first["conversation_id"])["closed_at"]
    ask(desk, "Both at once", expected=422, new_conversation=True, conversation_id=second["conversation_id"])
    ask(desk, "Into the closed one", expected=422, conversation_id=first["conversation_id"])
