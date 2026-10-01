"""Pairing a Hermes profile with its bot, restoring an archived bot, and what an archived Hermes bot's agent leaves behind."""

import uuid

from backend.store import H
from backend.tests.test_agents import beat, credential, hermes_bot, issues
from backend.tests.test_api import api, assign, claim, get, headers, post, ready, runner  # noqa: F401
from backend.tests.test_mcp import call, rpc
from backend.tests.test_member_bots import botops, finish, turn  # noqa: F401
from backend.tests.test_botops_parity import act
from clients import hubtools


def pair(api, profile="scout", ip=None, harness="hermes"):
    extra = {"cf-connecting-ip": ip} if ip else {}
    r = api.post("/api/v2/agents/pairings", json={"profile": profile, "harness": harness, "host": "mac-mini", "version": "1.0"},
                 headers=extra)
    return r


def poll(api, pairing, secret=None):
    return api.get("/api/v2/agents/pairings/" + pairing["pairing_id"],
                   headers={"X-Pairing-Secret": secret if secret is not None else pairing["secret"]})


def approve(api, code, bot="scout", token="ana-test"):
    return api.post("/api/v2/agents/pairings/approve", json={"code": code, "bot": bot}, headers=headers(token))


def test_the_pairing_lifecycle_hands_the_credential_over_once(api):
    hermes_bot(api, status="planned")
    made = pair(api)
    assert made.status_code == 201, made.text
    pairing = made.json()
    code = pairing["code"]
    assert len(code) == 9 and code[4] == "-" and not set(code.replace("-", "")) & set("0O1IL")
    assert pairing["expires_in"] == 600 and pairing["poll_every"] == 3 and len(pairing["secret"]) >= 32
    assert poll(api, pairing).json() == {"state": "pending"}
    # Only someone holding the secret may ask; a wrong one is the same 404 as an unknown pairing.
    assert poll(api, pairing, "wrong").status_code == 404
    assert api.get("/api/v2/agents/pairings/nope", headers={"X-Pairing-Secret": pairing["secret"]}).status_code == 404
    # Approval needs a person's sign-in, and a code nobody asked for is a plain 404.
    assert api.post("/api/v2/agents/pairings/approve", json={"code": code, "bot": "scout"}).status_code == 401
    assert approve(api, "ZZZZ-ZZZZ").status_code == 404
    done = approve(api, code.lower().replace("-", " "))
    assert done.status_code == 200, done.text
    assert done.json() == {"bot": "scout", "profile": "scout", "host": "mac-mini"}
    # A code is single use.
    assert approve(api, code).status_code == 404
    with api.app.state.store.read() as c:
        row = c.execute("SELECT * FROM agent_pairings WHERE id=?", (pairing["pairing_id"],)).fetchone()
        assert pairing["secret"] not in tuple(row) and code.replace("-", "") not in tuple(row)
    first = poll(api, pairing).json()
    assert first["state"] == "approved" and first["bot"] == "scout" and first["token"].startswith("tico-agent-")
    assert first["url"] == api.app.state.store.settings.runner_url
    assert get(api, "me", token=first["token"])["actor"] == "bot:scout"
    assert poll(api, pairing).json()["token"] == first["token"]  # installation can retry before a heartbeat
    assert beat(api, first["token"])["bot"] == "scout"
    assert next(bot for bot in get(api, "bots") if bot["slug"] == "scout")["state"] == "active"
    # The token is returned exactly once, and is gone from the row.
    assert poll(api, pairing).json() == {"state": "claimed"}
    with api.app.state.store.read() as c:
        assert c.execute("SELECT token FROM agent_pairings").fetchone()[0] is None
    # Pairing again replaces the standing credential, as Create credential does.
    again = pair(api).json()
    assert approve(api, again["code"]).status_code == 200
    second = poll(api, again).json()["token"]
    assert api.get("/api/v2/me", headers=headers(first["token"])).status_code == 401
    assert get(api, "me", token=second)["actor"] == "bot:scout"


def test_a_pairing_expires_and_can_be_declined(api):
    hermes_bot(api)
    late = pair(api).json()
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE agent_pairings SET expires_at=?", (H.shift(H.now(), seconds=-1),))
    assert approve(api, late["code"]).status_code == 404
    assert poll(api, late).json() == {"state": "expired"}
    # Approved but never collected is wiped when its time runs out.
    held = pair(api).json()
    assert approve(api, held["code"]).status_code == 200
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE agent_pairings SET expires_at=? WHERE id=?", (H.shift(H.now(), seconds=-1), held["pairing_id"]))
    assert poll(api, held).json() == {"state": "expired"}
    with api.app.state.store.read() as c:
        assert c.execute("SELECT token FROM agent_pairings WHERE id=?", (held["pairing_id"],)).fetchone()[0] is None
    refused = pair(api).json()
    declined = api.post("/api/v2/agents/pairings/decline", json={"code": refused["code"]}, headers=headers("cara-test"))
    assert declined.status_code == 200 and declined.json()["declined"] is True
    assert poll(api, refused).json() == {"state": "declined"}
    assert approve(api, refused["code"]).status_code == 404


def test_pairing_requests_are_rate_limited_per_address_and_capped_overall(api):
    for _ in range(10):
        assert pair(api, ip="10.0.0.1").status_code == 201
    limited = pair(api, ip="10.0.0.1")
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited"
    for _ in range(10):
        assert pair(api, ip="10.0.0.2").status_code == 201
    assert pair(api, ip="10.0.0.3").status_code == 429          # 20 are waiting: no more until some are answered


def test_who_may_approve_and_what_may_be_approved(api):
    hermes_bot(api)
    code = pair(api).json()["code"]
    # Cara neither owns Scout nor manages it: the server's own rule refuses, and the code stays open.
    assert approve(api, code, token="cara-test").status_code == 403
    # A bot on a computer cannot be paired.
    r = approve(api, code, bot="ops")
    assert r.status_code == 422 and "Hermes" in r.json()["error"]["detail"]
    # An admin may; so may an owner of that bot.
    post(api, "bots/scout/co-owners", {"add": ["cara"]})
    assert approve(api, code, token="cara-test").status_code == 200
    # A bot's own credential is not a person: it cannot approve a pairing for itself.
    token = post(api, "bots/scout/agent-credential", {})["token"]
    other = pair(api).json()["code"]
    assert approve(api, other, token=token).status_code == 403
    assert approve(api, other, token="ben-test").status_code == 200
    # An archived bot is not paired.
    hermes_bot(api, slug="old", status="planned")
    post(api, "bots/old/archive", {"expected_revision": get(api, "bots/old/access")["revision"]})
    assert approve(api, pair(api).json()["code"], bot="old").status_code == 409


def test_botops_pairs_a_profile_as_the_person_who_asked(api, botops):
    cara = turn(api, botops, person="cara-test", text="Connect my Hermes profile scout, code below")
    made = act(api, cara, "POST", "bots/register", {"slug": "scout", "display_name": "Scout", "model": "hermes",
                                                    "description": "A Hermes profile."})
    assert made.status_code == 200, made.text
    assert made.json()["harness"] == "hermes" and made.json()["status"] == "planned"
    # Activate it the way the app does; a Hermes bot has no computer to place it on.
    live = act(api, cara, "POST", "bots/scout/go-live", {"setup": False})
    assert live.status_code == 200 and live.json()["state"] == "active" and live.json()["computer"] is None
    pairing = pair(api).json()
    assert act(api, cara, "POST", "agents/pairings/approve", {"code": "NOPE-NOPE", "bot": "scout"}).status_code == 404
    done = act(api, cara, "POST", "agents/pairings/approve", {"code": pairing["code"], "bot": "scout"})
    assert done.status_code == 200 and done.json()["profile"] == "scout"
    with api.app.state.store.read() as c:
        event = c.execute("SELECT actor,detail_json FROM events WHERE action='agent.credential_issued' AND target='scout'").fetchone()
        assert event["actor"] == "human:cara" and '"via": "botops"' in event["detail_json"]
    token = poll(api, pairing).json()["token"]
    assert beat(api, token)["bot"] == "scout"
    # She is refused what she may not do: a bot that is not hers.
    mine = pair(api).json()
    assert act(api, cara, "POST", "agents/pairings/approve", {"code": mine["code"], "bot": "ops"}).status_code in (403, 422)
    hermes_bot(api, slug="anas")
    refused = act(api, cara, "POST", "agents/pairings/approve", {"code": mine["code"], "bot": "anas"})
    assert refused.status_code == 403
    # Rotating and revoking are hers to do too, and a token never comes back to BotOps.
    rotated = act(api, cara, "POST", "bots/scout/agent-credential", {})
    assert rotated.status_code == 200 and "tico-agent-" not in rotated.text and "pair" in rotated.json()["detail"]
    assert api.get("/api/v2/me", headers=headers(token)).status_code == 401
    assert act(api, cara, "POST", "bots/anas/agent-credential", {}).status_code == 403
    assert act(api, cara, "POST", "bots/scout/agent-credential/revoke", {}).json() == {"bot": "scout", "revoked": True}
    declined = act(api, cara, "POST", "agents/pairings/decline", {"code": mine["code"]})
    assert declined.status_code == 200 and poll(api, mine).json() == {"state": "declined"}


def test_restore_brings_an_archived_bot_back_to_what_it_was(api, botops):
    hermes_bot(api)
    assert post(api, "bots/scout/archive", {"expected_revision": get(api, "bots/scout/access")["revision"]})["status"] == "archived"
    # Nobody who does not manage it restores it, and a bot that is not archived has nothing to restore.
    assert api.post("/api/v2/bots/scout/restore", json={}, headers=headers("cara-test")).status_code == 403
    assert api.post("/api/v2/bots/ops/restore", json={}, headers=headers()).status_code == 409
    restored = post(api, "bots/scout/restore", {})
    assert restored["status"] == "active" and restored["restored"] is True and restored["agent"]["harness"] == "hermes"
    assert next(b for b in get(api, "bots") if b["slug"] == "scout")["state"] == "active"
    # A planned bot comes back planned; the same through BotOps as the requester, as a DO.
    hermes_bot(api, slug="draft", status="planned")
    post(api, "bots/draft/archive", {"expected_revision": get(api, "bots/draft/access")["revision"]})
    ana = turn(api, botops, person="ana-test", text="Bring draft back")
    back = act(api, ana, "POST", "bots/draft/restore", {})
    assert back.status_code == 200 and back.json()["status"] == "planned", back.text
    # A bot that was archived before the status was recorded comes back planned.
    post(api, "bots/scout/archive", {"expected_revision": get(api, "bots/scout/access")["revision"]})
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE events SET detail_json='{}' WHERE action='bot.archived' AND target='scout'")
    assert post(api, "bots/scout/restore", {})["status"] == "planned"
    # Register says where an archived slug went.
    post(api, "bots/scout/archive", {"expected_revision": get(api, "bots/scout/access")["revision"]})
    r = api.post("/api/v2/bots/register", json={"slug": "scout", "model": "hermes"}, headers=headers("cara-test"))
    assert r.status_code == 409 and "restore" in r.json()["error"]["detail"].lower()


def test_archiving_a_hermes_bot_says_its_agent_stops_and_revokes_the_credential(api):
    hermes_bot(api)
    token = post(api, "bots/scout/agent-credential", {})["token"]
    beat(api, token)
    archived = post(api, "bots/scout/archive", {"expected_revision": get(api, "bots/scout/access")["revision"]})
    assert archived["agent"]["harness"] == "hermes" and archived["agent"]["credential_revoked"] is True
    assert "Hermes agent will stop" in archived["agent"]["detail"]
    r = api.post("/api/v2/agents/heartbeat", json={}, headers=headers(token))
    assert r.status_code == 401
    # A bot on a computer says nothing about an agent.
    assert "agent" not in post(api, "bots/cpo/archive", {"expected_revision": get(api, "bots/cpo/access")["revision"]})


def test_an_archived_bots_agent_that_keeps_reporting_in_is_flagged_until_restored_or_revoked(api):
    hermes_bot(api)
    token = post(api, "bots/scout/agent-credential", {})["token"]
    beat(api, token)
    archived = post(api, "bots/scout/archive", {"expected_revision": get(api, "bots/scout/access")["revision"],
                                                 "revoke_agent": False})
    assert archived["agent"]["credential_revoked"] is False and "keeps reporting in" in archived["agent"]["detail"]
    assert issues(api, "scout") == []
    # The heartbeat is still refused with a 409 the connector can recognise.
    r = api.post("/api/v2/agents/heartbeat", json={"version": "1"}, headers=headers(token))
    assert r.status_code == 409 and r.json()["error"]["code"] == "bot_archived"
    (issue,) = issues(api, "scout")
    assert issue["title"] == "Scout's Hermes agent is still reporting in, but the bot is archived"
    assert issue["detail"] == "Restore it, or revoke its credential." and issue["needs_person"] is True
    # Restored, the credential works again and the issue is gone.
    post(api, "bots/scout/restore", {})
    assert issues(api, "scout") == []
    assert beat(api, token)["bot"] == "scout"
    # Archived again and then revoked: nothing is left to report.
    post(api, "bots/scout/archive", {"expected_revision": get(api, "bots/scout/access")["revision"], "revoke_agent": False})
    assert api.post("/api/v2/agents/heartbeat", json={}, headers=headers(token)).status_code == 409
    assert len(issues(api, "scout")) == 1
    post(api, "bots/scout/agent-credential/revoke", {})
    assert issues(api, "scout") == []


def test_a_renamed_tool_is_answered_with_its_new_name(api):
    failed, out = call(api, "hub_say", {"to": "ops", "text": "hi"})
    assert failed and out["error"] == "renamed" and out["renamed_to"] == "hub_message_send"
    assert out["detail"] == "`hub_say` was renamed `hub_message_send` in Tico 0.2.21."
    assert call(api, "hub_docs_search", {})[1]["renamed_to"] == "hub_doc_search"
    # A name that never existed is still an unknown tool, and every new name in the table is a tool.
    assert rpc(api, "tools/call", {"name": "hub_nothing", "arguments": {}})["error"]["code"] == -32602
    assert set(hubtools.RENAMED_TOOLS.values()) <= set(hubtools.BY_NAME)


def test_the_connector_is_served_without_a_sign_in_and_with_one(api):
    plain = api.get("/api/v2/agents/setup-script")
    assert plain.status_code == 200 and "hermes_agent" in plain.text or "Hermes" in plain.text
    hermes_bot(api)
    token = post(api, "bots/scout/agent-credential", {})["token"]
    assert api.get("/api/v2/agents/setup-script", headers=headers(token)).text == plain.text


def openclaw_bot(api, slug="claw"):
    return hermes_bot(api, slug=slug, model="openclaw-own", harness="openclaw", display_name="Claw")


def test_an_openclaw_bot_is_an_external_bot_with_a_credential_and_no_computer(api):
    made = openclaw_bot(api)
    assert made["harness"] == "openclaw"
    token = credential(api, "claw")["token"]
    assert beat(api, token, profile="claw")["bot"] == "claw"
    failed, me = call(api, "hub_whoami", token=token)
    assert not failed and me["agent"] == "openclaw"
    # A message waits in its inbox: no job is queued for a runner to claim.
    msg = post(api, "chat/claw", {"text": "Are you there?"})
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM jobs WHERE bot='claw'").fetchone()[0] == 0
    failed, inbox = call(api, "hub_message_list", token=token)
    assert not failed and [m["id"] for m in inbox["messages"]] == [msg["id"]]
    # It can place no computer, like a Hermes bot.
    assert api.post("/api/v2/bots/claw/computer", json={"runner_id": "x"}, headers=headers()).status_code in (404, 405, 422)
    # The tools the sync skill calls are all offered to an agent.
    for name in ("hub_whoami", "hub_note_list", "hub_message_list", "hub_task_list", "hub_message_send",
                 "hub_message_mark_read", "hub_task_update", "hub_conversation_show", "hub_question_answer"):
        assert "agent" in hubtools.offered_to(hubtools.BY_NAME[name]), name


def test_an_openclaw_profile_pairs_only_with_an_openclaw_bot(api):
    openclaw_bot(api)
    hermes_bot(api)
    code = pair(api, profile="claw", harness="openclaw").json()["code"]
    # A Hermes bot cannot take an OpenClaw profile's code, and the code stays open.
    refused = approve(api, code, bot="scout")
    assert refused.status_code == 422 and "OpenClaw" in refused.json()["error"]["detail"]
    done = approve(api, code, bot="claw")
    assert done.status_code == 200 and done.json()["profile"] == "claw"
    # And the other way round.
    wrong = pair(api, harness="hermes").json()["code"]
    refused = approve(api, wrong, bot="claw")
    assert refused.status_code == 422 and "Hermes" in refused.json()["error"]["detail"]
    # An unknown harness is not accepted at all.
    assert pair(api, harness="other").status_code == 422
    # The credential the profile collects is the OpenClaw bot's.
    pairing = pair(api, profile="claw", harness="openclaw").json()
    assert approve(api, pairing["code"], bot="claw").status_code == 200
    token = poll(api, pairing).json()["token"]
    assert get(api, "me", token=token)["agent"] == "openclaw"


def test_botops_registers_an_openclaw_bot_with_the_model_openclaw(api, botops):
    cara = turn(api, botops, person="cara-test", text="Connect my OpenClaw profile claw, code below")
    made = act(api, cara, "POST", "bots/register", {"slug": "claw", "display_name": "Claw", "model": "openclaw",
                                                    "description": "An OpenClaw profile."})
    assert made.status_code == 200, made.text
    assert made.json()["harness"] == "openclaw" and made.json()["status"] == "planned"
    live = act(api, cara, "POST", "bots/claw/go-live", {"setup": False})
    assert live.status_code == 200 and live.json()["computer"] is None
    pairing = pair(api, profile="claw", harness="openclaw").json()
    done = act(api, cara, "POST", "agents/pairings/approve", {"code": pairing["code"], "bot": "claw"})
    assert done.status_code == 200, done.text


def test_an_archived_openclaw_bot_says_so_in_its_own_words(api):
    openclaw_bot(api)
    token = credential(api, "claw")["token"]
    beat(api, token, profile="claw")
    archived = post(api, "bots/claw/archive", {"expected_revision": get(api, "bots/claw/access")["revision"],
                                               "revoke_agent": False})
    assert "OpenClaw agent will stop" in archived["agent"]["detail"]
    assert api.post("/api/v2/agents/heartbeat", json={"version": "1"}, headers=headers(token)).status_code == 409
    assert [i["title"] for i in issues(api, "claw")] == ["Claw's OpenClaw agent is still reporting in, but the bot is archived"]


def test_the_sync_skill_is_served_without_a_sign_in_and_is_the_file_in_the_repository(api):
    from pathlib import Path
    plain = api.get("/api/v2/agents/sync-skill")
    assert plain.status_code == 200
    assert plain.text == (Path(hubtools.__file__).resolve().parents[1] / "skills" / "tico-sync" / "SKILL.md").read_text()
    assert plain.text.startswith("---\nname: tico-sync\n")


def test_pairing_preview_does_not_rotate_a_working_credential(api):
    hermes_bot(api)
    token = credential(api)["token"]
    made = pair(api).json()
    shown = get(api, "agents/pairing-preview?code=" + made["code"])
    assert shown["profile"] == "scout" and shown["host"] == "mac-mini" and shown["harness"] == "hermes"
    assert "token" not in shown
    assert get(api, "me", token=token)["actor"] == "bot:scout"
    assert poll(api, made).json()["state"] == "pending"
