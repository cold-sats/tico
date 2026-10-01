"""`hub doc ask` (clients/docs_ask.py): a bot asks the Librarian as a message of kind ask; a person asks
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


def test_a_bot_asks_with_an_ask_message_and_gets_the_answer():
    api = Api("bot", [{"messages": [], "execution": {"state": "running"}},
                      {"messages": [{"id": "a1", "in_reply_to": "m1", "from_actor": "bot:librarian", "body": ANSWER}],
                       "execution": {"state": "completed"}}])
    out = D.ask(api, "How long do refunds take?", 30, sleep=lambda s: None)
    assert out["covered"] and len(out["citations"]) == 2 and out["answer"].startswith("Refunds")
    sent = next(c for c in api.calls if c[:2] == ("POST", "messages"))
    assert sent[2] == {"to": "librarian", "text": "How long do refunds take?", "kind": "ask", "wait_s": 30}
    assert ("POST", "messages/a1/ack", {}) in api.calls


def test_the_cli_and_the_tools_declare_ask_and_fetch_and_the_server_never_offers_fetch():
    parsed = hubcli.parser().parse_args(["doc", "fetch", "https://example.com", "--max-chars", "900"])
    assert (parsed.fn, parsed.url, parsed.max_chars) == ("doc fetch", "https://example.com", 900)
    assert hubcli.parser().parse_args(["doc", "ask", "Why?"]).fn == "doc ask"
    assert {t["name"] for t in hubtools.listing()} >= {"hub_doc_ask"}
    assert "hub_doc_fetch" not in {t["name"] for t in hubtools.listing()}                  # the server's door
    assert "hub_doc_fetch" in {t["name"] for t in hubtools.listing(local=True)}            # this computer's
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "hub_doc_fetch", "arguments": {"url": "http://169.254.169.254/"}}}
    assert "Unknown tool" in hubtools.Protocol(None).handle(call)["error"]["message"]
    refused = hubtools.Protocol(None, local=True).handle(call)["result"]
    assert refused["isError"] is False and refused["structuredContent"]["error"] == "private_address"


def test_a_person_waits_for_the_completed_run_and_gets_the_latest_correction():
    partial = {"in_reply_to": "m1", "from_actor": "bot:librarian", "body": "Pair the profile: .", "created": "1"}
    final = {**partial, "body": "Run `python3 hermes_agent.py pair`, then `/reload-mcp`.", "created": "2"}
    api = Api("human", [{"messages": [partial], "execution": {"state": "running"}},
                        {"messages": [partial, final], "execution": {"state": "completed"}}])
    assert D.ask(api, "Connect Hermes", 30, sleep=lambda s: None)["answer"] == final["body"]
