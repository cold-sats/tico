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
                 "The runner reads the race results after the competition."):
        assert H.librarian_text(kept) == kept
    assert H.librarian_text("Hub docs: standing instructions.") == "Tico docs: Instructions."


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
