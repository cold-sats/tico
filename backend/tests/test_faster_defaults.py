"""The faster defaults for permissions: what BotOps does without a Confirm card, and the rights the owner may tighten
back (docs/permissions.md). Ana owns the company, Ben is an admin, Cara is a member (the base fixture)."""

import pytest

from backend import botops_act as B
from backend.tests.test_api import api, get, headers, post, put, ready, runner  # noqa: F401  (fixture)
from backend.tests.test_botops_parity import act
from backend.tests.test_member_bots import botops, call, finish, register, turn  # noqa: F401  (fixtures)


def test_which_routes_run_without_a_card_and_which_still_need_one():
    to_bot = lambda name: str(name).startswith("bot:")
    direct = [("POST", "runners/r1/restart", None), ("POST", "credentials/c1/grants/g1/revoke", None),
              ("PUT", "usage/limits/ops", None), ("PUT", "usage/limits", None), ("PUT", "providers", None),
              ("POST", "chat/ops", None), ("POST", "messages", {"to": "bot:ops"}), ("POST", "runners/r1/logins", None),
              ("GET", "runners/r1/logins/l1", None), ("POST", "runners/r1/inbox-sharing", None),
              ("PUT", "bots/ops/github-repos", None), ("POST", "bots/ops/archive", None),
              ("POST", "system/update", None), ("PUT", "access/rules", None)]
    cards = [("POST", "runners/r1/revoke", None), ("POST", "runners/r1/member-bots", None), ("PUT", "access/allow", None),
             ("PUT", "access/limits", None),
             ("POST", "messages", {"to": "human:ben"}), ("POST", "messages", {"to": "nobody"}), ("POST", "messages", None)]
    for method, path, body in direct:
        assert B.classify(method, path, body, None, to_bot) == "do", (method, path)
    for method, path, body in cards:
        assert B.classify(method, path, body, None, to_bot) == "confirm", (method, path)
    # The pasted sign-in code and personal tokens are never BotOps's.
    assert B.classify("POST", "runners/r1/logins/l1/code", {}, None, to_bot) is None
    assert B.classify("POST", "me/tokens", {}, None, to_bot) is None
    # The owner's rule turns providers and limits back into cards, and nothing else.
    tight = {"botops_direct": False}
    for method, path in (("PUT", "providers"), ("PUT", "usage/limits"), ("PUT", "usage/limits/ops")):
        assert B.classify(method, path, {}, tight, to_bot) == "confirm", path
    for method, path in (("POST", "runners/r1/restart"), ("POST", "chat/ops"), ("POST", "credentials/c1/grants/g1/revoke")):
        assert B.classify(method, path, {}, tight, to_bot) == "do", path


def test_botops_restarts_a_computer_and_starts_a_model_sign_in_without_a_card(api, botops):
    ready(api, botops, ["botops"])
    ana = turn(api, botops, person="ana-test", text="Restart the Mac and sign Claude in")
    restarted = act(api, ana, "POST", f"runners/{botops['runner_id']}/restart", {})
    assert restarted.status_code == 200 and restarted.json()["requested"] is True, restarted.text
    started = act(api, ana, "POST", f"runners/{botops['runner_id']}/logins", {"runtime": "claude"})
    assert started.status_code == 200 and started.json()["state"] == "requested", started.text
    read = act(api, ana, "GET", f"runners/{botops['runner_id']}/logins/{started.json()['id']}")
    assert read.status_code == 200
    # The code the person pastes stays theirs to give in the app.
    assert act(api, ana, "POST", f"runners/{botops['runner_id']}/logins/{started.json()['id']}/code", {"code": "abcdef"}).status_code == 403
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM assistant_actions").fetchone()[0] == 0
        row = c.execute("SELECT actor,detail_json FROM events WHERE action='runner.restart'").fetchone()
        assert row["actor"] == "human:ana" and '"via": "botops"' in row["detail_json"]


def test_a_spending_limit_and_the_providers_change_at_once_and_the_owner_can_ask_for_cards(api, botops):
    ana = turn(api, botops, person="ana-test", text="Cap ops at $5 a day, then $10, and use OpenAI")
    assert act(api, ana, "PUT", "usage/limits/ops", {"daily_usd": 5}).status_code == 200
    assert act(api, ana, "PUT", "usage/limits/ops", {"daily_usd": 10}).status_code == 200            # raised: no card either
    assert act(api, ana, "PUT", "providers", {"enabled": ["openai"], "runtime": "codex", "model": "gpt-6-luna"}).status_code == 200
    assert act(api, ana, "PUT", "usage/limits", {"daily_usd": 50}).status_code == 200                 # the company default
    assert put(api, "access/rules", {"botops_direct": False}, "ana-test")["botops_direct"] is False
    raised = act(api, ana, "PUT", "usage/limits/ops", {"daily_usd": 20})
    assert raised.status_code == 200 and raised.json()["needs_confirm"] is True
    assert act(api, ana, "PUT", "providers", {"enabled": ["openai"], "expected_revision": 1}).json()["needs_confirm"] is True
    lowered = act(api, ana, "PUT", "usage/limits/ops", {"daily_usd": 3})                            # lowering is never a card
    assert lowered.status_code == 200 and "needs_confirm" not in lowered.json()
    assert act(api, ana, "PUT", "usage/limits", {"daily_usd": 80}).json()["needs_confirm"] is True
    assert "needs_confirm" not in act(api, ana, "PUT", "usage/limits", {"daily_usd": 40}).json()
    with api.app.state.store.read() as c:
        assert c.execute("SELECT daily_usd FROM usage_limits WHERE bot='ops'").fetchone()[0] == 3


def test_a_message_to_a_bot_goes_at_once_and_a_message_to_a_person_is_a_card(api, botops):
    ana = turn(api, botops, person="ana-test", text="Tell ops to start, and tell Ben hello")
    sent = act(api, ana, "POST", "messages", {"to": "bot:ops", "text": "Please start the launch plan."})
    assert sent.status_code == 200 and "needs_confirm" not in sent.json(), sent.text
    assert act(api, ana, "POST", "chat/ops", {"text": "And keep me posted."}).status_code == 200
    card = act(api, ana, "POST", "messages", {"to": "human:ben", "text": "Hello"})
    assert card.status_code == 200 and card.json()["needs_confirm"] is True
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM messages WHERE to_actor='human:ben' AND from_actor='human:ana'").fetchone()[0] == 0


def test_inbox_sharing_is_turned_on_by_botops_only_where_one_owner_runs_everything(api, botops):
    from backend import inbox_isolation
    ana = turn(api, botops, person="ana-test", text="Let the inbox bots share this computer")
    path = f"runners/{botops['runner_id']}/inbox-sharing"
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bot_config SET operator='ana'")                    # one person runs every bot and computer
        assert inbox_isolation.single_owner(c)
    on = act(api, ana, "POST", path, {"allowed": True})
    assert on.status_code == 200 and on.json() == {"allowed": True}, on.text
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bot_config SET operator='cara' WHERE bot='ops'")   # now someone else runs a bot
        assert not inbox_isolation.single_owner(c)
    refused = act(api, ana, "POST", path, {"allowed": True})
    assert refused.status_code == 403 and "one owner" in refused.json()["error"]["detail"]
    assert act(api, ana, "POST", path, {"allowed": False}).status_code == 200      # turning it off is always fine
    # An admin by hand is as before.
    assert call(api, "post", path, "ben-test", {"allowed": True}).status_code == 200


def test_a_member_makes_a_personal_token_until_the_owner_says_otherwise(api):
    assert post(api, "me/tokens", {"label": "laptop"}, "cara-test")["token"].startswith("tico_pt_")
    assert put(api, "access/rules", {"member_tokens": False}, "ana-test")["member_tokens"] is False
    assert call(api, "post", "me/tokens", "cara-test", {"label": "again"}).status_code == 403
    assert post(api, "me/tokens", {"label": "admin's"}, "ben-test")["token"]          # admins and the owner still do


def test_an_admin_sees_the_sql_page_until_the_owner_says_otherwise(api):
    def sees(token):
        return api.get("/api/me", headers=headers(token)).json()["can_see_sql"]
    assert [sees(t) for t in ("ana-test", "ben-test", "cara-test")] == [True, True, False]
    put(api, "access/rules", {"admin_sql": False}, "ana-test")
    assert [sees(t) for t in ("ana-test", "ben-test")] == [True, False]
    assert call(api, "get", "access", "ben-test").json()["rules"]["admin_sql"] is False


def test_a_bot_manager_who_is_not_the_owner_sets_its_extra_repositories(api, botops):
    # The route answers 409 (GitHub not connected) once the person may manage the bot, and 403 when they may not.
    assert call(api, "put", "bots/ops/github-repos", "cara-test", {"repositories": ["x"]}).status_code == 403
    assert call(api, "put", "bots/ops/github-repos", "ben-test", {"repositories": ["x"]}).status_code == 409
    register(api, turn(api, botops), "jira-manager")
    assert call(api, "put", "bots/jira-manager/github-repos", "cara-test", {"repositories": ["x"]}).status_code == 409
