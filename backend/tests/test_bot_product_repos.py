"""A bot with Create product repositories makes a private product repository: the Owner turns the right on, the bot
gets write to what it made, the Owner is told, and connecting GitHub stays the Owner's."""
import json

from backend import hubdb as H
from backend.store import encode
from backend.tests.test_github_app import api, gh, auth, botops_turn, connect, product_repo_request, runner_token  # noqa: F401

PREVIEW = "/api/v2/github/product-repos/preview"
ACCESS = "/api/v2/bots/cmo/repositories"
BODY = {"org": "Acme", "name": "tico-services", "visibility": "private", "auto_init": False, "confirmed": True}
RIGHT = "Create product repositories"


def ready(api, gh, administration="write"):
    """The Owner on the roster, GitHub connected, and bot cmo in a running turn (the `bot-test` credential)."""
    connect(api, administration="true")
    gh.permissions = {"administration": administration, "metadata": "read"}
    runner_token(api, "cmo")
    with api.app_state.store.transaction() as c:
        c.execute("INSERT OR REPLACE INTO registry_metadata VALUES('owner',?)", (encode({"email": "ana@acme.example"}),))
        c.execute("INSERT INTO messages(id,from_actor,to_actor,kind,body,created) "
                  "VALUES('m-cmo','keeper','bot:cmo','request','Make the services repository',?)", (H.now(),))
        job = c.execute("SELECT id FROM jobs WHERE bot='cmo'").fetchone()["id"]
        c.execute("INSERT INTO attempts(id,job_id,bot,runner_id,generation,token_hash,state,lease_until,created) "
                  "VALUES('a1',?,'cmo','r1',1,'x-cmo','running',?,?)", (job, H.shift(H.now(), hours=1), H.now()))


def grant(api, on=True, who="owner-test", mode="own"):
    return api.put(ACCESS, json={"mode": mode, "create_product_repositories": on}, headers=auth(who))


def creates(gh):
    return [call for call in gh.calls if call[:2] == ("POST", "/orgs/Acme/repos")]


def test_bot_with_the_right_creates_a_private_repo_gets_write_and_the_owner_is_told(api, gh):
    ready(api, gh)
    # Before the Owner turns it on, the bot is refused and told which right it needs (the 403 this ticket removes).
    refused = product_repo_request(api, BODY, actor="bot-test", key="bot-services")
    assert refused.status_code == 403 and RIGHT in refused.json()["error"]["detail"]
    assert api.get(PREVIEW, params={"name": "tico-services"}, headers=auth("bot-test")).status_code == 403
    assert not creates(gh)

    assert api.get(ACCESS, headers=auth()).json()["create_product_repositories"] is False
    on = grant(api)
    assert on.status_code == 200 and on.json()["create_product_repositories"] is True, on.text

    preview = api.get(PREVIEW, params={"name": "tico-services"}, headers=auth("bot-test"))
    assert preview.status_code == 200 and preview.json()["capability"] == "available", preview.text
    made = product_repo_request(api, BODY, actor="bot-test", key="bot-services")
    assert made.status_code == 200, made.text
    result = made.json()
    assert result["repository"] == "Acme/tico-services" and result["visibility"] == "private"
    assert result["bot_access"] == "write" and "cmo has write access to it." in result["note"]
    assert [call[2] for call in creates(gh)] == [{"name": "tico-services", "private": True, "auto_init": False,
                                                  "description": "Tico product repository"}]

    view = api.get(ACCESS, headers=auth()).json()
    assert view["mode"] == "chosen"
    assert {"full_name": "Acme/tico-services", "access": "write"} in view["effective"]
    with api.app_state.store.read() as c:
        event = c.execute("SELECT actor,detail_json FROM events WHERE action='github.product_repo_created'").fetchone()
        assert event["actor"] == "bot:cmo"
        assert json.loads(event["detail_json"])["bot_access"] == "write"
        assert json.loads(event["detail_json"])["owner_notified"] is True
        notices = c.execute("SELECT from_actor,body FROM messages WHERE to_actor='human:ana' AND kind='notice'").fetchall()
        assert [n["body"] for n in notices] == [
            "cmo created private repo tico-services (Acme/tico-services). cmo has write access to it."]

    # The same key replays the receipt: no second create, grant or notice.
    replay = product_repo_request(api, BODY, actor="bot-test", key="bot-services")
    assert replay.status_code == 200 and replay.json() == result
    assert len(creates(gh)) == 1
    with api.app_state.store.read() as c:
        assert c.execute("SELECT COUNT(*) FROM messages WHERE to_actor='human:ana' AND kind='notice'").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM events WHERE action='github.product_repo_created'").fetchone()[0] == 1


def test_a_chosen_bot_keeps_its_grants_and_bots_on_every_ticked_repo_are_named(api, gh):
    ready(api, gh)
    with api.app_state.store.transaction() as c:
        c.execute("INSERT INTO repositories(id,full_name,enabled,updated) VALUES('r-tico','Acme/tico',1,?)", (H.now(),))
        config = json.loads(c.execute("SELECT config_json FROM bot_config WHERE bot='cpo'").fetchone()[0])
        c.execute("UPDATE bot_config SET config_json=? WHERE bot='cpo'",
                  (json.dumps({**config, "repo_access_mode": "all"}),))
    assert api.put(ACCESS, json={"mode": "chosen", "chosen": [{"full_name": "Acme/tico", "access": "read"}],
                                 "create_product_repositories": True}, headers=auth()).status_code == 200
    made = product_repo_request(api, BODY, actor="bot-test", key="chosen-bot")
    assert made.status_code == 200, made.text
    chosen = {r["full_name"]: r["access"] for r in api.get(ACCESS, headers=auth()).json()["chosen"]}
    assert chosen == {"Acme/tico": "read", "Acme/tico-services": "write"}
    assert "Bots set to every ticked repository reach it too: cpo." in made.json()["note"]


def test_a_bot_without_the_right_is_refused_and_told_which_right(api, gh):
    ready(api, gh)
    botops_turn(api)
    # BotOps creates bot repositories built in, but not product repositories.
    assert api.get("/api/v2/bots/botops/repositories", headers=auth()).json()["create_product_repositories"] is False
    for actor in ("bot-test", "botops-test", "person-test", "runner-test"):
        refused = product_repo_request(api, BODY, actor=actor, key="no-right-" + actor)
        assert refused.status_code == 403, (actor, refused.text)
        assert RIGHT in refused.json()["error"]["detail"]
    assert not creates(gh)


def test_only_the_owner_turns_the_right_on_and_an_admin_may_turn_it_off(api, gh):
    ready(api, gh)
    with api.app_state.store.transaction() as c:
        c.execute("INSERT OR REPLACE INTO registry_metadata VALUES('access',?)", (encode({"admins": ["riley@acme.example"]}),))
    botops_turn(api)
    for actor in ("person-test", "bot-test", "botops-test", "runner-test"):
        refused = grant(api, who=actor)
        assert refused.status_code == 403, (actor, refused.text)
    assert api.get(ACCESS, headers=auth()).json()["create_product_repositories"] is False
    # An admin's save that leaves the right as it is still works.
    assert grant(api, on=False, who="person-test").status_code == 200
    assert grant(api).json()["create_product_repositories"] is True
    off = grant(api, on=False, who="person-test")
    assert off.status_code == 200 and off.json()["create_product_repositories"] is False
    assert off.json()["product_creation_stopped"] is True
    refused = product_repo_request(api, BODY, actor="bot-test", key="after-revoke")
    assert refused.status_code == 403 and RIGHT in refused.text
    assert not creates(gh)


def test_connecting_and_disconnecting_github_stay_the_owners(api, gh):
    ready(api, gh)
    assert grant(api).status_code == 200
    for method, path in (("GET", "/api/v2/github/app"), ("GET", "/api/v2/github/app/manifest?org=Acme"),
                         ("POST", "/api/v2/github/app/disconnect"), ("DELETE", "/api/v2/github/repos/Acme/tico-services")):
        refused = api.request(method, path, headers=auth("bot-test"))
        assert refused.status_code == 403, (method, path, refused.text)
    assert api.get("/api/v2/github/app", headers=auth()).json()["connected"] is True


def test_a_bot_never_creates_a_bot_repository_name(api, gh):
    ready(api, gh)
    assert grant(api).status_code == 200
    # bot-/emp- names, and a name a bot's repository already uses (cpo's emp-cpo, cmo's own emp-cmo).
    for name in ("bot-newhire", "emp-newhire", "BOT-x", "emp-cpo", "emp-cmo"):
        refused = product_repo_request(api, {**BODY, "name": name}, actor="bot-test", key="name-" + name)
        assert refused.status_code == 403 and "bot repository name" in refused.text, (name, refused.text)
        assert api.get(PREVIEW, params={"name": name}, headers=auth("bot-test")).status_code == 403
    assert not creates(gh)
    # The Owner's name rules are unchanged.
    assert api.get(PREVIEW, params={"name": "bot-newhire"}, headers=auth()).status_code == 200


def test_without_administration_the_refusal_says_so_and_what_the_owner_changes(api, gh):
    ready(api, gh, administration="read")
    assert grant(api).status_code == 200
    preview = api.get(PREVIEW, params={"name": "tico-services"}, headers=auth("bot-test")).json()
    assert preview["capability"] == "missing"
    fix = "https://github.com/organizations/Acme/settings/apps/acme-tico/permissions"
    assert "missing Administration: write" in preview["capability_detail"] and fix in preview["capability_detail"]
    refused = product_repo_request(api, BODY, actor="bot-test", key="no-admin")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "github_permission_missing"
    assert "set Administration to Read and write on " + fix in refused.json()["error"]["detail"]
    assert not creates(gh)
