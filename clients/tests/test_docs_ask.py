"""`hub docs ask` (clients/docs_ask.py): a bot asks the Librarian as a message of kind ask; a person asks
through their own docs conversation. Both come back as {answer, citations, covered}."""

from clients import docs_ask as D, hubcli, hubtools

ANSWER = ("Refunds are issued within 14 days.\n\nSources\n"
          "1. [Internal doc · Refund policy](doc:d7f3) 2. [Linked · help.example.com](https://help.example.com/refunds)")


class Api:
    def __init__(self, role, replies):
        self.role, self.replies, self.calls = role, list(replies), []

    def get(self, path, **params):
        self.calls.append(("GET", path))
        if path == "me":
            return {"actor": "bot:sales" if self.role == "bot" else "human:ana", "role": self.role}
        return self.replies.pop(0)

    def post(self, path, body, key=None):
        self.calls.append(("POST", path, body))
        return {"id": "m1", "conversation_id": "c1", "message_id": "m1"}


def test_citations_are_read_from_the_answer_once_each():
    assert D.parse_citations(ANSWER + " [Internal doc · Refund policy](doc:d7f3)") == [
        {"type": "internal", "title": "Refund policy", "url_or_id": "d7f3"},
        {"type": "linked", "title": "help.example.com", "url_or_id": "https://help.example.com/refunds"}]
    assert D.parse_citations("[Linked · x](javascript:alert(1)) [Internal doc · y](https://evil.example.com)") == []
    assert D.covered("Refunds take 14 days.") and not D.covered("Not in the docs. Nothing says how long.")


def test_a_bot_asks_with_an_ask_message_and_gets_the_answer():
    api = Api("bot", [{}, {"m1": {"id": "a1", "body": ANSWER}}])
    out = D.ask(api, "How long do refunds take?", 30, sleep=lambda s: None)
    assert out["covered"] and len(out["citations"]) == 2 and out["answer"].startswith("Refunds")
    sent = next(c for c in api.calls if c[:2] == ("POST", "messages"))
    assert sent[2] == {"to": "librarian", "text": "How long do refunds take?", "kind": "ask", "wait_s": 30}
    assert ("POST", "messages/a1/ack", {}) in api.calls


def test_a_person_asks_in_their_own_docs_conversation_and_a_silent_librarian_times_out():
    reply = {"messages": [{"in_reply_to": "m1", "from_actor": "bot:librarian", "body": "Not in the docs. Ask Ben."}]}
    person = Api("owner", [{"messages": []}, reply])
    out = D.ask(person, "Who signs contracts?", 30, sleep=lambda s: None)
    assert out["covered"] is False and out["citations"] == []
    assert ("POST", "docs/ask", {"question": "Who signs contracts?"}) in person.calls
    ticks = iter(range(0, 1000, 40))
    quiet = Api("bot", [{}, {}, {}])
    assert D.ask(quiet, "Anyone?", 30, sleep=lambda s: None, clock=lambda: next(ticks)) == {"timeout": True}


def test_the_cli_and_the_tools_declare_ask_and_fetch_and_the_server_never_offers_fetch():
    parsed = hubcli.parser().parse_args(["docs", "fetch", "https://example.com", "--max-chars", "900"])
    assert (parsed.fn, parsed.url, parsed.max_chars) == ("docs fetch", "https://example.com", 900)
    assert hubcli.parser().parse_args(["docs", "ask", "Why?"]).fn == "docs ask"
    assert {t["name"] for t in hubtools.listing()} >= {"hub_docs_ask"}
    assert "hub_docs_fetch" not in {t["name"] for t in hubtools.listing()}                  # the server's door
    assert "hub_docs_fetch" in {t["name"] for t in hubtools.listing(local=True)}            # this computer's
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "hub_docs_fetch", "arguments": {"url": "http://169.254.169.254/"}}}
    assert "Unknown tool" in hubtools.Protocol(None).handle(call)["error"]["message"]
    refused = hubtools.Protocol(None, local=True).handle(call)["result"]
    assert refused["isError"] is False and refused["structuredContent"]["error"] == "private_address"
