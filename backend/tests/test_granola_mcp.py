"""Fake official OAuth/MCP: no live accounts, network or secrets."""
import asyncio
import json
import logging

import httpx
import pytest

from backend.auth import Identity
from backend.tests.test_api import api, headers, setup_attempt  # noqa: F401
from backend.tests.test_media import import_meeting
from backend.tests.test_member_bots import botops  # noqa: F401

BASE = "/api/v2/meetings/granola"


class Provider:
    def __init__(self, api):
        self.api = api
        self.service = api.app.state.granola
        self.now = 2_000_000_000.0
        self.calls, self.sleeps = [], []
        self.poll_errors = []
        self.refresh_error = False
        self.unauthorized = False
        self.rate_limit = False
        self.paid = False
        self.transcript_denied = False
        self.registration_rejected = False
        self.service.clock = lambda: self.now
        self.service.transport = httpx.MockTransport(self.handle)
        self.service.sleep = self.sleep

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def handle(self, request):
        from urllib.parse import parse_qs
        path = request.url.path
        self.calls.append((path, request))
        if path == "/oauth2/register":
            body = json.loads(request.content)
            assert body["token_endpoint_auth_method"] == "none"
            # Granola's real server refuses a registration without a redirect_uris array (verified live).
            if not isinstance(body.get("redirect_uris"), list):
                return httpx.Response(400, json={"error": "invalid_client_metadata",
                                                 "error_description": "redirect_uris must be an array"})
            return httpx.Response(200, json={"client_id": "public-client"})
        if path == "/oauth2/device_authorization":
            if self.registration_rejected:
                self.registration_rejected = False
                return httpx.Response(401, json={"error": "invalid_client"})
            data = parse_qs(request.content.decode())
            assert data["resource"] == ["https://mcp.granola.ai/mcp"]
            return httpx.Response(200, json={"device_code": "fake-device-sensitive", "user_code": "ABCD",
                                            "verification_uri": "https://granola.ai/device", "expires_in": 600, "interval": 5})
        if path == "/oauth2/token":
            data = parse_qs(request.content.decode())
            assert data["resource"] == ["https://mcp.granola.ai/mcp"]
            if data["grant_type"] == ["refresh_token"]:
                if self.refresh_error:
                    return httpx.Response(400, json={"error": "invalid_grant", "description": "fake-refresh-sensitive"})
                return httpx.Response(200, json={"access_token": "fake-access-refreshed", "expires_in": 3600})
            if self.poll_errors:
                return httpx.Response(400, json={"error": self.poll_errors.pop(0)})
            return httpx.Response(200, json={"access_token": "fake-access-sensitive", "refresh_token": "fake-refresh-sensitive",
                                            "expires_in": 3600})
        if path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json={"revocation_endpoint": "https://mcp-auth.granola.ai/oauth2/revoke"})
        if path == "/oauth2/revoke":
            return httpx.Response(200, json={})
        assert path == "/mcp"
        body = json.loads(request.content)
        method = body["method"]
        if method == "initialize":
            if self.unauthorized:
                self.unauthorized = False
                return httpx.Response(401, json={})
            return httpx.Response(200, headers={"Mcp-Session-Id": "session"}, json={"result": {"protocolVersion": "2025-03-26"}})
        assert request.headers["Mcp-Session-Id"] == "session"
        if method == "notifications/initialized":
            return httpx.Response(202)
        if self.rate_limit:
            self.rate_limit = False
            return httpx.Response(429, headers={"Retry-After": "3"}, json={})
        if method == "tools/list":
            tools = [{"name": "list_meetings", "inputSchema": {"properties": {"since": {}, "until": {}}}},
                     {"name": "get_meetings", "inputSchema": {"properties": {"meeting_ids": {}}, "required": ["meeting_ids"]}}]
            if self.paid:
                tools.append({"name": "get_meeting_transcript", "inputSchema": {"properties": {"meeting_id": {}}, "required": ["meeting_id"]}})
            return httpx.Response(200, json={"result": {"tools": tools}})
        tool = body["params"]["name"]
        if tool == "list_meetings":
            assert set(body["params"]["arguments"]) == {"since", "until"}
            value = {"meetings": [{"id": "not_12345678901234", "title": "Planning"}]}
        elif tool == "get_meetings":
            value = {"meetings": [{"id": "not_12345678901234", "title": "Planning", "date": "2026-10-01T00:00:00Z",
                                   "summary_markdown": "## Decisions\nShip it", "private_notes": "Never import this"}]}
        else:
            assert tool == "get_meeting_transcript"
            if self.transcript_denied:
                return httpx.Response(200, json={"result": {"isError": True, "content": [{"type": "text", "text": "Paid plan required: permission denied"}]}})
            value = {"transcript": "Ana: Ship it"}
        return httpx.Response(200, json={"result": {"content": [{"type": "text", "text": json.dumps(value)}]}})

    def connect(self, token="ana-test"):
        response = self.api.post(BASE + "/connect", headers=headers(token))
        assert response.status_code == 200, response.text
        assert "device_code" not in response.text
        self.now += 5
        response = self.api.get(BASE + "/connect/status", headers=headers(token))
        assert response.status_code == 200, response.text
        return response.json()

    def sync(self, actor="human:ana"):
        self.api.portal.call(self.service.sync, actor)


def test_registration_device_encryption_status_and_disconnect(api, caplog):
    caplog.set_level(logging.DEBUG)
    provider = Provider(api)
    assert provider.connect()["connected"]
    assert provider.connect("ben-test")["connected"]
    assert sum(path == "/oauth2/register" for path, _ in provider.calls) == 1
    with api.app.state.store.read() as c:
        row = c.execute("SELECT * FROM granola_connections WHERE actor='human:ana'").fetchone()
        assert b"fake-refresh-sensitive" not in bytes(row["ciphertext"])
        assert "fake-" not in row["metadata_json"]
        assert c.execute("SELECT count(*) FROM credentials WHERE id=?", (row["id"],)).fetchone()[0] == 0
    for path in (BASE, BASE + "/connect/status", "/api/v2/credentials"):
        text = api.get(path, headers=headers("ana-test")).text
        assert all(secret not in text for secret in ("fake-access-sensitive", "fake-refresh-sensitive", "fake-device-sensitive"))
    assert "fake-refresh-sensitive" not in caplog.text
    assert api.delete(BASE + "/connect", headers=headers("ana-test")).status_code == 200
    with api.app.state.store.read() as c:
        assert not c.execute("SELECT 1 FROM granola_connections WHERE actor='human:ana'").fetchone()
        assert c.execute("SELECT 1 FROM granola_connections WHERE actor='human:ben'").fetchone()
    assert any(path == "/oauth2/revoke" for path, _ in provider.calls)


@pytest.mark.parametrize("error,state", [("expired_token", "expired"), ("access_denied", "denied")])
def test_terminal_device_errors(api, error, state):
    provider = Provider(api)
    provider.poll_errors = [error]
    assert provider.connect()["state"] == state
    saved = provider.service.load("human:ana")
    assert saved[2] == {}


def test_device_interval_slow_down_and_local_expiry(api):
    provider = Provider(api)
    provider.poll_errors = ["slow_down", "authorization_pending"]
    assert provider.connect()["state"] == "pending"
    before = len(provider.calls)
    assert api.get(BASE + "/connect/status", headers=headers("ana-test")).json()["state"] == "pending"
    assert len(provider.calls) == before
    provider.now += 10
    api.get(BASE + "/connect/status", headers=headers("ana-test"))
    saved = provider.service.load("human:ana")
    assert saved[1]["interval"] == 10 and saved[1]["next_poll"] == provider.now + 10
    provider.now += 601
    assert api.get(BASE + "/connect/status", headers=headers("ana-test")).json()["state"] == "expired"


def test_re_register_rejected_client(api):
    provider = Provider(api)
    provider.registration_rejected = True
    assert provider.connect()["connected"]
    assert sum(path == "/oauth2/register" for path, _ in provider.calls) == 2


def test_free_sync_dedup_private_notes_and_person_isolation(api):
    provider = Provider(api)
    provider.connect()
    existing = import_meeting(api, notes="API notes", source="granola", external_id="not_12345678901234", private=True)
    provider.sync()
    status = api.get(BASE, headers=headers("ana-test")).json()
    assert status["last_sync"] and status["plan_hint"] == "free" and not status["last_error"]
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM meetings").fetchone()[0] == 1
        row = c.execute("SELECT metadata_json FROM meetings WHERE id=?", (existing["id"],)).fetchone()
        assert json.loads(row[0])["private"]
    record = api.get("/api/meetings/" + existing["id"], headers=headers("ana-test")).json()
    assert record["notes"] == "API notes" and "Never import this" not in json.dumps(record)
    assert not api.get(BASE, headers=headers("ben-test")).json()["connected"]
    assert api.post(BASE + "/sync", headers=headers("ben-test")).json()["state"] == "off"
    assert api.get(BASE + "?person=ana", headers=headers("ben-test")).json()["mode"] == "off"
    _, _, attempt = setup_attempt(api)
    for method, path in (("get", BASE), ("post", BASE + "/sync"), ("post", BASE + "/connect"),
                         ("get", BASE + "/connect/status"), ("delete", BASE + "/connect")):
        assert getattr(api, method)(path, headers=headers(attempt["token"])).status_code == 403


@pytest.mark.parametrize("denied", [False, True])
def test_paid_transcripts_or_permission_denial_still_imports(api, denied):
    provider = Provider(api)
    provider.paid, provider.transcript_denied = True, denied
    provider.connect()
    provider.sync()
    status = api.get(BASE, headers=headers("ana-test")).json()
    assert status["last_sync"] and status["imported_count"] == 1 and not status["last_error"]
    assert status["plan_hint"] == ("free" if denied else "paid")
    if denied:
        assert status["plan_hint"] == "free"


def test_401_refresh_and_429_backoff(api):
    provider = Provider(api)
    provider.connect()
    provider.unauthorized, provider.rate_limit = True, True
    provider.sync()
    assert not api.get(BASE, headers=headers("ana-test")).json()["last_error"]
    assert 3 in provider.sleeps
    assert provider.service.load("human:ana")[2]["access_token"] == "fake-access-refreshed"
    assert len(provider.sleeps) >= 4  # Every MCP request is paced, including initialize and retry.


def test_refresh_failure_needs_signin_and_health_privacy(api):
    provider = Provider(api)
    provider.connect("ben-test")
    provider.unauthorized, provider.refresh_error = True, True
    provider.sync("human:ben")
    status = api.get(BASE, headers=headers("ben-test")).json()
    assert status["needs_signin"] and not status["connected"]
    assert "fake-" not in json.dumps(status)
    # Health is scoped even for an administrator who is not the owner.
    for token, visible in (("ben-test", True), ("ana-test", True), ("cara-test", False)):
        response = api.get("/api/v2/health", headers=headers(token))
        assert response.status_code == 200
        assert ("Granola needs sign-in again" in response.text) == visible


def test_debounce_background_and_25_minute_schedule(api):
    provider = Provider(api)
    provider.connect()
    provider.sync()
    assert api.post(BASE + "/sync", headers=headers("ana-test")).json()["state"] == "recent"
    count = len(provider.calls)
    provider.now += 119
    assert api.post(BASE + "/sync", headers=headers("ana-test")).json()["state"] == "recent"
    api.portal.call(provider.service.tick)
    assert len(provider.calls) == count
    provider.now += 2
    result = api.post(BASE + "/sync", headers=headers("ana-test")).json()
    assert result["state"] == "syncing"
    async def finish():
        await asyncio.gather(*list(provider.service.jobs.values()))
    api.portal.call(finish)
    count = len(provider.calls)
    provider.now += 1499
    api.portal.call(provider.service.tick)
    assert len(provider.calls) == count
    provider.now += 2
    api.portal.call(provider.service.tick)
    api.portal.call(finish)
    assert len(provider.calls) > count


def test_structured_and_xml_notes_exclude_private_fields_and_keep_provider_id():
    from backend.granola_mcp import GranolaMCP
    value = GranolaMCP.content({"content": [{"type": "text", "text": '<meetings><meeting id="not_12345678901234"><title>Planning</title><enhanced_notes>Ship it</enhanced_notes><private_notes>Never import</private_notes></meeting></meetings>'}]})
    item = GranolaMCP.item(value["meetings"][0])
    assert item.external_id == "not_12345678901234" and item.notes == "Ship it"
    assert "Never import" not in item.model_dump_json()
    assert GranolaMCP.item({"id": "uuid", "note_id": "not_12345678901234", "ai_summary": "Ship it"}).external_id == item.external_id
    assert GranolaMCP.item({"id": "uuid", "notes": "Private note", "private_notes": "Private note"}) is None
    assert GranolaMCP.content({"content": [{"type": "text", "text": "Ana: Ship it"}]}, allow_text=True)["transcript"] == "Ana: Ship it"


def test_botops_mcp_uses_the_human_requester(api, botops):
    from backend.tests.test_member_bots import turn
    from backend.tests.test_mcp import call
    provider = Provider(api)
    provider.connect("cara-test")
    attempt = turn(api, botops, person="cara-test", text="Sync my Granola notes")
    error, result = call(api, "hub_meeting_granola_status", token=attempt["token"])
    assert not error and result["connected"] and result["email"] is None
    error, result = call(api, "hub_meeting_granola_sync", token=attempt["token"])
    assert not error and result["state"] == "syncing"
    async def finish():
        await asyncio.gather(*list(provider.service.jobs.values()))
    api.portal.call(finish)
    assert provider.service.status(Identity("human:cara", "human", "cara@acme.example"))["imported_count"] == 1
    assert not provider.service.status(Identity("human:ana", "owner", "ana@acme.example"))["connected"]


def test_cli_granola_alias_and_dispatch():
    from clients import hubcli, hubtools
    from clients.remotecli import tool_name
    for action in ("status", "sync"):
        argv, _ = hubcli.rename_argv(["meetings", "granola", action])
        args = hubcli.parser().parse_args(argv)
        assert tool_name(args.fn) in hubtools.BY_NAME


def test_sql_cannot_read_connection_secrets(api):
    Provider(api).connect()
    response = api.post("/api/v2/sql", json={"sql": "SELECT * FROM granola_connections"}, headers=headers("ana-test"))
    assert response.status_code in (403, 422)
    assert "fake-access-sensitive" not in response.text



def test_sse_session_response_and_runtime_schema(api):
    provider = Provider(api)
    provider.connect()
    previous = provider.handle
    def handle(request):
        if request.url.path == "/mcp":
            body = json.loads(request.content)
            if body["method"] == "tools/list":
                response = previous(request)
                value = {"jsonrpc": "2.0", "id": body["id"], **response.json()}
                return httpx.Response(200, headers={"Content-Type": "text/event-stream"},
                                      text="event: message\ndata: " + json.dumps(value) + "\n\n")
        return previous(request)
    provider.service.transport = httpx.MockTransport(handle)
    provider.sync()
    assert provider.service.load("human:ana")[1]["last_sync"]
    from backend.granola_mcp import GranolaMCP, GranolaError
    args = GranolaMCP.arguments({"inputSchema": {"properties": {"time_range": {"enum": ["custom"]},
                                "start_date": {"format": "date"}}, "required": ["time_range"]}},
                               {"time_range": "custom", "start_date": "2026-10-01T00:00:00Z", "unknown": "ignore"})
    assert args == {"time_range": "custom", "start_date": "2026-10-01"}
    with pytest.raises(GranolaError):
        GranolaMCP.arguments({"inputSchema": {"required": ["unknown_required"]}}, {})


def test_expiry_refresh_before_request_and_connection_survives_vault_restart(api):
    from backend.credentials import Vault
    provider = Provider(api)
    provider.connect()
    api.app.state.vault = Vault(api.app.state.store)
    assert provider.service.load("human:ana")[2]["refresh_token"] == "fake-refresh-sensitive"
    provider.now += 3600
    provider.sync()
    assert provider.service.load("human:ana")[2]["access_token"] == "fake-access-refreshed"
    assert not api.get(BASE, headers=headers("ana-test")).json()["needs_signin"]


@pytest.mark.parametrize("failure", ["503", "429", "network", "bad_response", "registration_network"])
def test_transient_refresh_keeps_token_and_retries(api, caplog, failure):
    caplog.set_level(logging.DEBUG)
    provider = Provider(api)
    provider.connect()
    previous = provider.handle
    def handle(request):
        if request.url.path == "/oauth2/token":
            if failure in ("network", "registration_network"):
                if failure == "network":
                    raise httpx.ConnectError("fake-refresh-sensitive", request=request)
                return httpx.Response(401, json={"error": "invalid_client"})
            if failure == "bad_response":
                return httpx.Response(200, text="fake-refresh-sensitive")
            return httpx.Response(int(failure), text="fake-refresh-sensitive")
        if failure == "registration_network" and request.url.path == "/oauth2/register":
            raise httpx.ConnectError("fake-refresh-sensitive", request=request)
        return previous(request)
    provider.service.transport = httpx.MockTransport(handle)
    provider.now += 3600
    provider.sync()
    saved = provider.service.load("human:ana")
    assert saved[2]["refresh_token"] == "fake-refresh-sensitive"
    assert saved[1]["state"] == "connected" and not saved[1]["needs_signin"]
    assert saved[1]["last_error"] and saved[1]["retry_after"] > provider.now
    assert all(secret not in caplog.text for secret in ("fake-refresh-sensitive", "fake-access-sensitive", "fake-device-sensitive"))
    provider.service.transport = httpx.MockTransport(previous)
    provider.sync()
    assert provider.service.load("human:ana")[1]["last_sync"]


@pytest.mark.parametrize("transcript", ["tool_error", [], "", [{"start": "2026-10-01T00:00:00Z", "text": "Ship it"}], {"unknown": "shape"}])
def test_any_transcript_failure_imports_notes(api, transcript):
    provider = Provider(api)
    provider.paid = True
    provider.connect()
    previous = provider.handle
    def handle(request):
        if request.url.path == "/mcp":
            body = json.loads(request.content)
            if body.get("params", {}).get("name") == "get_meeting_transcript":
                result = {"isError": True, "content": [{"type": "text", "text": "Transcripts are available on Business and Enterprise plans"}]} if transcript == "tool_error" else {"structuredContent": {"transcript": transcript}}
                return httpx.Response(200, json={"result": result})
        return previous(request)
    provider.service.transport = httpx.MockTransport(handle)
    provider.sync()
    status = api.get(BASE, headers=headers("ana-test")).json()
    assert status["last_sync"] and status["imported_count"] == 1 and status["skipped"] == 0
    with api.app.state.store.read() as c:
        assert "Ship it" in c.execute("SELECT notes FROM meetings").fetchone()[0]


def test_malformed_meeting_is_skipped_and_later_notes_import(api):
    provider = Provider(api)
    provider.connect()
    previous = provider.handle
    def handle(request):
        if request.url.path == "/mcp":
            body = json.loads(request.content)
            if body.get("params", {}).get("name") == "get_meetings":
                return httpx.Response(200, json={"result": {"structuredContent": {"meetings": [
                    {"id": "invalid id", "summary": "Bad"},
                    {"id": "later-note", "summary": "Good"}]}}})
        return previous(request)
    provider.service.transport = httpx.MockTransport(handle)
    provider.sync()
    status = api.get(BASE, headers=headers("ana-test")).json()
    assert status["skipped"] == 1 and status["last_error"] == "1 notes skipped"
    assert status["imported_count"] == 1 and status["last_sync"]
    assert provider.service.load("human:ana")[1]["cursor"]


def test_url_dedup_preserves_richer_api_meeting_and_person_scope(api):
    provider = Provider(api)
    provider.connect()
    url = "https://app.granola.ai/notes/shared"
    original = import_meeting(api, source="granola", external_id="public-api-id", notes="Rich API notes",
                              started_at="2026-09-30T10:00:00Z", participants=["Ana"], media_url=url, private=False)
    original_record = api.get("/api/meetings/" + original["id"], headers=headers("ana-test")).json()
    previous = provider.handle
    def handle(request):
        response = previous(request)
        if request.url.path == "/mcp" and json.loads(request.content).get("params", {}).get("name") == "get_meetings":
            return httpx.Response(200, json={"result": {"structuredContent": {"meetings": [
                {"id": "document-uuid", "summary": "Poor summary", "title": "Poor title", "web_url": url,
                 "created_at": "2026-10-01T00:00:00Z"}]}}})
        return response
    provider.service.transport = httpx.MockTransport(handle)
    provider.sync()
    record = api.get("/api/meetings/" + original["id"], headers=headers("ana-test")).json()
    for field in ("notes", "transcript_readable", "title", "started", "participants", "private", "turns"):
        assert record[field] == original_record[field]
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM meetings").fetchone()[0] == 1
    assert api.get(BASE, headers=headers("ana-test")).json()["imported_count"] == 0


def test_disconnect_cancels_running_sync_and_status_matches_schema(api):
    from backend.tests.test_openapi_v2 import conforms
    provider = Provider(api)
    provider.connect()
    async def exercise():
        started = asyncio.Event()
        async def blocked(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()
        provider.service.rpc = blocked
        who = Identity("human:ana", "human", "ana@acme.example")
        result = await provider.service.trigger(who)
        await started.wait()
        status = await asyncio.to_thread(provider.service.status, who)
        assert status["syncing"] and result["state"] == "syncing"
        from backend.openapi_v2 import generate
        root = generate()
        assert conforms(status, root["components"]["schemas"]["GranolaStatus"], root) is None
        assert conforms(result, root["components"]["schemas"]["GranolaSync"], root) is None
        await asyncio.wait_for(provider.service.disconnect(who), 1)
        assert not provider.service.jobs
    api.portal.call(exercise)
    assert provider.service.load("human:ana") is None


@pytest.mark.parametrize("field,value", [("hidden", True), ("sign_in", False)])
def test_inactive_person_connection_deleted_and_revoked(api, field, value):
    provider = Provider(api)
    provider.connect()
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO registry_metadata(key,value_json) VALUES('people',?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                  (json.dumps({"people": [{"id": "ana", field: value}]}),))
    provider.sync()
    assert provider.service.load("human:ana") is None
    async def finish():
        await asyncio.gather(*list(provider.service.revocations))
    api.portal.call(finish)
    assert any(path == "/oauth2/revoke" for path, _ in provider.calls)
    assert not any(path == "/mcp" for path, _ in provider.calls)


def test_scheduler_isolates_corrupt_metadata_without_decryption(api):
    provider = Provider(api)
    provider.connect()
    provider.connect("ben-test")
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE granola_connections SET metadata_json='{' WHERE actor='human:ana'")
    scheduled = []
    async def fake_sync(actor):
        scheduled.append(actor)
    provider.service.sync = fake_sync
    def no_decryption(*args):
        raise AssertionError("Scheduling must not decrypt")
    provider.service.load = no_decryption
    async def exercise():
        await provider.service.tick()
        provider.now += 31
        await provider.service.tick()
        await asyncio.gather(*list(provider.service.jobs.values()))
    api.portal.call(exercise)
    assert scheduled == ["human:ben"]


@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://granola.ai/device", "https://granola.ai.example.com/device", "https://example.com/device"])
def test_untrusted_verification_urls_rejected(api, url):
    provider = Provider(api)
    previous = provider.handle
    def handle(request):
        response = previous(request)
        if request.url.path == "/oauth2/device_authorization":
            return httpx.Response(200, json={**response.json(), "verification_uri_complete": url})
        return response
    provider.service.transport = httpx.MockTransport(handle)
    response = api.post(BASE + "/connect", headers=headers("ana-test"))
    assert response.status_code == 503 and url not in response.text
    assert provider.service.load("human:ana") is None


def test_reconnect_expiry_preserves_old_token_and_success_resets_cursor(api):
    provider = Provider(api)
    provider.connect()
    provider.sync()
    old = provider.service.load("human:ana")
    api.post(BASE + "/connect", headers=headers("ana-test"))
    assert provider.service.load("human:ana")[2]["previous_secret"]["refresh_token"] == old[2]["refresh_token"]
    provider.now += 601
    response = api.get(BASE + "/connect/status", headers=headers("ana-test"))
    assert response.json()["connected"]
    assert provider.service.load("human:ana")[1]["cursor"] == old[1]["cursor"]
    provider.connect()
    assert "cursor" not in provider.service.load("human:ana")[1]
    async def finish():
        await asyncio.gather(*list(provider.service.revocations))
    api.portal.call(finish)
    assert any(path == "/oauth2/revoke" for path, _ in provider.calls)


def test_transcript_retry_after_plan_upgrade(api):
    provider = Provider(api)
    provider.paid = True
    provider.connect()
    previous = provider.handle
    denied = True
    transcript_calls = []
    def handle(request):
        if request.url.path == "/mcp":
            name = json.loads(request.content).get("params", {}).get("name")
            if name == "get_meetings":
                return httpx.Response(200, json={"result": {"structuredContent": {"meetings": [
                    {"id": f"note-{i}", "summary": "Shared summary"} for i in range(4)]}}})
            if name == "get_meeting_transcript":
                transcript_calls.append(request)
                if denied:
                    return httpx.Response(200, json={"result": {"isError": True}})
        return previous(request)
    provider.service.transport = httpx.MockTransport(handle)
    provider.sync()
    assert len(transcript_calls) == 3
    assert provider.service.load("human:ana")[1]["transcripts_unavailable"]
    denied = False
    provider.sync()
    assert len(transcript_calls) == 7
    assert not provider.service.load("human:ana")[1]["transcripts_unavailable"]


def test_guarded_oauth_seconds_and_xml_attributes(api):
    from backend.granola_mcp import GranolaMCP
    provider = Provider(api)
    previous = provider.handle
    def handle(request):
        response = previous(request)
        if request.url.path in ("/oauth2/device_authorization", "/oauth2/token"):
            return httpx.Response(200, json={**response.json(), "interval": "unknown", "expires_in": "unknown"})
        return response
    provider.service.transport = httpx.MockTransport(handle)
    assert provider.connect()["connected"]
    provider.now += 3600
    provider.sync()
    assert provider.service.load("human:ana")[2]["expiry"] > provider.now
    row = GranolaMCP.xml_content('<meeting id="doc" title="Planning" date="2026-10-01" summary="Ship it"/>')["meetings"][0]
    assert row["title"] == "Planning" and row["date"] == "2026-10-01"


def test_shared_pace_and_restart_stagger(api):
    provider = Provider(api)
    provider.connect()
    provider.connect("ben-test")
    starts = []
    async def fake_sync(actor):
        starts.append((actor, provider.now))
        saved = await asyncio.to_thread(provider.service.load, actor)
        saved[1]["last_attempt"] = provider.now
        await asyncio.to_thread(provider.service.save, *saved)
    provider.service.sync = fake_sync
    async def exercise():
        await provider.service.tick()
        await asyncio.gather(*list(provider.service.jobs.values()))
        assert len(starts) == 1
        provider.now += 5
        await provider.service.tick()
        await asyncio.gather(*list(provider.service.jobs.values()))
        assert len(starts) == 2 and starts[1][1] - starts[0][1] >= 5
        provider.service.next_call = provider.now
        times = []
        async def call():
            await provider.service.http("GET", "https://mcp-auth.granola.ai/.well-known/oauth-authorization-server")
            times.append(provider.now)
        await asyncio.gather(call(), call(), call())
        assert times[1] - times[0] >= 1 and times[2] - times[1] >= 1
    api.portal.call(exercise)


def test_poll_invalid_client_returns_terminal_state(api):
    provider = Provider(api)
    provider.poll_errors = ["invalid_client"]
    status = provider.connect()
    assert status["state"] == "needs_signin" and status["needs_signin"] and not status["connected"]


def test_bad_id_in_batch_does_not_block_healthy_meeting(api):
    provider = Provider(api)
    provider.connect()
    previous = provider.handle
    def handle(request):
        if request.url.path == "/mcp":
            body = json.loads(request.content)
            name = body.get("params", {}).get("name")
            if name == "list_meetings":
                return httpx.Response(200, json={"result": {"structuredContent": {"meetings": [
                    {"id": "bad"}, {"id": "good"}]}}})
            if name == "get_meetings":
                if "bad" in body["params"]["arguments"]["meeting_ids"]:
                    return httpx.Response(200, json={"result": {"isError": True}})
                return httpx.Response(200, json={"result": {"structuredContent": {"meetings": [
                    {"id": "good", "summary": "Shared notes"}]}}})
        return previous(request)
    provider.service.transport = httpx.MockTransport(handle)
    provider.sync()
    status = api.get(BASE, headers=headers("ana-test")).json()
    assert status["last_sync"] and status["imported_count"] == 1 and status["skipped"] == 1


def test_a_gzipped_answer_from_granola_is_read_once():
    """Granola gzips its answers; the client must not decode the body twice (it reported 'unreachable')."""
    import asyncio, gzip
    import httpx
    from backend import granola_mcp
    body = gzip.compress(json.dumps({"client_id": "zipped"}).encode())
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, headers={"Content-Encoding": "gzip", "Content-Type": "application/json"}, content=body))
    client = granola_mcp.GranolaMCP.__new__(granola_mcp.GranolaMCP)
    client.transport = transport
    async def no_pace():
        return None
    client.pace = no_pace
    response = asyncio.run(client.http("POST", granola_mcp.AUTH + "/oauth2/register", json={}))
    assert granola_mcp.GranolaMCP.payload(response) == {"client_id": "zipped"}
