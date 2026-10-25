"""Linking a self-run server to its Tico company (backend/company_server.py), against a fake HQ."""
import asyncio
import hashlib
import json
import time

import httpx
import pytest

from backend import company_server as CS
from backend.tests.test_api import api, as_member, headers  # noqa: F401

CODE = "synthetic_" + "s" * 33
INSTALL_ID = "cc4a8541-2661-4eb8-a1d3-a34e913571c0"
COMPANY = {"id": "2615c13e-d164-414f-94a5-782f0ea1b2f8", "name": "Acme", "slug": "acme"}
SERVER_KEY = "tsk_synthetic_server_key_0123456789"
PATH = "/api/v2/company/server-connection"


def reply(status, body=None):
    return httpx.Response(status, stream=httpx.ByteStream(json.dumps(body).encode() if body is not None else b""))


@pytest.fixture
def hq(api, monkeypatch):
    """A fake HQ: `answers[(method, path)]` is a function of the request; `seen` keeps every request."""
    monkeypatch.setenv("TICO_HQ_URL", "https://api.tico.dev")
    with api.app.state.store.transaction() as c:
        c.execute("INSERT OR REPLACE INTO registry_metadata VALUES('usage-count',?)", (json.dumps({"install_id": INSTALL_ID}),))
    fake = type("HQ", (), {"seen": [], "answers": {}})()

    def handle(request):
        fake.seen.append(request)
        return fake.answers[(request.method, request.url.path)](request)
    monkeypatch.setattr(CS, "TRANSPORT", httpx.MockTransport(handle))
    return fake


def connected(api, hq):
    def connect(request):
        body = json.loads(request.content)
        # HQ fetches the proof from the server itself, with no sign-in, while the connect waits.
        fetched = api.get(CS.PROOF_PATH)
        assert fetched.status_code == 200 and fetched.headers["cache-control"] == "no-store"
        if fetched.json() != {"proof_sha256": hashlib.sha256(body["proof"].encode()).hexdigest()}:
            return reply(422, {"error": "proof_failed"})
        return reply(201, {"company": COMPANY, "workspace_id": "ws_1", "server_key": SERVER_KEY,
                           "portal_url": "https://app.tico.dev/servers"})
    hq.answers[("POST", "/v1/portal/server-connection")] = connect
    hq.answers.setdefault(("GET", "/v1/portal/server"), lambda request: reply(200, {
        "company": COMPANY, "workspace_id": "ws_1", "portal_url": "https://app.tico.dev/servers",
        "credit": {"balance_cents": None}}))
    r = api.post(PATH, headers=headers(), json={"code": CODE, "preview": False})
    assert r.status_code == 200, r.text
    return r.json()


def test_preview_then_connect_proves_the_address_and_seals_the_key(api, hq):
    assert api.get(CS.PROOF_PATH).status_code == 404       # nothing pending: no proof, and no sign-in asked
    hq.answers[("POST", "/v1/portal/server-connection")] = lambda request: (
        reply(200, {"company": COMPANY}) if api.get(CS.PROOF_PATH).status_code == 404 else reply(500))
    r = api.post(PATH, headers=headers(), json={"code": CODE, "preview": True})
    assert r.status_code == 200 and r.json() == {"company": COMPANY, "preview": True}
    sent = json.loads(hq.seen[0].content)
    assert sent["preview"] is True and sent["install_id"] == INSTALL_ID and sent["public_url"].startswith("http://127.0.0.1")
    assert set(sent) == {"code", "public_url", "install_id", "version", "proof", "preview"}
    assert api.get(PATH, headers=headers()).json() == {"company": None}

    hq.answers[("GET", "/v1/portal/server")] = lambda request: reply(200, {
        "company": COMPANY, "workspace_id": "ws_1", "portal_url": "https://app.tico.dev/servers",
        "credit": {"balance_cents": 700}})
    view = connected(api, hq)
    assert view["company"] == COMPANY and view["portal_url"] == "https://app.tico.dev/servers"
    assert view["credit"] == {"balance_cents": 700} and view["checked"]   # the balance is read right after connecting
    assert api.get(CS.PROOF_PATH).status_code == 404       # the proof ends with the connect
    with api.app.state.store.read() as c:
        everything = json.dumps([list(r) for r in c.execute("SELECT * FROM registry_metadata")]) + \
            json.dumps([list(r) for r in c.execute("SELECT * FROM events")])
        assert CS.view(c)["company"] == COMPANY
    assert SERVER_KEY not in everything and SERVER_KEY not in json.dumps(view)


def test_hq_refusals_and_bad_answers_are_plain_errors(api, hq, monkeypatch):
    for status, body, expected, code in [(409, {"error": "code_used"}, 409, "code_used"),
                                         (404, {"error": "code_unknown"}, 404, "code_unknown"),
                                         (409, {"error": "install_linked"}, 409, "install_linked"),
                                         (418, {"error": "code_used"}, 503, "company_connection_unavailable"),
                                         (201, {"company": COMPANY, "workspace_id": "ws_1", "server_key": "nope",
                                                "portal_url": "https://app.tico.dev/"}, 503, "company_connection_unavailable"),
                                         (201, {"company": COMPANY, "workspace_id": "ws_1", "server_key": SERVER_KEY,
                                                "portal_url": "javascript:alert(1)"}, 503, "company_connection_unavailable")]:
        hq.answers[("POST", "/v1/portal/server-connection")] = lambda request, s=status, b=body: reply(s, b)
        r = api.post(PATH, headers=headers(), json={"code": CODE, "preview": False})
        assert (r.status_code, r.json()["error"]["code"]) == (expected, code), r.text
    assert api.get(PATH, headers=headers()).json() == {"company": None}
    assert api.post(PATH, headers=headers(), json={"code": CODE, "preview": "no"}).status_code == 422
    calls = len(hq.seen)
    monkeypatch.setenv("TICO_HQ_URL", "https://hq.example.com")   # only Tico's own HQ is ever asked
    assert api.post(PATH, headers=headers(), json={"code": CODE, "preview": True}).status_code == 503
    assert len(hq.seen) == calls


def test_only_a_direct_owner_or_admin_manages_the_link(api, hq):
    assert api.get(PATH).status_code == 401
    as_member(api, "ben@acme.example")
    assert api.get(PATH, headers=headers("ben-test")).status_code == 403
    assert api.post(PATH, headers=headers("ben-test"), json={"code": CODE, "preview": True}).status_code == 403
    assert api.delete(PATH, headers=headers("ben-test")).status_code == 403
    assert hq.seen == []


def test_refresh_heartbeat_and_disconnect_use_the_server_key(api, hq):
    connected(api, hq)
    store, vault = api.app.state.store, api.app.state.vault
    hq.answers[("GET", "/v1/portal/server")] = lambda request: reply(200, {
        "company": {**COMPANY, "name": "Acme Inc"}, "workspace_id": "ws_1", "portal_url": "https://app.tico.dev/s",
        "credit": {"balance_cents": 1250}})
    assert api.get(PATH, headers=headers()).json()["company"]["name"] == "Acme"   # fresh: HQ not asked again yet
    view = CS.status(store, vault, now=time.time() + CS.FRESH_S + 1)
    assert view["company"]["name"] == "Acme Inc" and view["credit"] == {"balance_cents": 1250}
    assert hq.seen[-1].headers["authorization"] == "Bearer " + SERVER_KEY

    assert not CS.heartbeat_due(store)                          # connecting counts as today's
    assert CS.heartbeat_due(store, now=time.time() + CS.HEARTBEAT_S + 1)
    hq.answers[("POST", "/v1/portal/server/heartbeat")] = lambda request: reply(204)
    assert CS.heartbeat(store, vault) == "sent"
    assert set(json.loads(hq.seen[-1].content)) == {"version"}

    hq.answers[("DELETE", "/v1/portal/server")] = lambda request: reply(503, {"error": "down"})
    assert api.delete(PATH, headers=headers()).status_code == 503   # HQ must hear it: the key stays until then
    hq.answers[("DELETE", "/v1/portal/server")] = lambda request: reply(204)
    assert api.delete(PATH, headers=headers()).json() == {"company": None}
    assert CS.heartbeat(store, vault) == "gone" and not CS.heartbeat_due(store, now=1e12)


def test_a_new_version_is_due_within_the_hour(api, hq, monkeypatch):
    monkeypatch.setenv("TICO_VERSION", "v0.4.5")
    connected(api, hq)
    store, vault = api.app.state.store, api.app.state.vault
    assert not CS.heartbeat_due(store)                          # connecting told HQ this version
    monkeypatch.setenv("TICO_VERSION", "v0.4.6")                # updated and restarted
    assert CS.heartbeat_due(store)
    hq.answers[("POST", "/v1/portal/server/heartbeat")] = lambda request: reply(503, {"error": "down"})
    assert CS.heartbeat(store, vault) == "failed" and CS.heartbeat_due(store)   # still due: the next hour tries again
    hq.answers[("POST", "/v1/portal/server/heartbeat")] = lambda request: reply(204)
    assert CS.heartbeat(store, vault) == "sent" and json.loads(hq.seen[-1].content) == {"version": "0.4.6"}
    assert not CS.heartbeat_due(store)
    with store.transaction() as c:                              # a record from before the version was kept
        CS._write(c, {k: v for k, v in CS._row(c).items() if k != "version"})
    assert CS.heartbeat_due(store)
    calls = len(hq.seen)
    monkeypatch.setenv("TICO_REHEARSAL", "1")                   # a changed version still sends nothing from a rehearsal
    assert not CS.heartbeat_due(store) and len(hq.seen) == calls


def test_a_key_hq_refuses_is_forgotten(api, hq):
    connected(api, hq)
    hq.answers[("POST", "/v1/portal/server/heartbeat")] = lambda request: reply(401, {"error": "unauthorized"})
    assert CS.heartbeat(api.app.state.store, api.app.state.vault) == "gone"
    assert api.get(PATH, headers=headers()).json() == {"company": None}


def test_rehearsal_sends_hq_nothing_and_keeps_the_link(api, hq, monkeypatch):
    connected(api, hq)
    store, vault = api.app.state.store, api.app.state.vault
    calls = len(hq.seen)
    monkeypatch.setenv("TICO_REHEARSAL", "1")
    assert CS.status(store, vault, now=time.time() + CS.FRESH_S + 1)["company"] == COMPANY
    assert not CS.heartbeat_due(store, now=1e12) and CS.heartbeat(store, vault) == "failed"
    assert api.delete(PATH, headers=headers()).status_code == 409
    assert api.post(PATH, headers=headers(), json={"code": CODE, "preview": True}).status_code == 503
    assert len(hq.seen) == calls and api.get(PATH, headers=headers()).json()["company"] == COMPANY


def test_a_late_401_never_removes_a_newer_connection(api, hq):
    connected(api, hq)
    store, vault = api.app.state.store, api.app.state.vault

    def replaced_then_refused(request):
        # A new connect lands while HQ's refusal of the old key is on its way.
        with store.transaction() as c:
            CS._write(c, {**CS._row(c), "key": vault.cipher.seal(c, CS.CONTEXT, "tsk_newer_synthetic_key_0123456")})
        return reply(401, {"error": "unauthorized"})
    hq.answers[("GET", "/v1/portal/server")] = replaced_then_refused
    CS.status(store, vault, now=time.time() + CS.FRESH_S + 1)
    hq.answers[("DELETE", "/v1/portal/server")] = replaced_then_refused
    assert api.delete(PATH, headers=headers()).json()["company"] == COMPANY
    with store.read() as c:
        assert vault.cipher.unseal(c, CS.CONTEXT, CS._row(c)["key"]) == "tsk_newer_synthetic_key_0123456"


def test_a_slow_answer_is_cut_off_at_the_deadline(api, hq, monkeypatch):
    class Drip(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"{"
            await asyncio.sleep(30)        # a read that never finishes on its own
            yield b"}"
    monkeypatch.setattr(CS, "WAIT_S", 0.5)
    hq.answers[("POST", "/v1/portal/server-connection")] = lambda request: httpx.Response(200, stream=Drip())
    began = time.monotonic()
    r = api.post(PATH, headers=headers(), json={"code": CODE, "preview": True})
    assert r.status_code == 503 and time.monotonic() - began < 5
