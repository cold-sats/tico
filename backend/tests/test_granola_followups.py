"""Offline regressions for sign-in, retry scheduling and source-owned Granola summaries."""
import asyncio
import base64
import json

import httpx
import pytest

from backend.auth import Identity
from backend.granola_mcp import GranolaMCP, RATE_LIMIT_RETRY
from backend.tests.test_granola_mcp import BASE, Provider, api, headers  # noqa: F401
from backend.tests.test_granola_rate_limits import NotesProvider, rate_limit
from backend.tests.test_media import import_meeting


def metadata(provider, **changes):
    saved = provider.service.load("human:ana")
    saved[1].update(changes)
    provider.service.save(*saved)
    return saved


@pytest.mark.parametrize("claim,expected", [
    ({"email": "account@example.com", "email_verified": True}, "account@example.com"),
    ({"email": "account@example.com", "email_verified": False}, None),
    ({"email": "not an email"}, None),
    ({"sub": "provider-person"}, None),
])
def test_account_email_is_display_only_and_omits_missing_or_unverified_claims(api, claim, expected):
    provider = Provider(api)
    original = provider.handle
    payload = base64.urlsafe_b64encode(json.dumps(claim).encode()).decode().rstrip("=")
    token = "header." + payload + ".signature"

    def handle(request):
        response = original(request)
        if request.url.path == "/oauth2/token":
            return httpx.Response(200, json={**response.json(), "id_token": token})
        return response

    provider.service.transport = httpx.MockTransport(handle)
    assert provider.connect()["email"] == expected
    saved = provider.service.load("human:ana")
    assert "id_token" not in saved[2] and token not in json.dumps(saved[1])


@pytest.mark.parametrize("retry_after", [None, "42", "600"])
def test_scheduled_rate_limit_retry_runs_at_five_minutes_or_provider_deadline(api, retry_after):
    provider = NotesProvider(api)
    provider.connect()
    metadata(provider, skipped=50)
    provider.responses = [rate_limit(retry_after=retry_after) for _ in range(4)]
    provider.sync()
    meta = provider.service.load("human:ana")[1]
    assert meta["skipped"] == 0
    deadline = meta["retry_after"]
    assert deadline - provider.now == max(RATE_LIMIT_RETRY, float(retry_after or 0))

    async def exercise():
        before = len(provider.notes_calls)
        provider.now = deadline - 1
        await provider.service.tick()
        assert not provider.service.jobs and len(provider.notes_calls) == before
        who = Identity("human:ana", "human", "ana@acme.example")
        assert (await provider.service.trigger(who))["state"] == "recent", "Manual sync also honors throttling"
        provider.now = deadline
        await provider.service.tick()
        await asyncio.gather(*list(provider.service.jobs.values()))
        assert len(provider.notes_calls) == before + 1

    api.portal.call(exercise)
    assert provider.service.load("human:ana")[1]["last_error"] is None


def test_refresh_rate_limit_keeps_token_and_honors_provider_deadline(api):
    provider = Provider(api)
    provider.connect()
    original = provider.handle

    def handle(request):
        if request.url.path == "/oauth2/token":
            return httpx.Response(429, headers={"Retry-After": "900"}, json={})
        return original(request)

    provider.service.transport = httpx.MockTransport(handle)
    provider.now += 3600
    provider.sync()
    saved = provider.service.load("human:ana")
    assert saved[2]["refresh_token"] == "fake-refresh-sensitive"
    assert saved[1]["last_error"] == "rate_limited: refresh_token"
    assert saved[1]["retry_after"] == provider.now + 900


@pytest.mark.parametrize("kind", ["tool", "rpc", "http"])
def test_optional_account_info_rate_limit_stops_calls_and_retries_metadata_later(api, kind):
    provider = NotesProvider(api)
    provider.account_result = rate_limit(kind, retry_after="900")
    provider.connect()
    provider.sync()
    saved = provider.service.load("human:ana")
    assert saved[1]["last_error"] == "rate_limited: get_account_info"
    assert saved[1]["retry_after"] == provider.now + 900
    assert not saved[1].get("account_info_checked")
    assert not provider.notes_calls and not provider.ranges
    assert saved[2]["refresh_token"] == "fake-refresh-sensitive"
    before = provider.account_calls
    provider.account_result = httpx.Response(200, json={"result": {"structuredContent": {
        "email": "account@example.com", "plan": "business"}}})
    provider.now = saved[1]["retry_after"]
    provider.sync()
    meta = provider.service.load("human:ana")[1]
    assert provider.account_calls == before + 1
    assert meta["account_info_checked"] and meta["email"] == "account@example.com"
    assert meta["plan_hint"] == "paid" and meta["last_sync"] and meta["imported_count"] == 2


@pytest.mark.parametrize("failure", ["server", "network"])
def test_optional_account_info_transient_failure_can_retry_next_sync(api, failure):
    provider = NotesProvider(api)
    provider.account_result = httpx.Response(503, json={})
    provider.connect()
    original = provider.handle

    def handle(request):
        response = original(request)
        if request.url.path == "/mcp" and json.loads(request.content).get("params", {}).get("name") == "get_account_info" and failure == "network":
            raise httpx.ConnectError("fake-provider-sensitive", request=request)
        return response

    provider.service.transport = httpx.MockTransport(handle)
    provider.sync()
    meta = provider.service.load("human:ana")[1]
    assert not meta.get("account_info_checked") and meta["last_sync"] and meta["imported_count"] == 2
    provider.account_result = httpx.Response(200, json={"result": {"structuredContent": {"plan": "paid"}}})
    provider.service.transport = httpx.MockTransport(original)
    provider.sync()
    meta = provider.service.load("human:ana")[1]
    assert provider.account_calls == 2 and meta["account_info_checked"] and meta["plan_hint"] == "paid"


def test_transcript_rejected_refresh_preserves_needs_signin_reason(api):
    provider = Provider(api)
    provider.paid = True
    provider.connect()
    original = provider.handle

    def handle(request):
        if request.url.path == "/mcp" and json.loads(request.content).get("params", {}).get("name") == "get_meeting_transcript":
            return httpx.Response(401, json={})
        return original(request)

    provider.refresh_error = True
    provider.service.transport = httpx.MockTransport(handle)
    provider.sync()
    status = api.get(BASE, headers=headers()).json()
    assert status["needs_signin"] and not status["connected"]
    assert status["last_error"] == "Granola needs sign-in again"
    assert not provider.service.load("human:ana")[2].get("refresh_token")
    assert status["imported_count"] == 0 and status["skipped"] == 0


@pytest.mark.parametrize("failure", ["network", "rate_limit", "server", "tool_error"])
def test_transient_transcript_failure_never_infers_free_plan(api, failure):
    provider = Provider(api)
    provider.paid = True
    provider.connect()
    metadata(provider, account_plan_hint="paid", plan_hint="paid")
    original = provider.handle

    def handle(request):
        if request.url.path == "/mcp" and json.loads(request.content).get("params", {}).get("name") == "get_meeting_transcript":
            if failure == "network":
                raise httpx.ConnectError("fake-provider-sensitive", request=request)
            if failure == "rate_limit":
                return httpx.Response(429, headers={"Retry-After": "1"}, json={})
            if failure == "server":
                return httpx.Response(503, json={})
            return httpx.Response(200, json={"result": {"isError": True}})
        return original(request)

    provider.service.transport = httpx.MockTransport(handle)
    provider.sync()
    meta = provider.service.load("human:ana")[1]
    assert meta["plan_hint"] == "paid" and not meta["transcripts_unavailable"]
    assert provider.service.load("human:ana")[2]["refresh_token"] == "fake-refresh-sensitive"
    if failure in ("server", "tool_error"):
        assert meta["last_sync"] and meta["imported_count"] == 1
    else:
        assert meta["last_error"].startswith("rate_limited" if failure == "rate_limit" else "unreachable")


def test_repeated_unknown_transcript_errors_do_not_downgrade_paid_account(api):
    provider = Provider(api)
    provider.paid = True
    provider.connect()
    metadata(provider, account_plan_hint="paid", plan_hint="paid")
    original = provider.handle

    def handle(request):
        if request.url.path == "/mcp":
            name = json.loads(request.content).get("params", {}).get("name")
            if name == "get_meetings":
                return httpx.Response(200, json={"result": {"structuredContent": {"meetings": [
                    {"id": f"note-{i}", "summary": "Shared notes"} for i in range(4)]}}})
            if name == "get_meeting_transcript":
                return httpx.Response(200, json={"result": {"isError": True}})
        return original(request)

    provider.service.transport = httpx.MockTransport(handle)
    provider.sync()
    meta = provider.service.load("human:ana")[1]
    assert meta["transcripts_unavailable"] and meta["plan_hint"] == "paid" and meta["imported_count"] == 4


def test_oauth_connect_and_pending_poll_bypass_background_pace_queue(api):
    provider = Provider(api)
    provider.connect()

    async def exercise():
        # Hold the background queue indefinitely; interactive OAuth must still finish.
        async with provider.service.pace_lock:
            who = Identity("human:ben", "human", "ben@acme.example")
            signin = await asyncio.wait_for(provider.service.connect(who), 1)
            assert signin["user_code"] == "ABCD"
            provider.now += 5
            status = await asyncio.wait_for(provider.service.poll(who), 1)
            assert status["connected"] and status["state"] == "connected"

    api.portal.call(exercise)


@pytest.mark.parametrize("operation", ["connect", "poll"])
def test_interactive_signin_does_not_wait_behind_own_sync(api, operation):
    provider = Provider(api)
    provider.connect()

    async def exercise():
        started = asyncio.Event()

        async def blocked(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()

        provider.service.rpc = blocked
        who = Identity("human:ana", "human", "ana@acme.example")
        await provider.service.trigger(who)
        await started.wait()
        result = await asyncio.wait_for(getattr(provider.service, operation)(who), 1)
        if operation == "connect":
            assert result["user_code"] == "ABCD"
            assert provider.service.metadata(who.actor)["state"] == "pending"
            assert not provider.service.jobs
        else:
            assert result["connected"] and result["syncing"]
            await provider.service.disconnect(who)

    api.portal.call(exercise)


def test_disconnect_blocks_trigger_during_cancellation_and_cannot_resurrect_connection(api):
    provider = Provider(api)
    provider.connect()
    old = provider.service.load("human:ana")

    async def exercise():
        started, cancelling, finish_cancel = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def blocked(*args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelling.set()
                await finish_cancel.wait()
                raise

        provider.service.rpc = blocked
        who = Identity("human:ana", "human", "ana@acme.example")
        await provider.service.trigger(who)
        await started.wait()
        original_job = provider.service.jobs[who.actor]
        deleting = asyncio.create_task(provider.service.disconnect(who))
        await cancelling.wait()
        assert (await provider.service.trigger(who))["state"] == "off"
        assert provider.service.jobs[who.actor] is original_job
        finish_cancel.set()
        await asyncio.wait_for(deleting, 1)
        assert not provider.service.jobs and provider.service.load(who.actor) is None
        # A late save from an old worker cannot insert the deleted row.
        await asyncio.to_thread(provider.service.save, *old)
        assert provider.service.load(who.actor) is None
        assert (await provider.service.trigger(who))["state"] == "off"

    api.portal.call(exercise)


@pytest.mark.parametrize("human_edit", [False, True, "api"])
def test_regenerated_summary_updates_only_source_owned_notes_and_preserves_other_fields(api, human_edit):
    provider = Provider(api)
    provider.paid = True
    provider.connect()
    provider.sync()
    with api.app.state.store.read() as c:
        rid = c.execute("SELECT id FROM meetings").fetchone()[0]
    record = api.get("/api/meetings/" + rid, headers=headers()).json()
    original_notes = record["notes"]
    edit = api.post("/api/meetings/" + rid + "/edit", json={"version": record["version"],
                    "title": "Human title", "note": "Human meeting log"}, headers=headers())
    assert edit.status_code == 200
    if human_edit is True:
        with api.app.state.store.transaction() as c:
            from backend.media import save
            from backend.meetings import get
            stored = get(rid, c)
            save(c, stored["metadata"], notes="Human summary")
    elif human_edit == "api":
        import_meeting(api, source="granola", external_id="not_12345678901234", notes="API summary", private=True)
    before = api.get("/api/meetings/" + rid, headers=headers()).json()
    original = provider.handle

    def handle(request):
        if request.url.path == "/mcp" and json.loads(request.content).get("params", {}).get("name") == "get_meetings":
            return httpx.Response(200, json={"result": {"structuredContent": {"meetings": [
                {"id": "not_12345678901234", "title": "Provider title", "summary": "Regenerated summary"}]}}})
        return original(request)

    provider.service.transport = httpx.MockTransport(handle)
    provider.sync()
    after = api.get("/api/meetings/" + rid, headers=headers()).json()
    assert after["notes"] == ("Human summary" if human_edit is True else "API summary" if human_edit == "api" else "Regenerated summary")
    for key in ("title", "note", "started", "participants", "turns", "private", "review_state", "transcript_readable"):
        assert after[key] == before[key]
    versions = api.get("/api/meetings/" + rid + "/versions", headers=headers()).json()
    assert original_notes in [v["notes"] for v in versions["versions"]]
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM meetings").fetchone()[0] == 1
