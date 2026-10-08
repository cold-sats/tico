"""Independent current-inventory/authentication/retry integration acceptance."""
from backend import assistant
from backend.tests.test_api import api, as_member, post  # noqa: F401
from backend.tests.test_assistant import jobs, room


def test_member_inventory_is_current_private_and_bound_to_the_retry_content(api, monkeypatch):
    as_member(api, "ben@acme.example")
    calls, decisions = [], []
    original = assistant.Internal.call

    async def recorded(self, method, path, **kwargs):
        calls.append((method, path, self.headers.get("authorization")))
        return await original(self, method, path, **kwargs)

    async def unavailable(*args, **kwargs):
        decisions.append(args)
        return None

    monkeypatch.setattr(assistant.Internal, "call", recorded)
    monkeypatch.setattr(assistant, "decide", unavailable)
    before = jobs(api)
    first = post(api, "assistant/messages", {"text": "what task types do we use?"},
                 token="ben-test", key="member-inventory")
    assert first["fast"] is True and "General" in first["reply"]["body"]
    assert calls == [("GET", "task-types", "Bearer ben-test")]
    assert not room(api, "ana-test")["messages"]
    post(api, "assistant/messages", {"text": "hi"}, token="ben-test",
         key="member-inventory", expected=409)
    assert len(room(api, "ben-test")["messages"]) == 2
    post(api, "task-types", {"name": "Fresh member fixture", "steps": [{"name": "Triage", "status": "open"}]})
    second = post(api, "assistant/messages", {"text": "for tidy, what types of tasks do we use?"},
                  token="ben-test", key="member-inventory-fresh")
    assert "Fresh member fixture" in second["reply"]["body"]
    assert "Fresh member fixture" not in first["reply"]["body"]
    assert calls == [("GET", "task-types", "Bearer ben-test")] * 2
    assert not decisions and jobs(api) == before
    assert len(room(api, "ben-test")["messages"]) == 4
    assert not room(api, "ana-test")["messages"]
