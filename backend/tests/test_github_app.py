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
        self.delete_status = 204
        self.refuse = None                       # (status, message) for every token request
        self.permissions = None                  # the installation's live permissions; None leaves them out
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
            info = {"id": 77, "repository_selection": self.selection}
            if self.permissions is not None:
                info["permissions"] = self.permissions
            return httpx.Response(200, json=info)
        if path.startswith("/repos/") and path.count("/") == 3:
            if request.method == "DELETE":
                return httpx.Response(self.delete_status)
            return httpx.Response(404 if path.split("/")[3] in self.missing else 200, json={})
        if path.endswith("/access_tokens"):
            if self.refuse:
                return httpx.Response(self.refuse[0], json={"message": self.refuse[1]})
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


def test_repository_delete_is_owner_only_scoped_audited_and_never_treats_404_as_success(api, gh):
    botops_turn(api)
    connect(api, administration="true")
    path = "/api/v2/github/repos/Acme/bot-qa-delete"
    head = {**auth(), "Idempotency-Key": str(uuid.uuid4())}
    assert api.delete(path, headers={**head, **auth("person-test")}).status_code == 403
    assert api.delete(path, headers={**head, **auth("botops-test")}).status_code == 403
    assert api.delete("/api/v2/github/repos/elsewhere/bot-qa-delete", headers=head).status_code == 422
    assert not any(c[0] == "DELETE" for c in gh.calls)
    response = api.delete(path, headers=head)
    assert response.status_code == 200 and response.json() == {"repository": "Acme/bot-qa-delete", "deleted": True}
    token = gh.of("/access_tokens")[-1][2]
    assert token == {"repositories": ["bot-qa-delete"], "permissions": {"administration": "write", "metadata": "read"}}
    with api.app.state.store.read() as c:
        event = c.execute("SELECT actor,target FROM events WHERE action='github.repo_deleted'").fetchone()
        assert tuple(event) == ("human:ana", "Acme/bot-qa-delete")
    from backend import rooms
    with api.app.state.store.transaction() as c:
        c.execute("INSERT OR REPLACE INTO registry_metadata VALUES('owner',?)", (encode({"email": "ana@acme.example"}),))
        conversation = rooms.personal_room(c, "human:ana", "botops")
        c.execute("UPDATE messages SET conversation_id=?,kind='say',body='Delete the QA repository' WHERE id='m-botops'",
                  (conversation["id"],))
        c.execute("INSERT INTO attempt_conversations VALUES('a2',?)", (conversation["id"],))
    delegated = api.delete("/api/v2/github/repos/Acme/bot-qa-delegated", headers={**auth("botops-test"),
                           "X-Tico-On-Behalf-Of": "turn", "Idempotency-Key": str(uuid.uuid4())})
    assert delegated.status_code == 200 and delegated.json()["deleted"] and "needs_confirm" not in delegated.json(), delegated.text
    with api.app.state.store.read() as c:
        event = c.execute("SELECT actor,detail_json FROM events WHERE action='github.repo_deleted' "
                          "AND target='Acme/bot-qa-delegated'").fetchone()
        assert event["actor"] == "human:ana" and '"via": "botops"' in event["detail_json"]
    gh.delete_status = 404
    response = api.delete(path, headers={**auth(), "Idempotency-Key": str(uuid.uuid4())})
    assert response.status_code == 409 and "did not delete" in response.json()["error"]["detail"]
    gh.permissions = {"administration": "read"}
    response = api.delete(path, headers={**auth(), "Idempotency-Key": str(uuid.uuid4())})
    assert response.status_code == 403 and "Administration" in response.json()["error"]["detail"]


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


def botops_turn(api):
    """A live turn for the botops bot: the runner, its assignment, and a leased attempt for `botops-test`."""
    runner_token(api, "botops")
    with api.app_state.store.transaction() as c:
        c.execute("INSERT INTO messages(id,from_actor,to_actor,kind,body,created) VALUES('m-botops','human:ana','bot:botops','request','hi',?)",
                  (H.now(),))
        job = c.execute("SELECT id FROM jobs WHERE bot='botops'").fetchone()["id"]
        c.execute("INSERT INTO attempts(id,job_id,bot,runner_id,generation,token_hash,state,lease_until,created) "
                  "VALUES('a2',?,'botops','r1',1,'x','running',?,?)", (job, H.shift(H.now(), hours=1), H.now()))


def test_botops_is_refused_outside_its_lane(api, gh):
    botops_turn(api)
    connect(api, administration="true")
    for slug, why in (("nobody", "not a bot being set up or running"), ("oldie", "not a bot being set up or running")):
        r = api.post("/api/v2/github/repos", json={"slug": slug}, headers=auth("botops-test"))
        assert r.status_code == 403 and why in r.text, slug
    r = api.post("/api/v2/github/repos", json={"slug": "newbie", "template": "evil/template"}, headers=auth("botops-test"))
    assert r.status_code == 403
    # Any other credential is refused with the reason.
    for who in ("runner-test", "person-test"):
        r = api.post("/api/v2/github/repos", json={"slug": "newbie"}, headers=auth(who))
        assert r.status_code == 403 and "Only the owner" in r.text, who
    assert not gh.of("/generate") and not gh.of("/repos")



def token_health(api):
    with api.app_state.store.read() as c:
        row = c.execute("SELECT last_error FROM service_health WHERE service='github:token'").fetchone()
        return bool(row and row["last_error"])


def service_issues(api):
    return [i for i in api.get("/api/v2/operations", headers=auth()).json()["issues"] if i["kind"] == "service"]


def test_a_bot_whose_repository_is_not_on_github_is_not_a_token_problem(api, gh):
    connect(api)
    runner_token(api, "cpo")
    gh.missing.add("emp-cpo")
    r = turn_token(api)
    assert r.status_code == 409 and "does not exist yet" in r.text
    assert "can't create repositories (Administration is off)" in r.text       # connected without Administration
    assert not token_health(api) and not service_issues(api)


def test_repository_creation_is_only_suggested_when_the_app_can_do_it(api, gh):
    connect(api, administration="true")
    runner_token(api, "cpo")
    gh.missing.add("emp-cpo")
    assert "hub bot repo-create cpo" in turn_token(api).text


def test_the_app_itself_failing_is_named_with_what_to_do_and_clears_on_recovery(api, gh):
    connect(api)
    runner_token(api, "cpo")
    gh.refuse = (422, "The permissions requested are not granted to this installation.")
    r = turn_token(api)
    assert r.status_code == 409 and "Accept its updated permissions" in r.text
    assert token_health(api)
    issue = [i for i in service_issues(api) if i["title"] == "GitHub needs attention"]
    assert issue and "permissions" in issue[0]["detail"] and issue[0]["action"]
    gh.refuse = (500, "Server Error")
    assert "HTTP 500: Server Error" in turn_token(api).text
    gh.refuse = None
    assert turn_token(api).status_code == 200
    assert not token_health(api) and not service_issues(api)


def test_a_row_written_before_app_only_recording_is_not_shown_and_disconnecting_clears_it(api, gh):
    connect(api)
    with api.app_state.store.transaction() as c:
        c.execute("INSERT INTO service_health VALUES('github:token',NULL,?,?)",
                  (H.now(), json.dumps({"message": "The repository Acme/emp-cpo does not exist yet on GitHub."})))
    assert not service_issues(api)
    with api.app_state.store.transaction() as c:
        c.execute("UPDATE github_app SET installation_id=77")
    checks = {c["id"]: c["status"] for c in api.get("/api/v2/health", headers=auth()).json()["checks"]}
    assert checks["github"] == "ok"
    assert api.post("/api/v2/github/app/disconnect", headers=auth()).status_code == 200
    with api.app_state.store.read() as c:
        assert not c.execute("SELECT 1 FROM service_health WHERE service='github:token'").fetchone()


def stored_administration(api):
    with api.app_state.store.read() as c:
        return c.execute("SELECT administration FROM github_app").fetchone()["administration"]


def test_live_write_permission_lets_create_repo_proceed_and_updates_the_stored_flag(api, gh):
    connect(api)                                        # set up without Administration
    assert stored_administration(api) == 0
    gh.permissions = {"administration": "write", "contents": "write"}   # the owner added it later and accepted it
    assert api.get("/api/v2/github/app", headers=auth()).json()["administration"] is True
    assert stored_administration(api) == 1
    r = api.post("/api/v2/github/repos", json={"slug": "newbie", "empty": True}, headers=auth())
    assert r.status_code == 200, r.text
    assert gh.of("/repos")


def test_live_permissions_without_administration_refuse_even_when_the_stored_flag_says_yes(api, gh):
    connect(api, administration="true")
    gh.permissions = {"contents": "write", "metadata": "read"}
    r = api.post("/api/v2/github/repos", json={"slug": "newbie", "empty": True}, headers=auth())
    assert r.status_code == 409
    assert "turn on Administration for the app in GitHub and accept it for the organisation" in r.text
    assert not gh.of("/repos")
    assert stored_administration(api) == 0
    assert api.get("/api/v2/github/app", headers=auth()).json()["administration"] is False


def test_unreadable_live_permissions_keep_the_stored_flag(api, gh):
    connect(api, administration="true")                 # GitHub's answer has no permissions
    assert api.get("/api/v2/github/app", headers=auth()).json()["administration"] is True
    assert api.post("/api/v2/github/repos", json={"slug": "newbie", "empty": True}, headers=auth()).status_code == 200
