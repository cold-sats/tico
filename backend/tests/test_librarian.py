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


@pytest.mark.parametrize("next_run", [False, True])
def test_upgrade_refresh_waits_for_a_runner_that_carries_next_run_tasks(desk, next_run):
    with desk.app.state.store.transaction() as c:
        c.execute("DELETE FROM registry_metadata WHERE key='librarian_fix33'")
    ask(desk, "Where are the docs?")
    attempt = post(desk, "jobs/claim", {"next_run": next_run}, token=desk.runner["token"])["attempt"]
    assert [item["title"] for item in attempt["next_run"]] == (["Refresh the map"] if next_run else [])
    with desk.app.state.store.read() as c:
        assert bool(c.execute("SELECT 1 FROM registry_metadata WHERE key='librarian_fix33'").fetchone()) == next_run


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
         {"outcome": "completed", "text": r"14 days.\n\nRead Hub docs with your coworker. "
          "[Internal doc · Refund policy](doc:d1) `printf '\\n'`", "last_seq": 0},
         token=desk.runner["token"])
    snapshot = get(desk, f"conversations/{sent['conversation_id']}/snapshot")
    reply = next(m for m in snapshot["messages"] if m["from_actor"] == "bot:librarian")
    assert reply["in_reply_to"] in (sent["message_id"], again["message_id"])
    assert "Refund policy" in reply["body"]
    assert "14 days.\n\nRead Tico docs with your coworker." in reply["body"]
    assert "`printf '\\n'`" in reply["body"]


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


def test_docs_history_reopens_without_losing_messages_or_changing_the_ask_contract(desk):
    from backend.tests.test_openapi_v2 import conforms
    first = ask(desk, "Where is the release checklist?")
    second = ask(desk, "Who owns smoke checks?", new_conversation=True)
    assert second["conversation_id"] != first["conversation_id"]
    history = get(desk, "librarian/conversations")
    assert {row["id"] for row in history["conversations"]} == {first["conversation_id"], second["conversation_id"]}
    archived = next(row for row in history["conversations"] if row["id"] == first["conversation_id"])
    assert archived["closed_at"] and archived["title"] == "Where is the release checklist?"
    page = get(desk, "librarian/conversations?limit=1")
    tail = get(desk, "librarian/conversations?limit=1&offset=" + str(page["next_offset"]))
    assert page["next_offset"] == 1 and tail["next_offset"] is None
    assert page["conversations"][0]["id"] != tail["conversations"][0]["id"]
    reopened = post(desk, f"librarian/conversations/{first['conversation_id']}/reopen", {})
    assert reopened == {"conversation_id": first["conversation_id"]}
    document = get(desk, "openapi.json")
    for value, name in [(history, "DocsConversations"), (reopened, "DocsReopened")]:
        assert conforms(value, document["components"]["schemas"][name], document) is None
    with desk.app.state.store.read() as c:
        assert librarian.find_room(c, "human:ana")["id"] == first["conversation_id"]
        assert H.conversation(c, second["conversation_id"])["closed_at"]
    assert get(desk, f"conversations/{first['conversation_id']}/snapshot")["messages"][0]["body"] == archived["title"]
    assert ask(desk, "And deployment?")["conversation_id"] == first["conversation_id"]
    assert ask(desk, "And rollback?", conversation_id=first["conversation_id"])["conversation_id"] == first["conversation_id"]
    # Reopening the current room is a no-op, even if it is now busy.
    claim(desk, desk.runner)
    assert post(desk, f"librarian/conversations/{first['conversation_id']}/reopen", {}) == reopened


def test_docs_history_is_private_and_only_docs_rooms_can_be_reopened(desk):
    mine = ask(desk, "My private docs question")
    theirs = ask(desk, "Another private docs question", token="ben-test")
    ask(desk, "Another docs chat", token="ben-test", new_conversation=True)
    assert [row["id"] for row in get(desk, "librarian/conversations")["conversations"]] == [mine["conversation_id"]]
    other_history = get(desk, "librarian/conversations", token="ben-test")["conversations"]
    assert mine["conversation_id"] not in {row["id"] for row in other_history}
    post(desk, f"librarian/conversations/{theirs['conversation_id']}/reopen", {}, expected=403)
    post(desk, f"librarian/conversations/{mine['conversation_id']}/reopen", {}, token="ben-test", expected=403)
    post(desk, "librarian/conversations/missing/reopen", {}, expected=404)
    with desk.app.state.store.transaction() as c:
        other = H.open_conversation(c, "human:ana", ["human:ana", "bot:coo"], kind="chat",
                                    scope="personal", owner_actor="human:ana", room_key="coo")
        direct = H.open_conversation(c, "human:ana", ["human:ana", "bot:librarian"], kind="chat",
                                     room_key="docs", owner_actor="human:ana")
    for cid in (other["id"], direct["id"]):
        post(desk, f"librarian/conversations/{cid}/reopen", {}, expected=422)
    assert len(get(desk, "librarian/conversations")["conversations"]) == 1
    attempt = claim(desk, desk.runner)
    get(desk, "librarian/conversations", token=attempt["token"], expected=403)
    post(desk, f"librarian/conversations/{mine['conversation_id']}/reopen", {}, token=attempt["token"], expected=403)


def test_reopening_docs_keeps_the_current_room_when_its_turn_is_busy(desk):
    first = ask(desk, "An earlier question")
    current = ask(desk, "The current question", new_conversation=True)
    with desk.app.state.store.transaction() as c:
        c.execute("UPDATE jobs SET state='cancelled' WHERE message_id=?", (first["message_id"],))
    attempt = claim(desk, desk.runner)
    assert attempt["message"]["id"] == current["message_id"]
    response = post(desk, f"librarian/conversations/{first['conversation_id']}/reopen", {}, expected=409)
    assert response["error"]["code"] == "busy"
    with desk.app.state.store.read() as c:
        assert librarian.find_room(c, "human:ana")["id"] == current["conversation_id"]
        assert H.conversation(c, first["conversation_id"])["closed_at"]


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



def test_instant_search_keeps_long_question_tail_and_includes_manual(api, monkeypatch):
    import asyncio
    from starlette.requests import Request
    request = Request({"type": "http", "app": api.app, "method": "POST", "path": "/api/v2/docs/ask",
                       "headers": [(b"authorization", b"Bearer ana-test")], "scheme": "http",
                       "server": ("testserver", 80), "query_string": b""})
    question = ("Please explain the existing setup for this computer and its relationship to the team "
                "while keeping the previous configuration intact. " * 12 + "How long does the join code last?")
    hits = asyncio.run(librarian._search(request, question))
    assert any(r["id"] == "manual:install" for r in hits)
    seen = {}
    class Search:
        def __init__(self, request):
            pass
        async def get(self, path, **params):
            seen.update(params)
            return {"results": hits}
    monkeypatch.setattr(librarian, "Internal", Search)
    assert asyncio.run(librarian._search(request, question)) == hits
    assert seen["q"] == question and seen["collection"] == "all"


def test_mcp_docs_ask_status_collects_the_same_private_answer(desk):
    from backend.mcp import InProcessApi
    from backend.tests.test_mcp import call
    assert InProcessApi.docs_wait_max == 20
    err, pending = call(desk, "hub_doc_ask", {"question": "Refund window?", "wait_s": 0})
    assert not err and pending["timeout"] and pending["message_id"] and pending["conversation_id"]
    ids = {k: pending[k] for k in ("message_id", "conversation_id")}
    err, waiting = call(desk, "hub_doc_ask_status", ids)
    assert not err and waiting == pending
    err, refused = call(desk, "hub_doc_ask_status", ids, token="ben-test")
    assert err and refused["error"] == "forbidden"
    attempt = claim(desk, desk.runner)
    post(desk, f"attempts/{attempt['id']}/started", {"thread_id": "t"}, token=desk.runner["token"])
    post(desk, f"attempts/{attempt['id']}/complete",
         {"outcome": "completed", "text": "14 days. [Internal doc · Refund policy](doc:d1)", "last_seq": 0},
         token=desk.runner["token"])
    err, final = call(desk, "hub_doc_ask_status", ids)
    assert not err and final["covered"] and final["answer"].startswith("14 days")
    snapshot = get(desk, f"conversations/{pending['conversation_id']}/snapshot")
    assert len([m for m in snapshot["messages"] if m["from_actor"] == "human:ana"]) == 1


def test_how_to_wording_preserves_installation_software_and_source_literals():
    source = ('Change standing instructions. The runner pulls the update before the next run. '
              'Install the runner. `runner --help` [runner](https://example.com/runner) '
              '"standing instructions" runner/service.py')
    result = H.librarian_text(source)
    assert result.startswith('Change Instructions. The Computer pulls the update before the next run.')
    assert 'Install the runner.' in result
    for literal in ('`runner --help`', '[runner](https://example.com/runner)',
                    '"standing instructions"', 'runner/service.py'):
        assert literal in result
    for kept in ("Our company fixes the washing machine; two machines a day.",
                 "We bought a new machine to wash clothes at our company.",
                 "The washing machine broke. That machine needs a new pump.",
                 "Companies hire coworkers to repair washing machines.", "Company docs describe the factory machines.",
                 "The runner reads the race results after the competition.", "The runner pulls a hamstring.",
                 "He said 'Hub docs' and ‘standing instructions’ and “Hub docs”.", "> Hub docs contain standing instructions."):
        assert H.librarian_text(kept) == kept
    assert H.librarian_text("Hub docs: standing instructions.") == "Tico docs: Instructions."
    assert H.librarian_text("HUB DOCS; don't skip standing instructions.") == "TICO DOCS; don't skip Instructions."
    assert H.librarian_text("THE RUNNER PULLS UPDATES. Read Hub Docs.") == "THE COMPUTER PULLS UPDATES. Read Tico Docs."
    for kept in ('He wrote "Hub docs and\nstanding instructions".', "~~~text\nHub docs and standing instructions\n~~~",
                 "``a `Hub docs` b``", "[Hub docs][source]", "'Hub docs\ncontain standing instructions'",
                 "````a ``` Hub docs b````", "~~~~\nHub docs\n~~~\nstanding instructions\n~~~~",
                 "    Hub docs in indented code\n", "~~~~\n~~~~`\nHub docs and standing instructions\n~~~~"):
        assert H.librarian_text(kept) == kept
    assert H.librarian_text("~~~~\n~~~~`\nHub docs\n~~~~\nRead Hub docs.") == "~~~~\n~~~~`\nHub docs\n~~~~\nRead Tico docs."
    assert H.librarian_text("The runner syncs `AGENT.md` before work.") == "The Computer syncs `AGENT.md` before work."
    assert (H.librarian_text("The runner pulls [updates](https://example.com/u). Read Hub docs.")
            == "The Computer pulls [updates](https://example.com/u). Read Tico docs.")


def test_librarian_doc_writes_normalize_generated_instructions_and_computers(desk):
    ask(desk, "How do I change Instructions?")
    attempt = claim(desk, desk.runner)
    created = post(desk, "docs", {"title": "FAQ", "path": "FAQ.md",
                                  "body": "Change standing instructions. The runner pulls the update."},
                   token=attempt["token"])["doc"]
    assert created["body"] == "Change Instructions. The Computer pulls the update."
    edited = desk.patch("/api/v2/docs/" + created["id"],
                        json={"version": created["version"], "body": "Standing instructions: the runner pulls AGENT.md."},
                        headers=headers(attempt["token"]))
    assert edited.status_code == 200, edited.text
    assert edited.json()["doc"]["body"] == "Instructions: the Computer pulls AGENT.md."
