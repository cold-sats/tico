"""Notes imports preserve progress when Granola throttles real MCP response shapes."""
import json
import uuid
from datetime import datetime, timezone
from email.utils import format_datetime

import httpx
import pytest

from backend.granola_mcp import GranolaMCP
from backend.tests.test_granola_mcp import BASE, Provider, api, headers  # noqa: F401


PREFIXED_NOTES = '''Here are the shared notes for this meeting:
<meetings_data count="1"><meeting id="shared" title="Team sync">
<known_participants>Ana from Acme <ana@example.com></known_participants>
<summary>## Decisions
Budget < 15% & roadmap approved</summary></meeting></meetings_data>'''


class NotesProvider(Provider):
    def __init__(self, api, count=2):
        self.ids = [str(uuid.UUID(int=i + 1)) for i in range(count)]
        self.notes_calls, self.ranges = [], []
        self.responses = []
        self.account_result = None
        self.account_calls = 0
        self.range_enum = ["custom", "last_30_days"]
        super().__init__(api)
        self.now = datetime(2026, 10, 2, tzinfo=timezone.utc).timestamp()

    def handle(self, request):
        if request.url.path == "/mcp":
            body = json.loads(request.content)
            if body["method"] == "tools/list":
                tools = [
                    {"name": "list_meetings", "inputSchema": {"properties": {
                        "time_range": {"enum": self.range_enum}, "custom_start": {}, "custom_end": {}},
                        "required": ["time_range"]}},
                    {"name": "get_meetings", "inputSchema": {"properties": {
                        "meeting_ids": {"type": "array", "minItems": 1, "maxItems": 10}},
                        "required": ["meeting_ids"], "additionalProperties": False}}]
                if self.account_result is not None:
                    tools.append({"name": "get_account_info", "inputSchema": {"properties": {}}})
                return httpx.Response(200, json={"result": {"tools": tools}})
            name = body.get("params", {}).get("name")
            if name == "list_meetings":
                self.ranges.append(body["params"]["arguments"])
                return httpx.Response(200, json={"result": {"structuredContent": {
                    "meetings": [{"id": nid} for nid in self.ids]}}})
            if name == "get_account_info":
                self.account_calls += 1
                return self.account_result
            if name == "get_meetings":
                args = body["params"]["arguments"]
                assert set(args) == {"meeting_ids"}
                assert 1 <= len(args["meeting_ids"]) <= 10
                self.notes_calls.append((self.now, args["meeting_ids"]))
                if self.responses:
                    response = self.responses.pop(0)
                    if response is not None:
                        return response
                return httpx.Response(200, json={"result": {"structuredContent": {
                    "meetings": [{"id": nid, "summary": "Shared notes"} for nid in args["meeting_ids"]]}}})
        return super().handle(request)


def rate_limit(kind="tool", message="Rate limit exceeded. Please slow down requests.", retry_after=None):
    payload = {"result": {"isError": True, "content": [{"type": "text", "text": message}]}}
    status = 200
    if kind == "rpc":
        payload = {"error": {"code": -32000, "message": message}}
    elif kind in ("http", "http_error"):
        status = 429 if kind == "http" else 503
        payload = {"error": message}
    return httpx.Response(status, json=payload, headers={"Retry-After": retry_after} if retry_after else {})


@pytest.mark.parametrize("raw,expected", [
    (PREFIXED_NOTES, {"meetings": [{"id": "shared", "title": "Team sync",
        "summary": "## Decisions\nBudget < 15% & roadmap approved",
        "attendees": [{"name": "Ana", "email": "ana@example.com"}]}], "next_cursor": None}),
    ('Intro\n<meetings><meeting id="a" summary="Shared"/></meetings>',
        {"meetings": [{"id": "a", "summary": "Shared", "attendees": []}], "next_cursor": None}),
    ('Intro\n<notes><note id="a" summary="Shared"/></notes>',
        {"meetings": [{"id": "a", "summary": "Shared", "attendees": []}], "next_cursor": None}),
    ('Intro\n<meeting id="a" summary="Shared"/>',
        {"meetings": [{"id": "a", "summary": "Shared", "attendees": []}], "next_cursor": None}),
    ('Intro\n<note id="a" summary="Shared"/>',
        {"meetings": [{"id": "a", "summary": "Shared", "attendees": []}], "next_cursor": None}),
    ('Intro\n<transcript>Ana: Ship it</transcript>', {"transcript": "Ana: Ship it"}),
])
def test_text_before_xml_is_ignored(raw, expected):
    assert GranolaMCP.content({"content": [{"type": "text", "text": raw}]}) == expected
    assert GranolaMCP.xml_content(raw) == expected


@pytest.mark.parametrize("kind,message", [
    ("tool", "Rate limit exceeded"), ("tool", "Please slow down requests"),
    ("tool", "Too many requests"), ("rpc", "Rate limit exceeded"),
    ("http", "Busy"), ("http_error", "Too many requests"),
])
def test_rate_limits_wait_and_retry_the_same_batch(api, kind, message):
    provider = NotesProvider(api)
    provider.connect()
    provider.responses = [rate_limit(kind, message)]
    provider.sync()
    status = api.get(BASE, headers=headers()).json()
    assert status["imported_count"] == 2 and status["skipped"] == 0 and status["last_error"] is None
    assert len(provider.notes_calls) == 2
    assert all(ids == provider.ids for _, ids in provider.notes_calls)
    assert provider.notes_calls[1][0] - provider.notes_calls[0][0] == 15


@pytest.mark.parametrize("retry_after", ["42", "http-date", "invalid"])
def test_retry_after_is_honored(api, retry_after):
    provider = NotesProvider(api)
    provider.connect()
    if retry_after == "http-date":
        # Three globally paced setup calls occur before the notes request.
        retry_after = format_datetime(datetime.fromtimestamp(provider.now + 50, timezone.utc), usegmt=True)
    provider.responses = [rate_limit("tool", retry_after=retry_after)]
    provider.sync()
    first, second = [t for t, _ in provider.notes_calls]
    if retry_after == "42":
        assert second - first == 42
    elif retry_after == "invalid":
        assert second - first == 15
    else:
        assert second == datetime.strptime(retry_after, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=timezone.utc).timestamp()


@pytest.mark.parametrize("kind", ["tool", "rpc", "http"])
def test_four_rate_limits_stop_without_skipping_or_advancing_cursor(api, caplog, kind):
    provider = NotesProvider(api)
    provider.connect()
    saved = provider.service.load("human:ana")
    saved[1].update(cursor="2026-10-01T00:00:00+00:00", skipped=7, imported_count=4, last_sync="previous")
    provider.service.save(*saved)
    provider.responses = [rate_limit(kind, "Rate limit exceeded fake-provider-sensitive") for _ in range(4)]
    provider.sync()
    meta = provider.service.load("human:ana")[1]
    assert meta["last_error"] == "rate_limited: get_meetings"
    assert meta["cursor"] == saved[1]["cursor"] and meta["skipped"] == 0
    assert meta["imported_count"] == 4 and meta["last_sync"] == "previous" and meta["state"] == "connected"
    assert len(provider.notes_calls) == 4 and all(ids == provider.ids for _, ids in provider.notes_calls)
    assert [b[0] - a[0] for a, b in zip(provider.notes_calls, provider.notes_calls[1:])] == [15, 30, 60]
    assert "fake-provider-sensitive" not in caplog.text and "fake-provider-sensitive" not in json.dumps(meta)
    provider.sync()
    assert provider.service.load("human:ana")[1]["last_error"] is None


def test_fifty_meetings_use_five_spaced_batches_and_keep_pacing_between_syncs(api):
    provider = NotesProvider(api, 50)
    provider.connect()
    provider.sync()
    assert len(provider.notes_calls) == 5 and all(len(ids) == 10 for _, ids in provider.notes_calls)
    assert [nid for _, ids in provider.notes_calls for nid in ids] == provider.ids
    assert provider.service.load("human:ana")[1]["imported_count"] == 50
    assert provider.ranges[0]["time_range"] == "last_30_days"
    provider.sync()
    assert provider.ranges[1]["time_range"] == "custom"
    assert all(b[0] - a[0] >= 6 for a, b in zip(provider.notes_calls, provider.notes_calls[1:]))


@pytest.mark.parametrize("exhausted", [False, True])
def test_single_id_fallback_is_paced_and_retries_rate_limits(api, exhausted):
    provider = NotesProvider(api)
    provider.connect()
    provider.responses = [httpx.Response(200, json={"result": {"isError": True}})]
    provider.responses.extend(rate_limit() for _ in range(4 if exhausted else 1))
    provider.sync()
    meta = provider.service.load("human:ana")[1]
    assert meta["skipped"] == 0
    assert meta["last_error"] == ("rate_limited: get_meetings" if exhausted else None)
    assert meta["imported_count"] == (0 if exhausted else 2)
    assert provider.notes_calls[0][1] == provider.ids
    assert all(ids == [provider.ids[0]] for _, ids in provider.notes_calls[1:5 if exhausted else 3])
    assert all(b[0] - a[0] >= 6 for a, b in zip(provider.notes_calls, provider.notes_calls[1:]))


def test_completed_batch_checkpoint_survives_a_rate_limit_and_resumes(api):
    provider = NotesProvider(api, 20)
    provider.connect()
    provider.responses = [None] + [rate_limit() for _ in range(4)]
    provider.sync()
    meta = provider.service.load("human:ana")[1]
    assert meta["imported_count"] == 10 and meta["cursor"] and not meta.get("last_sync")
    assert meta["last_error"] == "rate_limited: get_meetings" and meta["skipped"] == 0
    assert all(ids == provider.ids[10:] for _, ids in provider.notes_calls[1:])
    provider.sync()
    meta = provider.service.load("human:ana")[1]
    assert meta["imported_count"] == 20 and meta["last_sync"] and meta["last_error"] is None


@pytest.mark.parametrize("result,plan,email", [
    ({"structuredContent": {"email": "granola@example.com", "plan": "free"}}, "free", "granola@example.com"),
    ({"structuredContent": {"account": {"user": {"email": "granola@example.com"},
        "plan": {"name": "business"}}}}, "paid", "granola@example.com"),
    ({"content": [{"type": "text", "text": "Email: granola@example.com\nPlan: free"}]}, "free", "granola@example.com"),
    ({"structuredContent": {"unexpected": True}}, "free", None),
    ({"content": [{"type": "text", "text": None}]}, "free", None),
    ({"content": [None]}, "free", None),
    ({"isError": True, "content": [{"type": "text", "text": "Unavailable"}]}, "free", None),
])
def test_account_info_is_optional_and_called_once_per_connection(api, caplog, result, plan, email):
    provider = NotesProvider(api)
    provider.account_result = httpx.Response(200, json={"result": result})
    provider.connect()
    provider.sync()
    status = api.get(BASE, headers=headers()).json()
    assert status["plan_hint"] == plan and status["email"] == email and status["last_error"] is None
    assert provider.ranges[0]["time_range"] == ("custom" if plan == "paid" else "last_30_days")
    provider.sync()
    assert provider.account_calls == 1
    assert not [record for record in caplog.records if record.name == "backend.granola_mcp"]
    assert "fake-access-sensitive" not in caplog.text


def test_free_first_sync_uses_custom_when_last_30_days_is_not_advertised(api):
    provider = NotesProvider(api)
    provider.range_enum = ["custom"]
    provider.connect()
    provider.sync()
    assert provider.ranges[0]["time_range"] == "custom"
    assert provider.ranges[0]["custom_start"] and provider.ranges[0]["custom_end"]


def test_default_batch_limit_and_connection_pacing_are_independent(api):
    provider = NotesProvider(api, 20)
    provider.connect()
    provider.connect("ben-test")
    previous = provider.handle

    def handle(request):
        response = previous(request)
        if request.url.path == "/mcp" and json.loads(request.content)["method"] == "tools/list":
            value = response.json()
            value["result"]["tools"][1]["inputSchema"]["properties"]["meeting_ids"].pop("maxItems")
            return httpx.Response(200, json=value)
        return response

    provider.service.transport = httpx.MockTransport(handle)
    provider.sync()
    assert len(provider.notes_calls) == 2 and all(len(ids) == 10 for _, ids in provider.notes_calls)
    first = provider.service.load("human:ana")
    first[1]["next_meetings_call"] = provider.now + 600
    provider.service.save(*first)
    start = provider.now
    provider.sync("human:ben")
    assert provider.now - start < 20
    assert provider.service.load("human:ben")[1]["imported_count"] == 20
