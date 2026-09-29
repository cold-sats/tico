"""The GitHub App: manifest, state nonce, secret storage, installation tokens, runner scope."""
import json
import re
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from backend import github_app as G
from backend import hubdb as H
from backend.app import create_app
from backend.auth import Identity
from backend.config import Settings
from backend.store import encode

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                        serialization.NoEncryption()).decode()
PUBLIC = "https://tico.acme.example"


class FakeGitHub:
    def __init__(self):
        self.calls, self.installations = [], [{"id": 77, "account": {"login": "Acme"}}]
        self.ttl = 3600
        self.generate_status = 201
        self.missing, self.selection, self.forbidden = set(), "all", False   # repositories GitHub answers 404 for

    def __call__(self, request):
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, body, request.headers.get("authorization", "")))
        path = request.url.path
        if path.startswith("/app-manifests/"):
            return httpx.Response(201, json={"id": 4242, "slug": "acme-tico", "client_id": "Iv1.abc", "client_secret": "cs",
                                             "webhook_secret": "whs", "pem": PEM, "html_url": "https://github.com/apps/acme-tico"})
        if path == "/app/installations":
            return httpx.Response(200, json=self.installations)
        if path.startswith("/app/installations/") and not path.endswith("/access_tokens"):
            return httpx.Response(200, json={"id": 77, "repository_selection": self.selection})
        if path.startswith("/repos/") and path.count("/") == 3:
            return httpx.Response(404 if path.split("/")[3] in self.missing else 200, json={})
        if path.endswith("/access_tokens"):
            if body and any(name in self.missing for name in body.get("repositories", [])):
                return httpx.Response(403 if self.forbidden else 422, json={"message": "Validation Failed"})
            exp = datetime.now(timezone.utc) + timedelta(seconds=self.ttl)
            return httpx.Response(201, json={"token": "ghs_" + uuid.uuid4().hex, "expires_at": exp.strftime("%Y-%m-%dT%H:%M:%SZ")})
        if path.startswith("/orgs/") and path.endswith("/repos"):
            return httpx.Response(self.generate_status, json={"full_name": path.split("/")[2] + "/" + body["name"],
                                                            "html_url": "https://github.com/" + path.split("/")[2] + "/" + body["name"]})
        if path.endswith("/generate"):
            return httpx.Response(self.generate_status, json={"full_name": body["owner"] + "/" + body["name"],
                                                            "html_url": "https://github.com/" + body["owner"] + "/" + body["name"]})
        return httpx.Response(404)

    def of(self, suffix):
        return [c for c in self.calls if c[1].endswith(suffix)]


@pytest.fixture
def gh(monkeypatch):
    fake = FakeGitHub()
    monkeypatch.setattr(G, "TRANSPORT", httpx.MockTransport(fake))
    return fake


@pytest.fixture
def api(tmp_path, gh):
    ids = {"owner-test": Identity("human:ana", "owner", "ana@acme.example"),
           "other-test": Identity("human:ben", "owner", "ben@acme.example"),
           "runner-test": Identity("runner:r1", "runner", runner_id="r1"),
           "bot-test": Identity("bot:cmo", "bot", runner_id="r1", attempt_id="a1"),
           "botops-test": Identity("bot:botops", "bot", runner_id="r1", attempt_id="a2"),
           "person-test": Identity("human:riley", "human", "riley@acme.example")}
    app = create_app(Settings(db_path=tmp_path / "hub.db", public_url=PUBLIC, company_name="Acme", github_owner="Acme",
                              test_identities=ids))
    with TestClient(app, follow_redirects=False) as client:
        with app.state.store.transaction() as c:
            bots = {slug: {"name": slug, "runtime": "fake", "status": "active"} for slug in ("cpo", "cmo", "cfo", "botops")}
            bots["newbie"] = {"name": "newbie", "runtime": "fake", "status": "planned"}
            bots["oldie"] = {"name": "oldie", "runtime": "fake", "status": "archived"}
            H.sync_registry(c, bots, {"people": [{"id": "ana", "email": "ana@acme.example", "team": "leadership"}, {"id": "ben", "email": "ben@acme.example", "team": "leadership"}, {"id": "riley", "email": "riley@acme.example", "team": "leadership"}]})
            repos = {"botops": "emp-botops", "newbie": "emp-newbie", "oldie": "emp-oldie", "cpo": "emp-cpo", "cmo": "https://github.com/Acme/emp-cmo.git", "cfo": "elsewhere/emp-cfo"}
            for slug, config in bots.items():
                c.execute("INSERT INTO bot_config(bot,config_json,team,operator,repo) VALUES(?,?,?,?,?)",
                          (slug, encode(config), "t", "ana", repos[slug]))
            c.execute("INSERT INTO registry_metadata VALUES('onboarding',?)", (encode({"completed": "2026-01-01T00:00:00Z"}),))
        client.app_state = app.state
        yield client


def auth(token="owner-test"):
    return {"Authorization": "Bearer " + token}


def manifest(api, **params):
    r = api.get("/api/v2/github/app/manifest", params={"org": "Acme", **params}, headers=auth())
    assert r.status_code == 200, r.text
    return r.json()


def connect(api, **params):
    state = manifest(api, **params)["state"]
    r = api.get("/api/v2/github/app/callback", params={"code": "the-code", "state": state}, headers=auth())
    assert r.status_code == 302, r.text
    return r


def test_manifest_contents_and_owner_only(api):
    data = manifest(api)
    m = data["manifest"]
    assert data["action"] == f"https://github.com/organizations/Acme/settings/apps/new?state={data['state']}"
    assert m["name"] == "Acme Tico" and m["url"] == PUBLIC and m["public"] is False
    assert m["redirect_url"] == PUBLIC + "/api/v2/github/app/callback"
    assert m["hook_attributes"]["active"] is False
    assert m["default_permissions"] == {"contents": "write", "pull_requests": "write", "issues": "write", "metadata": "read"}
    assert manifest(api, administration="true", name="Custom")["manifest"]["default_permissions"]["administration"] == "write"
    assert manifest(api, name="Custom")["manifest"]["name"] == "Custom"
    plain = api.get("/api/v2/github/app/manifest", params={"org": "Acme"}, headers=auth("nobody"))
    assert plain.status_code == 401
    assert api.get("/api/v2/github/app/manifest", params={"org": "bad org!"}, headers=auth()).status_code == 422


def test_html_form_posts_manifest(api):
    r = api.get("/api/v2/github/app/manifest", params={"org": "Acme", "html": "true"}, headers=auth())
    assert "settings/apps/new?state=" in r.text and "method=post" in r.text


def test_state_is_single_use_and_bound_to_session(api, gh):
    state = manifest(api)["state"]
    bad = api.get("/api/v2/github/app/callback", params={"code": "c", "state": "forged"}, headers=auth())
    assert bad.status_code == 400
    other = api.get("/api/v2/github/app/callback", params={"code": "c", "state": state}, headers=auth("other-test"))
    assert other.status_code == 400 and not gh.of("/conversions")
    # Presenting it from another session burned it.
    assert api.get("/api/v2/github/app/callback", params={"code": "c", "state": state}, headers=auth()).status_code == 400
    state = manifest(api)["state"]
    ok = api.get("/api/v2/github/app/callback", params={"code": "c", "state": state}, headers=auth())
    assert ok.status_code == 302
    replay = api.get("/api/v2/github/app/callback", params={"code": "c", "state": state}, headers=auth())
    assert replay.status_code == 400


def test_expired_state_is_refused(api, gh):
    state = manifest(api)["state"]
    with api.app_state.store.transaction() as c:
        c.execute("UPDATE github_app_states SET created=?", (time.time() - 2 * G.STATE_TTL,))
    assert api.get("/api/v2/github/app/callback", params={"code": "c", "state": state}, headers=auth()).status_code == 400


def test_callback_stores_secrets_and_never_exposes_pem(api, gh, caplog):
    caplog.set_level("DEBUG")
    r = connect(api)
    assert r.headers["location"] == "https://github.com/apps/acme-tico/installations/new"
    assert gh.of("/conversions")[0][1] == "/app-manifests/the-code/conversions"
    status = api.get("/api/v2/github/app", headers=auth())
    body = status.text
    assert status.json()["slug"] == "acme-tico" and status.json()["org"] == "Acme" and status.json()["installed"] is False
    for secret in ("BEGIN", "whs", "PRIVATE KEY", "\"cs\""):
        assert secret not in body
    assert "BEGIN" not in caplog.text
    # At rest: encrypted, not the PEM.
    raw = sqlite3.connect(api.app_state.store.settings.db_path).execute("SELECT * FROM github_app").fetchall()
    assert raw and PEM.encode() not in b"".join(v for v in raw[0] if isinstance(v, bytes))
    assert "PRIVATE KEY" not in json.dumps([str(v) for v in raw[0]])
    assert api.get("/api/v2/github/app/manifest", params={"org": "Acme"}, headers=auth()).status_code == 409


def test_installed_discovers_installation_and_disconnect_forgets(api, gh):
    connect(api)
    r = api.get("/api/v2/github/app/installed", headers=auth())
    assert r.headers["location"].endswith("github=connected")
    assert api.get("/api/v2/github/app", headers=auth()).json()["installed"] is True
    assert api.post("/api/v2/github/app/disconnect", json={}, headers=auth()).status_code == 200
    assert api.get("/api/v2/github/app", headers=auth()).json() == {"connected": False}


def test_jwt_claims_and_repo_scoped_token(api, gh):
    connect(api)
    r = api.post("/api/v2/github/token", json={"bot": "cpo"}, headers=auth("owner-test"))
    # An owner is neither the bot nor its runner.
    assert r.status_code == 403
    runner_token(api, "cpo")
    r = api.post("/api/v2/github/token", json={"bot": "cpo"}, headers=auth("runner-test"))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["repository"] == "Acme/emp-cpo" and data["token"].startswith("ghs_")
    method, path, body, header = gh.of("/access_tokens")[0]
    assert path == "/app/installations/77/access_tokens"
    assert body == {"repositories": ["emp-cpo"], "permissions": {"contents": "write", "pull_requests": "write",
                                                                   "issues": "write", "metadata": "read"}}
    claims = jwt.decode(header.removeprefix("Bearer "), KEY.public_key(), algorithms=["RS256"], options={"verify_exp": False})
    assert claims["iss"] == "4242" and claims["exp"] - claims["iat"] <= 660 and claims["iat"] <= time.time() - 59
    assert claims["exp"] <= time.time() + 600


def test_token_cache_until_five_minutes_before_expiry(api, gh):
    connect(api)
    runner_token(api, "cpo")
    ask = lambda: api.post("/api/v2/github/token", json={"bot": "cpo"}, headers=auth("runner-test")).json()["token"]
    first = ask()
    assert ask() == first and len(gh.of("/access_tokens")) == 1
    service = api.app_state.github_app
    for entry in service.cache.values():
        entry["exp"] = time.time() + 200          # inside the five-minute margin
    assert ask() != first and len(gh.of("/access_tokens")) == 2


def runner_token(api, bot):
    with api.app_state.store.transaction() as c:
        if not c.execute("SELECT 1 FROM runners WHERE id='r1'").fetchone():
            cols = [r[1] for r in c.execute("PRAGMA table_info(runners)")]
            values = {"id": "r1", "operator": "ana", "label": "mac", "token_hash": "x", "created": H.now(), "created_by": "ana",
                      "last_seen": H.now(), "hostname": "h", "version": "1", "state": "active"}
            use = {k: v for k, v in values.items() if k in cols}
            c.execute(f"INSERT INTO runners({','.join(use)}) VALUES({','.join('?' * len(use))})", tuple(use.values()))
        c.execute("INSERT OR REPLACE INTO assignments VALUES(?,?,?,?,?)", (bot, "r1", 1, H.now(), "ana"))


def test_runner_refuses_bot_it_does_not_run_and_repo_outside_config(api, gh):
    connect(api)
    runner_token(api, "cpo")
    r = api.post("/api/v2/github/token", json={"bot": "cmo"}, headers=auth("runner-test"))
    assert r.status_code == 403 and not gh.of("/access_tokens")
    runner_token(api, "cfo")           # runs it, but its repo belongs to another org
    r = api.post("/api/v2/github/token", json={"bot": "cfo"}, headers=auth("runner-test"))
    assert r.status_code == 403 and "connected organization" in r.text and not gh.of("/access_tokens")
    # A bot's own turn token names only itself.
    assert api.post("/api/v2/github/token", json={"bot": "cpo"}, headers=auth("bot-test")).status_code in (403, 409)


def test_no_app_means_not_configured(api):
    runner_token(api, "cpo")
    r = api.post("/api/v2/github/token", json={"bot": "cpo"}, headers=auth("runner-test"))
    assert r.status_code == 200 and r.json() == {"configured": False}


def test_create_bot_repo(api, gh):
    connect(api, administration="true")
    r = api.post("/api/v2/github/repos", json={"slug": "botops"}, headers=auth())
    assert r.status_code == 200, r.text
    assert r.json()["repository"] == "Acme/emp-botops"
    method, path, body, _ = gh.of("/generate")[0]
    assert path == "/repos/ticoteam/botops/generate" and body["private"] is True and body["name"] == "emp-botops"
    assert gh.of("/access_tokens")[0][2]["permissions"] == {"administration": "write", "contents": "read"}
    assert "repositories" not in gh.of("/access_tokens")[0][2]


def test_create_bot_repo_without_permission_says_to_do_it_manually(api, gh):
    connect(api)
    r = api.post("/api/v2/github/repos", json={"slug": "botops"}, headers=auth())
    assert r.status_code == 409
    error = r.json()["error"]
    assert error["code"] == "github_permission_missing" and "Create Acme/emp-botops yourself" in error["detail"]
    assert not gh.of("/generate")
    assert api.post("/api/v2/github/repos", json={"slug": "Bad Slug"}, headers=auth()).status_code == 422


def test_repo_of():
    assert G.repo_of("emp-x", "Acme") == "Acme/emp-x"
    assert G.repo_of("https://github.com/Acme/emp-x.git", "") == "Acme/emp-x"
    assert G.repo_of("https://gitlab.com/Acme/emp-x", "Acme") is None
    assert G.repo_of("", "Acme") is None and G.repo_of("a/b/c", "") is None


def put_extras(api, bot, repos, who="owner-test"):
    return api.put(f"/api/v2/bots/{bot}/github-repos", json={"repositories": repos}, headers=auth(who))


def turn_token(api, bot="cpo"):
    return api.post("/api/v2/github/token", json={"bot": bot}, headers=auth("runner-test"))


def events(api, action):
    with api.app_state.store.read() as c:
        return [json.loads(r[0]) for r in c.execute("SELECT detail_json FROM events WHERE action=?", (action,))]


def test_extra_repositories_join_the_turn_token_with_the_same_permissions(api, gh):
    connect(api)
    runner_token(api, "cpo")
    r = put_extras(api, "cpo", ["shared-docs", "Acme/design-system", "https://github.com/Acme/infra.git", "Acme/emp-cpo", "shared-docs"])
    assert r.status_code == 200, r.text
    assert r.json()["repositories"] == ["Acme/shared-docs", "Acme/design-system", "Acme/infra"]
    data = turn_token(api).json()
    assert data["repository"] == "Acme/emp-cpo"
    assert data["repositories"] == ["Acme/emp-cpo", "Acme/shared-docs", "Acme/design-system", "Acme/infra"]
    _, _, body, _ = gh.of("/access_tokens")[-1]
    assert body["repositories"] == ["design-system", "emp-cpo", "infra", "shared-docs"]
    assert body["permissions"] == {"contents": "write", "pull_requests": "write", "issues": "write", "metadata": "read"}
    assert api.get("/api/v2/bots/cpo/github-repos", headers=auth()).json()["repositories"] == data["repositories"][1:]


def test_repositories_not_on_the_list_are_not_in_the_token(api, gh):
    connect(api)
    runner_token(api, "cpo")
    turn_token(api)
    assert gh.of("/access_tokens")[-1][2]["repositories"] == ["emp-cpo"]
    put_extras(api, "cpo", ["shared-docs"])
    turn_token(api)
    assert "secrets" not in gh.of("/access_tokens")[-1][2]["repositories"]
    # Another bot's list is its own, and clearing the list takes the repositories back out.
    runner_token(api, "cmo")
    assert turn_token(api, "cmo").json()["repositories"] == ["Acme/emp-cmo"]
    put_extras(api, "cpo", [])
    assert turn_token(api).json()["repositories"] == ["Acme/emp-cpo"]


def test_extra_repositories_must_be_in_the_connected_organization(api, gh):
    connect(api)
    for bad in (["other-org/secrets"], ["https://github.com/other-org/x"], ["https://example.com/Acme/x"], ["bad name"]):
        assert put_extras(api, "cpo", bad).status_code == 422, bad
    assert put_extras(api, "nobody", ["x"]).status_code == 404
    assert put_extras(api, "cpo", [f"r{i}" for i in range(G.MAX_EXTRA_REPOS + 1)]).status_code == 422
    assert api.get("/api/v2/bots/cpo/github-repos", headers=auth()).json()["repositories"] == []


def test_only_the_owner_manages_extra_repositories(api, gh):
    connect(api)
    runner_token(api, "cpo")
    for who in ("person-test", "runner-test", "bot-test"):
        # A bot without a live attempt is refused earlier still (409).
        assert put_extras(api, "cpo", ["shared-docs"], who).status_code in (403, 409), who
        assert api.get("/api/v2/bots/cpo/github-repos", headers=auth(who)).status_code in (403, 409), who
    assert put_extras(api, "cpo", ["shared-docs"], "nobody").status_code == 401
    assert turn_token(api).json()["repositories"] == ["Acme/emp-cpo"]


def test_changing_extra_repositories_is_audited_and_needs_a_connection(api, gh):
    assert put_extras(api, "cpo", ["shared-docs"]).status_code == 409
    connect(api)
    put_extras(api, "cpo", ["shared-docs"])
    put_extras(api, "cpo", ["shared-docs"])      # unchanged: no second event
    put_extras(api, "cpo", ["infra"])
    assert events(api, "github.bot_repos_changed") == [
        {"before": [], "after": ["Acme/shared-docs"]}, {"before": ["Acme/shared-docs"], "after": ["Acme/infra"]}]
    runner_token(api, "cpo")
    turn_token(api)
    assert events(api, "github.token")[-1]["repositories"] == ["Acme/emp-cpo", "Acme/infra"]


def botops_turn(api):
    """A live turn for the botops bot: the runner, its assignment, and a leased attempt for `botops-test`."""
    runner_token(api, "botops")
    with api.app_state.store.transaction() as c:
        c.execute("INSERT INTO messages(id,from_actor,to_actor,kind,body,created) VALUES('m-botops','human:ana','bot:botops','request','hi',?)",
                  (H.now(),))
        job = c.execute("SELECT id FROM jobs WHERE bot='botops'").fetchone()["id"]
        c.execute("INSERT INTO attempts(id,job_id,bot,runner_id,generation,token_hash,state,lease_until,created) "
                  "VALUES('a2',?,'botops','r1',1,'x','running',?,?)", (job, H.shift(H.now(), hours=1), H.now()))


def test_botops_creates_bot_repo_when_administration_is_on(api, gh):
    botops_turn(api)
    connect(api, administration="true")
    r = api.post("/api/v2/github/repos", json={"slug": "newbie"}, headers=auth("botops-test"))
    assert r.status_code == 200, r.text
    assert r.json()["repository"] == "Acme/emp-newbie"
    assert gh.of("/generate")[0][2]["private"] is True
    with api.app_state.store.read() as c:
        event = c.execute("SELECT actor FROM events WHERE action='github.repo_created'").fetchone()
    assert event["actor"] == "bot:botops"


def test_botops_is_refused_outside_its_lane(api, gh):
    botops_turn(api)
    connect(api, administration="true")
    for slug, why in (("nobody", "not a planned or active bot"), ("oldie", "not a planned or active bot")):
        r = api.post("/api/v2/github/repos", json={"slug": slug}, headers=auth("botops-test"))
        assert r.status_code == 403 and why in r.text, slug
    r = api.post("/api/v2/github/repos", json={"slug": "newbie", "template": "evil/template"}, headers=auth("botops-test"))
    assert r.status_code == 403
    # Any other credential is refused with the reason.
    for who in ("runner-test", "person-test"):
        r = api.post("/api/v2/github/repos", json={"slug": "newbie"}, headers=auth(who))
        assert r.status_code == 403 and "Only the owner" in r.text, who
    assert not gh.of("/generate") and not gh.of("/repos")


def test_botops_is_refused_when_administration_is_off(api, gh):
    botops_turn(api)
    connect(api)
    r = api.post("/api/v2/github/repos", json={"slug": "newbie"}, headers=auth("botops-test"))
    assert r.status_code == 403 and "permission to create repositories" in r.text
    assert not gh.of("/generate")


def test_empty_repo_is_created_without_a_template(api, gh):
    botops_turn(api)
    connect(api, administration="true")
    r = api.post("/api/v2/github/repos", json={"slug": "cmo", "empty": True}, headers=auth("botops-test"))
    assert r.status_code == 200, r.text
    assert r.json()["repository"] == "Acme/emp-cmo" and r.json()["empty"] is True
    method, path, body, _ = gh.of("/repos")[-1]
    assert path == "/orgs/Acme/repos" and body["private"] is True and body["auto_init"] is False and body["name"] == "emp-cmo"
    assert not gh.of("/generate")
    both = api.post("/api/v2/github/repos", json={"slug": "cmo", "empty": True, "template": "a/b"}, headers=auth())
    assert both.status_code == 422
    gh.generate_status = 422
    assert api.post("/api/v2/github/repos", json={"slug": "cfo", "empty": True}, headers=auth()).status_code == 409


def test_empty_repo_without_permission_says_to_do_it_manually(api, gh):
    connect(api)
    r = api.post("/api/v2/github/repos", json={"slug": "cmo", "empty": True}, headers=auth())
    assert r.status_code == 409 and "empty private repository" in r.json()["error"]["detail"]


def test_token_for_a_bare_repo_link_is_scoped_to_the_connected_org(api, gh):
    connect(api)
    api.app_state.store.settings.github_owner = "Elsewhere"      # a default owner must not win over the connection
    runner_token(api, "cpo")                                # its repo link is the bare `emp-cpo`
    r = api.post("/api/v2/github/token", json={"bot": "cpo"}, headers=auth("runner-test"))
    assert r.status_code == 200 and r.json()["repository"] == "Acme/emp-cpo"
    body = gh.of("/access_tokens")[-1][2]
    assert body["repositories"] == ["emp-cpo"] and body["permissions"]["contents"] == "write"


def test_a_repository_that_does_not_exist_yet_says_so_and_how_to_create_it(api, gh):
    connect(api)
    runner_token(api, "cpo")
    gh.missing = {"emp-cpo"}
    r = turn_token(api)
    assert r.status_code == 409 and r.json()["error"]["code"] == "github_repo_missing"
    assert "does not exist yet" in r.json()["error"]["detail"] and "hub github create-bot-repo cpo" in r.json()["error"]["detail"]
    assert "--empty" in r.json()["error"]["detail"] and "installation settings" not in r.json()["error"]["detail"]
    with api.app_state.store.read() as c:
        assert "does not exist yet" in c.execute("SELECT detail_json FROM service_health").fetchone()[0]


def test_a_repository_the_app_may_not_see_keeps_the_access_message(api, gh):
    connect(api)
    runner_token(api, "cpo")
    gh.missing, gh.forbidden = {"emp-cpo"}, True
    r = turn_token(api)
    assert r.status_code == 409 and r.json()["error"]["code"] == "github_repo_not_accessible"
    assert "installation settings" in r.json()["error"]["detail"] and "does not exist yet" not in r.json()["error"]["detail"]
    # With selected repositories a 404 is either: the message gives both answers.
    gh.forbidden, gh.selection = False, "selected"
    detail = turn_token(api).json()["error"]["detail"]
    assert "does not exist yet" in detail and "installation settings" in detail
