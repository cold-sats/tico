"""BotOps does what the person asking could do (docs/permissions.md): any v2 route as them, placement that never leaves an
active bot silent, and the tool-level parts of the evals (evals/botops/) without a model.

Ana owns the company, Ben is an admin, Cara is a member (the base fixture). BotOps acts as whoever's chat message started
its turn: a member is refused what only an owner may do, an owner is not.
"""
import json

import pytest

from backend.tests.test_api import api, assign, claim, get, headers, post, put, ready, runner  # noqa: F401  (fixture)
from backend.tests.test_member_bots import botops, call, close_computer, finish, register, turn  # noqa: F401  (fixtures)


def act(api, attempt, method, path, body=None, ref="turn"):
    """One `hub api` call: the request BotOps makes, asking to be answered as the person it works for."""
    kwargs = {"headers": {**headers(attempt["token"]), "X-Tico-On-Behalf-Of": ref}}
    if body is not None:
        kwargs["json"] = body
    return getattr(api, method.lower())("/api/v2/" + path, **kwargs)


def open_computer(api, label="Team Mac"):
    """A computer an admin has opened to members' bots."""
    machine = runner(api, label=label)
    ready(api, machine, [])
    post(api, f"runners/{machine['runner_id']}/member-bots", {"accepts": True}, "ben-test")
    return machine


# ------------------------------------------------------------------ any route, as the requester
def test_an_owner_requester_may_and_a_member_requester_may_not(api, botops):
    ana = turn(api, botops, person="ana-test", text="Use a bigger model on ops")
    changed = act(api, ana, "POST", "bots/ops/model", {"model": "gpt-6-astra", "expected_revision": 1})
    assert changed.status_code == 200, changed.text
    with api.app.state.store.read() as c:
        row = c.execute("SELECT actor,detail_json FROM events WHERE action='bot.model_changed' AND target='ops'").fetchone()
        assert row["actor"] == "human:ana" and '"via": "botops"' in row["detail_json"]       # hers, via BotOps
    finish(api, botops, ana)
    cara = turn(api, botops, person="cara-test", text="Use a bigger model on ops")
    # Not her bot: the server's own rule refuses, exactly as in the app.
    assert act(api, cara, "POST", "bots/ops/model", {"model": "gpt-6-astra", "expected_revision": 2}).status_code == 403
    # What only an owner or an admin may ask for is refused at once, not handed over as a card that fails.
    assert act(api, cara, "PUT", "access/limits", {"member_bot_limit": 9}).status_code == 403
    assert act(api, cara, "PUT", "providers", {"enabled": ["openai"]}).status_code == 403
    # Her own bot, she may.
    register(api, cara, "jira-manager")
    revision = act(api, cara, "GET", "bots/jira-manager/access").json()["revision"]
    assert act(api, cara, "POST", "bots/jira-manager/model", {"model": "gpt-6-astra", "expected_revision": revision}).status_code == 200


def test_what_always_needs_a_click_comes_back_as_one_card_and_runs_only_on_it(api, botops):
    ben = turn(api, botops, person="ben-test", text="Let members have 3 bots")
    first = act(api, ben, "PUT", "access/limits", {"member_bot_limit": 3})
    assert first.status_code == 200 and first.json()["needs_confirm"] is True, first.text
    card = first.json()["action"]
    again = act(api, ben, "PUT", "access/limits", {"member_bot_limit": 3}).json()
    assert again["action"]["id"] == card["id"]                                          # a retry is the same card
    from backend import access as Access
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM assistant_actions WHERE status='pending'").fetchone()[0] == 1
        assert Access.load_access(c, api.app.state.store.settings)["member_bot_limit"] != 3
    assert call(api, "post", f"assistant/actions/{card['id']}/confirm", "cara-test").status_code == 404     # not hers to click
    assert call(api, "post", f"assistant/actions/{card['id']}/confirm", ben["token"]).status_code == 403    # nor BotOps'
    assert call(api, "post", f"assistant/actions/{card['id']}/confirm", "ben-test").status_code == 200
    with api.app.state.store.read() as c:
        assert Access.load_access(c, api.app.state.store.settings)["member_bot_limit"] == 3


def test_a_secret_or_an_unlisted_route_never_goes_through_it(api, botops):
    attempt = turn(api, botops, person="ana-test")
    revision = act(api, attempt, "GET", "bots/ops/access").json()["revision"]
    leaked = act(api, attempt, "POST", "bots/ops/definition", {"description": "x", "expected_revision": revision,
                                                              "config": {"api_key": "sk-live-not-for-you"}})
    assert leaked.status_code == 422 and leaked.json()["error"]["code"] == "secret_in_request"
    assert "sk-live" not in leaked.text
    for method, path in (("POST", "credentials"), ("POST", "credentials/x/reveal"), ("POST", "enrollments"), ("POST", "me/tokens"),
                         ("POST", "approvals/x"), ("POST", "access/owner"), ("POST", "bots/ops/agent-credential"), ("GET", "credential-runtime")):
        assert act(api, attempt, method, path, {} if method == "POST" else None).status_code == 403, path
    # Only BotOps, and only in a turn a person's own chat message started.
    other = runner(api, label="Other Mac")
    assign(api, other, "ops")
    ready(api, other, ["ops"])
    post(api, "chat/ops", {"text": "Hello"})
    assert act(api, claim(api, other, "ops"), "GET", "bots/ops/access").status_code == 403
    finish(api, botops, attempt)
    post(api, "tasks", {"owner": "botops", "title": "Review the bot list", "body": "Please look."}, "cara-test")
    assert act(api, claim(api, botops, "botops"), "GET", "bots").status_code == 403


# ------------------------------------------------------------------ a computer for every active bot
def test_an_active_bot_goes_on_the_only_computer_or_the_least_busy_one(api):
    only = runner(api, label="Only Mac")
    ready(api, only, [])
    made = post(api, "bots", {"slug": "scribe", "display_name": "Scribe", "description": "Writes", "status": "active",
                              "model": "gpt-6-astra", "effort": "high", "harness": None, "runner_id": None})
    assert made["assignment"]["runner_id"] == only["runner_id"]
    second = runner(api, label="Second Mac")
    ready(api, second, [])
    post(api, "bots", {"slug": "writer", "display_name": "Writer", "description": "Writes", "status": "active",
                       "model": "gpt-6-astra", "effort": "high", "harness": None, "runner_id": None})
    with api.app.state.store.read() as c:
        where = dict(c.execute("SELECT bot,runner_id FROM assignments").fetchall())
    assert where["writer"] == second["runner_id"]                  # the one with nothing on it


def test_a_bot_botops_builds_goes_where_botops_and_its_repository_are(api, botops):
    other = runner(api, label="Idle Mac")
    ready(api, other, [])
    ready(api, botops, ["botops"])
    made = post(api, "bots", {"slug": "scribe", "display_name": "Scribe", "description": "Writes", "status": "active",
                              "model": "gpt-6-astra", "effort": "high", "harness": None, "runner_id": None})
    assert made["assignment"]["runner_id"] == botops["runner_id"]            # not the emptier computer


def test_activating_or_resuming_places_a_bot_and_the_scheduler_places_the_rest(api):
    made = post(api, "bots", {"slug": "scribe", "display_name": "Scribe", "description": "Writes", "status": "planned",
                              "model": "gpt-6-astra", "effort": "high", "harness": None, "runner_id": None})
    assert made["status"] == "planned" and made["assignment"] is None
    machine = runner(api)
    ready(api, machine, [])
    post(api, "bots/scribe/definition", {"status": "active", "expected_revision": made["revision"]})
    with api.app.state.store.read() as c:
        assert c.execute("SELECT runner_id FROM assignments WHERE bot='scribe'").fetchone()[0] == machine["runner_id"]
    # Active with nowhere to go says so, and is placed by the scheduler when a computer can take it.
    with api.app.state.store.transaction() as c:
        c.execute("DELETE FROM assignments WHERE bot='scribe'")
    from backend import placement
    with api.app.state.store.transaction() as c:
        assert [slug for slug, _ in placement.sweep(c, api.app.state.execution) if slug == "scribe"] == ["scribe"]


def test_a_members_bot_waits_for_a_computer_that_takes_it_and_then_goes_there(api):
    closed = close_computer(api, runner(api, label="Closed Mac"))
    ready(api, closed, [])
    made = post(api, "bots", {"slug": "mine", "display_name": "Mine", "description": "x", "status": "active", "model": "gpt-6-astra",
                              "effort": "high", "harness": None, "runner_id": None}, "cara-test")
    assert made["assignment"] is None and "No computer takes Mine" in made["note"]
    open_ = open_computer(api)
    from backend import placement
    with api.app.state.store.transaction() as c:
        placed = placement.sweep(c, api.app.state.execution)
    assert dict(placed)["mine"]["runner_id"] == open_["runner_id"]               # never the closed one


def test_an_external_agent_has_no_computer_to_place(api):
    machine = runner(api)
    ready(api, machine, [])
    made = post(api, "bots", {"slug": "hermes-one", "display_name": "Hermes", "description": "x", "status": "active",
                              "model": "hermes-profile", "effort": "as-configured", "harness": "hermes", "runner_id": None})
    assert made["assignment"] is None and "note" not in made


def test_go_live_places_activates_and_starts_setup_as_the_requester(api, botops):
    open_computer(api)
    cara = turn(api, botops, person="cara-test", text="Make it live")
    register(api, cara, "jira-manager")
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bot_config SET onboarding_state='needs_setup' WHERE bot='jira-manager'")
    gone = act(api, cara, "POST", "bots/jira-manager/go-live", {})
    assert gone.status_code == 200, gone.text
    done = gone.json()
    assert (done["state"], done["placed"], done["activated"], done["setup_started"]) == ("active", True, True, True)
    with api.app.state.store.read() as c:
        said = c.execute("SELECT from_actor,body FROM messages WHERE to_actor='bot:jira-manager'").fetchone()
        assert (said["from_actor"], said["body"]) == ("human:cara", "Let's set you up.")
    assert act(api, cara, "POST", "bots/jira-manager/place", {}).json()["already"] is True


def test_the_fleet_check_names_what_is_wrong_most_urgent_first(api, botops):
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bots SET state='paused' WHERE slug='cpo'")
    ana = turn(api, botops, person="ana-test", text="Tell me issues to solve")
    result = act(api, ana, "GET", "fleet/check").json()
    kinds = {(i["bot"], i["kind"]) for i in result["issues"]}
    assert ("ops", "not_placed") in kinds and ("cpo", "paused") in kinds
    assert result["issues"][0]["severity"] == "high" and result["issues"][0]["fix"].startswith("hub ")


# ------------------------------------------------------------------ a credential card in the chat
KEY = "ana@acme.example:atl-SECRET-token-0123456789"


def vault(api):
    from backend.tests.test_credentials import setup
    setup(api)


def everything(api):
    """Every table's text, to look for a value that must not be anywhere."""
    with api.app.state.store.read() as c:
        names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '%fts%'")]
        return "".join(str([tuple(r) for r in c.execute(f"SELECT * FROM {n}")]) for n in names
                       if n not in ("credentials", "credential_keys"))


def test_a_credential_card_stores_and_grants_without_the_value_touching_anything_else(api, botops):
    vault(api)
    ana = turn(api, botops, person="ana-test", text="Make Jira work for ops")
    opened = call(api, "post", "credential-requests", ana["token"], {
        "env": "JIRA_BASIC_AUTH", "for_bot": "ops", "label": "your Jira login", "format": "you@company.com:API token",
        "help_url": "https://id.atlassian.com/manage-profile/security/api-tokens", "on_behalf_of": "turn"})
    assert opened.status_code == 200, opened.text
    card = opened.json()
    assert card["title"] == "ops needs your Jira login"
    with api.app.state.store.read() as c:
        message = c.execute("SELECT from_actor,to_actor,refs_json FROM messages WHERE id=?", (card["message_id"],)).fetchone()
        assert (message["from_actor"], message["to_actor"]) == ("bot:botops", "human:ana") and card["id"] in message["refs_json"]
    seen = get(api, f"credential-requests/{card['id']}")
    assert seen["can_save"] and seen["format"] == "you@company.com:API token" and seen["help_url"].startswith("https://")
    get(api, f"credential-requests/{card['id']}", "cara-test", expected=404)                # nobody else's
    # A value of the wrong shape is refused and never repeated.
    wrong = post(api, f"credential-requests/{card['id']}/save", {"value": "no-colon-here-12345"}, expected=422)
    assert wrong["error"]["code"] == "format" and "no-colon-here" not in json.dumps(wrong)
    post(api, f"credential-requests/{card['id']}/save", {"value": KEY}, "cara-test", expected=404)
    saved = post(api, f"credential-requests/{card['id']}/save", {"value": KEY})
    assert saved["status"] == "saved"
    with api.app.state.store.read() as c:
        cred = c.execute("SELECT id,name,env,kind FROM credentials WHERE env='JIRA_BASIC_AUTH'").fetchone()
        assert cred["name"] == "JIRA_BASIC_AUTH"
        grants = c.execute("SELECT subject FROM credential_grants WHERE credential_id=? AND revoked IS NULL", (cred["id"],)).fetchall()
        assert [g["subject"] for g in grants] == ["bot:ops"]                                # that bot alone
        wake = c.execute("SELECT from_actor,to_actor,body,refs_json FROM messages WHERE refs_json LIKE '%credential_saved%'").fetchone()
        assert (wake["from_actor"], wake["to_actor"]) == ("human:ana", "bot:botops") and "Saved your Jira login" in wake["body"]
    assert KEY not in everything(api) and "atl-SECRET" not in everything(api)
    post(api, f"credential-requests/{card['id']}/save", {"value": KEY}, expected=409)          # once
    # BotOps is woken by that message, and keeps acting as her: the test of the connection is hers to run.
    finish(api, botops, ana)
    woken = claim(api, botops, "botops")
    assert act(api, woken, "GET", "bots/ops/access").status_code == 200
    # Replacing it uses the same card, and the same credential.
    again = call(api, "post", "credential-requests", woken["token"], {"env": "JIRA_BASIC_AUTH", "for_bot": "ops", "on_behalf_of": "turn"}).json()
    post(api, f"credential-requests/{again['id']}/save", {"value": "ana@acme.example:atl-NEW-token-0123456789"})
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM credentials WHERE env='JIRA_BASIC_AUTH'").fetchone()[0] == 1
        assert c.execute("SELECT revision FROM credentials WHERE env='JIRA_BASIC_AUTH'").fetchone()[0] == 2


def test_only_a_credential_admin_can_fill_a_card_and_a_member_is_told_who(api, botops):
    vault(api)
    cara = turn(api, botops, person="cara-test", text="Connect my bot")
    register(api, cara, "jira-manager")
    card = call(api, "post", "credential-requests", cara["token"], {"env": "JIRA_TOKEN", "for_bot": "jira-manager", "on_behalf_of": "turn"}).json()
    seen = get(api, f"credential-requests/{card['id']}", "cara-test")
    assert seen["can_save"] is False and "credential admin" in seen["note"]
    post(api, f"credential-requests/{card['id']}/save", {"value": "some-token-value-123"}, "cara-test", expected=403)
    assert get(api, f"credential-requests/{card['id']}", "ana-test")["can_save"] is True       # an admin may, for her


def test_a_token_pasted_in_chat_is_stored_for_the_bot_and_taken_out_of_the_conversation(api, botops):
    vault(api)
    secret = "ghp_PastedInChat0123456789abcdef"
    post(api, "chat/botops", {"text": f"Here is the GitHub token for ops: {secret}"}, "ana-test")
    attempt = claim(api, botops, "botops")
    # The run recorded it in its own transcript before it could act.
    post(api, f"attempts/{attempt['id']}/started", {"thread_id": "t"}, botops["token"])
    post(api, f"attempts/{attempt['id']}/events", {"events": [{"seq": 1, "kind": "message", "payload": {"text": f"token is {secret}"}}]},
         botops["token"])
    done = call(api, "post", "credential-set", attempt["token"], {"env": "GITHUB_TOKEN", "for_bot": "ops", "value": secret,
                                                                  "on_behalf_of": "turn"})
    assert done.status_code == 200, done.text
    assert done.json()["granted"] is True and done.json()["redacted"] == 1 and secret not in done.text
    # A later event of the same run is scrubbed as it arrives.
    post(api, f"attempts/{attempt['id']}/events", {"events": [{"seq": 2, "kind": "message", "payload": {"text": f"stored {secret}"}}]},
         botops["token"])
    assert secret not in everything(api)
    with api.app.state.store.read() as c:
        body = c.execute("SELECT body FROM messages WHERE from_actor='human:ana' AND to_actor='bot:botops'").fetchone()[0]
        assert "•••• saved as GITHUB_TOKEN" in body
        assert c.execute("SELECT count(*) FROM credential_grants WHERE subject='bot:ops' AND revoked IS NULL").fetchone()[0] == 1
    # A member may not store a credential, pasted or not, and the words stay as they were.
    post(api, f"attempts/{attempt['id']}/complete", {"outcome": "completed", "last_seq": 2}, botops["token"])
    post(api, "chat/botops", {"text": f"token for my bot: {secret}"}, "cara-test")
    cara = claim(api, botops, "botops")
    refused = call(api, "post", "credential-set", cara["token"], {"env": "GITHUB_TOKEN", "for_bot": "ops", "value": secret, "on_behalf_of": "turn"})
    assert refused.status_code == 403 and secret not in refused.text


def test_a_secret_is_never_a_command_line_argument():
    from clients import hubcli
    parser = hubcli.parser()
    parsed = parser.parse_args(["credential", "set", "JIRA_BASIC_AUTH", "--for-bot", "jira-manager"])
    assert not hasattr(parsed, "value")
    with pytest.raises(SystemExit):
        parser.parse_args(["credential", "set", "JIRA_BASIC_AUTH", "--for-bot", "jira-manager", "--value", "x"])
