"""Independent regressions for the reported local-inventory/greeting routing gap.

Only the isolated API fixture is used; no live company or provider is queried.
"""
import pytest

from backend import assistant
from backend.tests.test_api import api, get, post  # noqa: F401
from backend.tests.test_assistant import jobs, room


def forbid_decision(monkeypatch):
    calls = []
    async def unavailable(*args, **kwargs):
        calls.append(args)
        return None
    monkeypatch.setattr(assistant, "decide", unavailable)
    return calls


@pytest.mark.parametrize("text", [
    "what kind of task types do we use here?",
    "for tidy, what types of tasks do we use?",
])
def test_local_inventory_is_api_derived_without_decision_or_job(api, monkeypatch, text):
    post(api, "task-types", {"name": "Fixture repairs", "steps": [{"name": "Triage", "status": "open"}]})
    decisions = forbid_decision(monkeypatch)
    before = jobs(api)
    result = post(api, "assistant/messages", {"text": text}, key="inventory-review")
    assert result["fast"] is True
    assert not decisions, "A simple inventory must not wait for an intent provider"
    answer = result["reply"]["body"]
    assert "General" in answer and "Fixture repairs" in answer
    assert "From [Task types and steps]" not in answer
    # Dev tickets is an example in the documentation, not in this company's inventory.
    assert "Dev tickets" not in answer
    retry = post(api, "assistant/messages", {"text": text}, key="inventory-review")
    assert retry["reply"]["id"] == result["reply"]["id"]
    messages = room(api)["messages"]
    assert len(messages) == 2
    assert jobs(api) == before


def test_exact_greeting_is_fast_once_without_decision_or_job(api, monkeypatch):
    decisions = forbid_decision(monkeypatch)
    before = jobs(api)
    result = post(api, "assistant/messages", {"text": "hi"}, key="greeting-review")
    assert result["fast"] is True and result["reply"]["body"]
    assert not decisions, "A simple greeting must not wait for an intent provider"
    retry = post(api, "assistant/messages", {"text": "hi"}, key="greeting-review")
    assert retry["reply"]["id"] == result["reply"]["id"]
    assert len(room(api)["messages"]) == 2 and jobs(api) == before


@pytest.mark.parametrize("status_code", [403, 503])
def test_task_type_api_failure_is_not_presented_as_an_empty_inventory(api, monkeypatch, status_code):
    decisions = forbid_decision(monkeypatch)
    calls = []

    async def rejected(_self, method, path, **kwargs):
        calls.append((method, path))
        return type("Response", (), {"status_code": status_code})()

    monkeypatch.setattr(assistant.Internal, "call", rejected)
    before = jobs(api)
    result = post(api, "assistant/messages", {"text": "what task types do we use?"}, key="inventory-unavailable")
    assert result["fast"] is True
    assert result["reply"]["body"] == "I couldn't read the task types for this Tico workspace. Please try again later."
    assert calls == [("GET", "task-types")]
    assert not decisions
    assert jobs(api) == before


def test_how_to_type_help_is_still_documentation_and_greeting_with_work_is_not_fast(api, monkeypatch):
    result = post(api, "assistant/messages", {"text": "How do I create a task type?"})
    assert result["fast"] is True and result["intent"] == "help"
    assert "From [" in result["reply"]["body"]
    async def no_decision(*args, **kwargs):
        return None
    monkeypatch.setattr(assistant, "decide", no_decision)
    result = post(api, "assistant/messages", {"text": "Hi, please plan tomorrow's launch"})
    assert result["fast"] is False


@pytest.mark.parametrize("text", [
    "what task types do we use and create one?",
    "for create, what types of tasks do we use?",
])
def test_inventory_with_a_follow_up_write_request_is_not_a_fast_intent(text):
    assert assistant.route(text) == (None, None)
