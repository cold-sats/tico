"""A company's own frontend on another origin: CORS, the sign-in redirect allowlist, and the
bearer session it earns through the OIDC flow (docs/custom-frontend.md)."""

import base64
import hashlib
import json
import re
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
import yaml
from fastapi.testclient import TestClient

from backend import cors
from backend.app import create_app
from backend.auth import Identity
from backend.config import Settings
from backend.store import H, encode
from backend.tests.test_api import headers
from backend.tests.test_oidc import provider, signin  # noqa: F401  (fixtures)

APP = "http://localhost:5173"
PROD = "https://app.acme.example"
EVIL = "https://evil.example"


@pytest.fixture
def api(tmp_path):
    """The api fixture of test_api, with a frontend allowed to call it. Fixtures that ask for `api` get this one."""
    registry = tmp_path / "hub-registry"
    registry.mkdir()
    (registry / "hub-access.yaml").write_text(yaml.safe_dump({"owner": "ana@acme.example", "bot_admins": ["ben@acme.example"]}))
    app = create_app(Settings(db_path=tmp_path / "hub.db", registry_dir=registry, cors_origins=APP + ", " + PROD, test_identities={
        "ana-test": Identity("human:ana", "owner", "ana@acme.example"),
        "ben-test": Identity("human:ben", "human", "ben@acme.example")}))
    with TestClient(app) as client:
        with app.state.store.transaction() as c:
            H.sync_registry(c, {"ops": {"name": "ops", "runtime": "fake", "status": "active"}},
                            {"people": [{"id": p, "email": p + "@acme.example"} for p in ("ana", "ben")]})
            c.execute("INSERT INTO registry_metadata VALUES('people',?)", (encode({"people": [
                {"id": "ana", "email": "ana@acme.example", "primary_for": ["*"]},
                {"id": "ben", "email": "ben@acme.example"}]}),))
            c.execute("INSERT INTO bot_config(bot,config_json,operator) VALUES('ops',?,'ana')",
                      (encode({"name": "ops", "runtime": "fake", "status": "active"}),))
            c.execute("INSERT INTO registry_metadata VALUES('onboarding',?)", (encode({"completed": "2026-01-01T00:00:00Z"}),))
        yield client


def challenge_for(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


VERIFIER = "v" * 64
CHALLENGE = challenge_for(VERIFIER)


# ---- CORS -------------------------------------------------------------------------------

def test_an_allowed_origin_gets_credentialed_cors_headers(api):
    r = api.get("/api/v2/me", headers={**headers(), "Origin": APP})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == APP
    assert r.headers["access-control-allow-credentials"] == "true"
    assert "origin" in r.headers["vary"].lower()
    assert "server-timing" in r.headers["access-control-expose-headers"].lower()
    assert api.get("/api/v2/me", headers={**headers(), "Origin": PROD}).headers["access-control-allow-origin"] == PROD


def test_other_origins_get_no_cors_headers_and_never_a_wildcard(api):
    for origin in (EVIL, "http://localhost:5174", "https://app.acme.example:8443", "http://app.acme.example",
                   "https://sub.app.acme.example", "null"):
        r = api.get("/api/v2/me", headers={**headers(), "Origin": origin})
        assert not [k for k in r.headers if k.lower().startswith("access-control-")], origin
    assert api.get("/api/v2/me", headers=headers()).headers.get("access-control-allow-origin") is None


def test_the_preflight_is_answered_without_a_sign_in_for_allowed_origins_only(api):
    ask = {"Origin": APP, "Access-Control-Request-Method": "POST",
           "Access-Control-Request-Headers": "authorization, content-type, idempotency-key"}
    r = api.options("/api/v2/tasks", headers=ask)
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == APP and r.headers["access-control-allow-credentials"] == "true"
    assert "POST" in r.headers["access-control-allow-methods"]
    allowed = r.headers["access-control-allow-headers"].lower()
    assert all(h in allowed for h in ("authorization", "content-type", "idempotency-key"))
    assert int(r.headers["access-control-max-age"]) > 0
    bad = api.options("/api/v2/tasks", headers={**ask, "Origin": EVIL})
    # Answered like any other unsigned request, with nothing that lets the browser go on.
    assert bad.status_code in (400, 401) and not [k for k in bad.headers if k.lower().startswith("access-control-")]
    odd = api.options("/api/v2/tasks", headers={**ask, "Access-Control-Request-Headers": "x-secret"})
    assert odd.status_code == 400


def test_an_error_still_carries_the_headers_so_the_page_can_read_it(api):
    r = api.get("/api/v2/me", headers={"Origin": APP})
    assert r.status_code == 401 and r.headers["access-control-allow-origin"] == APP
    assert r.json()["error"]["code"] == "identity"
    r = api.post("/api/v2/tasks", json={}, headers={**headers(), "Origin": APP})
    assert r.status_code == 422 and r.headers["access-control-allow-origin"] == APP


def test_browser_writes_pass_only_from_the_server_or_an_allowed_origin(api):
    body = {"text": "hello"}
    ok = api.post("/api/v2/chat/ops", json=body, headers={**headers(), "Origin": APP})
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == APP
    refused = api.post("/api/v2/chat/ops", json=body, headers={**headers(), "Origin": EVIL})
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "origin"


def test_nothing_is_added_when_no_origin_is_configured(tmp_path):
    app = create_app(Settings(db_path=tmp_path / "hub.db", test_identities={"t": Identity("human:ana", "owner", "a@x.example")}))
    with TestClient(app) as client:
        r = client.options("/api/v2/me", headers={"Origin": APP, "Access-Control-Request-Method": "GET"})
        assert not [k for k in r.headers if k.lower().startswith("access-control-")]
        r = client.get("/healthz", headers={"Origin": APP})
        assert "access-control-allow-origin" not in r.headers


@pytest.mark.parametrize("value", ["*", "https://*.acme.example", "null", "https://app.acme.example/", "https://app.acme.example/x",
                                   "http://app.acme.example", "ftp://app.acme.example", "app.acme.example",
                                   "https://user@app.acme.example", "https://app.acme.example?x=1", "http://localhost:5173/x"])
def test_the_allowlist_takes_exact_origins_only(value):
    with pytest.raises(RuntimeError, match="TICO_CORS_ORIGINS"):
        cors.parse(value)


def test_the_allowlist_is_parsed_and_normalised():
    assert cors.parse("") == () and cors.parse(" , ") == ()
    assert cors.parse("HTTPS://App.Acme.example, http://localhost:5173,http://127.0.0.1:3000, https://app.acme.example") == (
        "https://app.acme.example", "http://localhost:5173", "http://127.0.0.1:3000")


# ---- sign-in for a frontend on another origin -----------------------------------------------

def start(signin, target=APP + "/", challenge=CHALLENGE, **query):
    return signin.api.get("/auth/login", params={"next": target, **({"code_challenge": challenge} if challenge else {}), **query},
                          follow_redirects=False)


def sign_in(signin, target=APP + "/", claims=None):
    began = start(signin, target)
    assert began.status_code == 302, began.text
    code, state = signin.fake.approve(began.headers["location"], **(claims or {}))
    return signin.api.get("/auth/callback", params={"code": code, "state": state}, follow_redirects=False)


def tico_code(response):
    assert response.status_code == 302, response.text
    location = urlparse(response.headers["location"])
    return location, parse_qs(location.fragment)["tico_code"][0]


def exchange(signin, code, verifier=VERIFIER, origin=APP):
    return signin.api.post("/auth/token", json={"code": code, "code_verifier": verifier},
                           headers={"Origin": origin} if origin else {})


def test_a_frontend_signs_in_and_gets_a_code_then_a_bearer_session(signin):
    done = sign_in(signin, APP + "/app/?tab=tasks")
    location, code = tico_code(done)
    assert (location.scheme, location.netloc, location.path, location.query) == ("http", "localhost:5173", "/app/", "tab=tasks")
    assert "tico_session" not in done.headers.get("set-cookie", "") and signin.sessions() == []      # no cookie, no session yet
    assert me_status(signin, {}) == 401

    made = exchange(signin, code)
    assert made.status_code == 200, made.text
    assert made.headers["access-control-allow-origin"] == APP and made.headers["cache-control"].startswith("no-store")
    token = made.json()
    assert token["token_type"] == "Bearer" and token["access_token"].startswith("tico_st_") and token["person"] == "ben"
    assert token["expires_in"] == signin.settings.session_absolute_seconds
    bearer = {"Authorization": "Bearer " + token["access_token"], "Origin": APP}
    who = signin.api.get("/api/v2/me", headers=bearer)
    assert who.status_code == 200 and who.json()["actor"] == "human:ben" and who.json()["role"] == "human"
    assert who.headers["access-control-allow-credentials"] == "true"
    # Only a hash is kept, and the session answers as a cookie session would.
    assert token["access_token"][len("tico_st_"):] not in json.dumps([dict(r) for r in signin.sessions()])
    signin.api.cookies.clear()
    assert signin.api.get("/api/v2/needs-you", headers=bearer).status_code == 200
    assert signin.api.post("/api/v2/chat/coo", json={"text": "hi"}, headers={**bearer, "Idempotency-Key": str(uuid.uuid4())}).status_code in (200, 403, 404)

    out = signin.api.post("/auth/token/revoke", headers=bearer)
    assert out.status_code == 200 and out.json() == {"revoked": True}
    assert signin.api.get("/api/v2/me", headers=bearer).status_code == 401
    assert signin.sessions() == []


def me_status(signin, extra):
    return signin.api.get("/api/v2/me", headers=extra).status_code


def test_the_code_is_single_use_and_bound_to_the_verifier_and_the_origin(signin):
    _, code = tico_code(sign_in(signin))
    assert exchange(signin, code, verifier="w" * 64).status_code == 400          # wrong verifier burns the code
    assert exchange(signin, code).status_code == 400
    _, code = tico_code(sign_in(signin))
    assert exchange(signin, code, origin=PROD).status_code == 400                 # another allowed origin
    assert exchange(signin, code).status_code == 400
    _, code = tico_code(sign_in(signin))
    assert exchange(signin, code, origin=None).status_code == 400                 # no Origin: not a browser
    _, code = tico_code(sign_in(signin))
    assert exchange(signin, code, origin=EVIL).status_code == 400
    _, code = tico_code(sign_in(signin))
    assert exchange(signin, code, verifier="short").status_code == 400
    assert signin.sessions() == []
    _, code = tico_code(sign_in(signin))
    assert exchange(signin, code).status_code == 200
    assert exchange(signin, code).status_code == 400
    assert exchange(signin, "not-a-code").json()["error"]["code"] == "invalid_grant"


def test_a_code_expires_after_a_minute_and_junk_bodies_are_refused(signin):
    _, code = tico_code(sign_in(signin))
    with signin.auth.store.transaction() as c:
        c.execute("UPDATE oidc_codes SET expires_at='2000-01-01T00:00:00Z'")
    assert exchange(signin, code).status_code == 400
    for body in ({}, {"code": 1, "code_verifier": VERIFIER}, [], "x"):
        r = signin.api.post("/auth/token", json=body, headers={"Origin": APP})
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
    assert signin.api.post("/auth/token", content=b"{nope", headers={"Origin": APP}).status_code == 400


@pytest.mark.parametrize("target", [
    EVIL + "/", "//evil.example/", "///evil.example", "\\\\evil.example", "javascript:alert(1)", "data:text/html,x",
    "https://app.acme.example.evil.example/", "https://app.acme.example@evil.example/", "http://localhost:5173@evil.example/",
    "https://evil.example/https://app.acme.example/", "https://app.acme.example:444/", "http://app.acme.example/",
    "http://localhost:5174/", "http://localhost:5173/#frag", "http://user:pw@localhost:5173/", "http://localhost:5173/\r\nX: y",
    "http://localhost:5173//evil.example", "http://localhost:5173/\\evil.example", "", "app.acme.example"])
def test_an_open_redirect_is_refused(signin, target):
    began = start(signin, target)
    if target in ("//evil.example/", "///evil.example", "\\\\evil.example", "", "app.acme.example"):
        # Not an absolute URL: the same rules as ever, so it lands on this server's own "/".
        assert began.status_code in (302, 400)
        if began.status_code == 302:
            assert urlparse(began.headers["location"]).path.endswith("/authorize")
            code, state = signin.fake.approve(began.headers["location"])
            done = signin.api.get("/auth/callback", params={"code": code, "state": state}, follow_redirects=False)
            assert done.headers["location"] == "/" and "tico_session" in done.headers["set-cookie"]
        return
    assert began.status_code == 400 and "location" not in began.headers and "set-cookie" not in began.headers
    assert began.headers["content-type"].startswith("text/html") and signin.fake.codes == {}


def test_a_frontend_must_send_a_pkce_challenge(signin):
    for bad in ("", "short", "x" * 44, "!" * 43):
        assert start(signin, challenge=bad).status_code == 400
    assert start(signin, PROD + "/").status_code == 302


def test_a_frontend_signing_in_off_the_roster_gets_no_code(signin):
    result = sign_in(signin, claims={"email": "stranger@acme.example"})
    assert result.status_code == 403 and "location" not in result.headers
    with signin.auth.store.read() as c:
        assert c.execute("SELECT count(*) FROM oidc_codes").fetchone()[0] == 0


def test_the_builtin_sign_in_still_returns_to_a_path_and_sets_its_cookie(signin):
    began = signin.api.get("/auth/login", params={"next": "/tasks"}, follow_redirects=False)
    code, state = signin.fake.approve(began.headers["location"])
    done = signin.api.get("/auth/callback", params={"code": code, "state": state}, follow_redirects=False)
    assert done.headers["location"] == "/tasks" and "tico_session=" in done.headers["set-cookie"]


def test_a_bearer_session_is_refused_without_built_in_sign_in(api):
    assert api.get("/api/v2/me", headers={"Authorization": "Bearer tico_st_" + "a" * 40}).status_code == 401
    assert api.post("/auth/token", json={"code": "a", "code_verifier": "b" * 43}, headers={"Origin": APP}).status_code == 404


def test_a_session_ended_by_the_server_ends_the_bearer(signin):
    _, code = tico_code(sign_in(signin))
    bearer = {"Authorization": "Bearer " + exchange(signin, code).json()["access_token"]}
    assert signin.api.get("/api/v2/me", headers=bearer).status_code == 200
    with signin.auth.store.transaction() as c:
        c.execute("UPDATE oidc_sessions SET last_seen='2000-01-01T00:00:00Z'")
    r = signin.api.get("/api/v2/me", headers=bearer)
    assert r.status_code == 401 and r.json()["error"]["sign_in"] == "/auth/login"
