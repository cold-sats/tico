"""The hub's MCP door: same tools as the `hub` CLI, same rules, no privileged path."""

import io
import json
from pathlib import Path

from backend.store import H
from backend.tests.test_api import api, assign, claim, get, headers, post, ready, runner, setup_attempt  # noqa: F401
from clients import hubcli, hubtools
from clients.agent_skill import WHO_NEEDS_ME


def rpc(api, method, params=None, token="ana-test", rid=1):
    r = api.post("/api/v2/mcp", json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}},
                 headers=headers(token))
    assert r.status_code == 200, r.text
    return r.json()


def call(api, name, arguments=None, token="ana-test"):
    reply = rpc(api, "tools/call", {"name": name, "arguments": arguments or {}}, token=token)
    result = reply["result"]
    payload = result.get("structuredContent")
    return result["isError"], payload if payload is not None else json.loads(result["content"][0]["text"])


def test_initialize_lists_every_tool_and_ignores_notifications(api):
    init = rpc(api, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "test", "version": "0"}})
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert init["result"]["capabilities"] == {"tools": {}}
    r = api.post("/api/v2/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers())
    assert r.status_code == 202 and r.content == b""
    tools = rpc(api, "tools/list")["result"]["tools"]
    assert {t["name"] for t in tools} == set(hubtools.BY_NAME)
    assert all(t["inputSchema"]["type"] == "object" for t in tools)
    assert api.get("/api/v2/mcp", headers=headers()).status_code == 405
    assert api.post("/api/v2/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "resources/list"},
                    headers=headers()).json()["error"]["code"] == -32601


def test_the_skill_file_is_the_same_text_the_server_sends():
    skill = (Path(__file__).resolve().parents[2] / "skills" / "who-needs-me" / "SKILL.md").read_text()
    assert skill.startswith("---\nname: who-needs-me\n")
    assert skill.split("\n---\n\n", 1)[1] == WHO_NEEDS_ME


def test_agent_skill_gives_a_person_the_runner_mcp_address_and_the_skill(api, monkeypatch):
    monkeypatch.setattr(api.app.state.auth.settings, "runner_url", "https://runner.example.test")
    for token in ("ana-test", "cara-test"):
        assert get(api, "agent-skill", token=token) == {"mcp_url": "https://runner.example.test/api/v2/mcp",
                                                          "text": WHO_NEEDS_ME}
    from backend.tests.test_agents import credential, hermes_bot   # it imports this module
    hermes_bot(api)
    bot = credential(api)["token"]
    r = api.get("/api/v2/agent-skill", headers=headers(bot))
    assert r.status_code == 403 and WHO_NEEDS_ME not in r.text


def test_mcp_needs_the_same_credential_as_http(api):
    r = api.post("/api/v2/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401


def test_every_cli_command_has_a_tool_of_the_same_name():
    """The schema is the standard; `hub <words>` is `hub_<words>` with underscores.

    A command that only works on the Mac (it writes the workspace) is listed in
    `hubtools.SHELL_ONLY`, so adding one is a decision, not an omission."""
    names = set()
    for action in hubcli.parser()._subparsers._group_actions:
        for word, sub in action.choices.items():
            groups = [a for a in sub._actions if getattr(a, "choices", None) and not isinstance(a.choices, (list, tuple))]
            if groups:
                names.update(f"hub_{word}_{leaf}" for leaf in groups[0].choices)
            else:
                names.add(f"hub_{word}")
    assert names - hubtools.SHELL_ONLY == set(hubtools.BY_NAME)
    assert hubtools.SHELL_ONLY <= names


def test_tools_write_through_the_same_rules_as_http(api):
    r, msg, attempt = setup_attempt(api)
    token = attempt["token"]
    err, me = call(api, "hub_whoami", token=token)
    assert not err and me["actor"] == "bot:ops"

    err, out = call(api, "hub_say", {"to": "ops", "text": "Talking to myself"}, token=token)
    assert err and out["error"] == "self"

    err, out = call(api, "hub_task_create", {"owner": "ana", "title": "The thing", "body": "x"}, token=token)
    assert err and out["error"] == "lint"

    err, out = call(api, "hub_task_create", {"owner": "ana", "title": "The thing", "body": "x", "dry_run": True}, token=token)
    assert not err and out["ok"] is False and any("verb" in p for p in out["problems"])
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM tasks WHERE requester='bot:ops'").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM events WHERE action LIKE 'refus%' AND actor='bot:ops'").fetchone()[0] >= 1

    err, task = call(api, "hub_task_create", {"owner": "cpo", "title": "Review the runtime", "body": "Please.",
                                               "operation_id": "op-1"}, token=token)
    assert not err and task["task"]["owner"] == "bot:cpo"
    err, again = call(api, "hub_task_create", {"owner": "cpo", "title": "Review the runtime", "body": "Please.",
                                                "operation_id": "op-1"}, token=token)
    assert not err and again["task"]["id"] == task["task"]["id"]

    err, shown = call(api, "hub_task_show", {"id": task["task"]["id"]}, token=token)
    assert not err and shown["task"]["title"] == "Review the runtime"

    # A bot reads its conversation back itself: the hub rebuilds nothing into a session.
    err, page = call(api, "hub_history", {"conversation": msg["conversation_id"]}, token=token)
    assert not err and page["conversation"]["id"] == msg["conversation_id"]
    assert [m["body"] for m in page["messages"]][0] == msg["body"]

    # A bot sets up its own routine; the same key is the same routine.
    err, routine = call(api, "hub_routine_set", {"key": "audit", "title": "Daily audit", "cron": "0 7 * * 1-5",
                                                  "text": "Audit the rentals"}, token=token)
    assert not err and routine["id"] == "ops:audit" and routine["enabled"] == 1
    err, again = call(api, "hub_routine_set", {"key": "audit", "title": "Daily audit", "cron": "0 8 * * 1-5"}, token=token)
    assert not err and again["cron"] == "0 8 * * 1-5"
    err, listed = call(api, "hub_routine_list", {}, token=token)
    assert not err and [r["key"] for r in listed["result"]] == ["audit"]
    err, out = call(api, "hub_routine_set", {"key": "other", "title": "Not mine", "cron": "0 7 * * *", "bot": "cpo"}, token=token)
    assert err
    err, gone = call(api, "hub_routine_delete", {"id": "ops:audit"}, token=token)
    assert not err and gone["deleted_at"]
    err, listed = call(api, "hub_task_list", {"requester": "me"}, token=token)
    assert not err and [t["id"] for t in listed["result"]] == [task["task"]["id"]]

    err, out = call(api, "hub_task_close", {"id": task["task"]["id"], "note": "Not needed"}, token=token)
    assert not err and out["task"]["status"] == "closed"
    err, out = call(api, "hub_task_show", {"id": "no-such-task"}, token=token)
    assert err and out["error"] == "not_found" and out["retryable"] is False


def test_tools_refuse_a_runner_credential_like_http_does(api):
    r = runner(api)
    err, out = call(api, "hub_inbox", token=r["token"])
    assert err and out["error"] == "identity"


def test_a_person_works_who_needs_them_one_bot_at_a_time_through_mcp(api):
    """What Grok Bot or any connected assistant does on "who needs me"."""
    _, _, finance = setup_attempt(api, "finance")
    post(api, "tasks", {"title": "Grant the replica", "body": "Read-only", "owner": "human:ana"},
         token=finance["token"])
    _, _, inbox = setup_attempt(api, "inbox")
    post(api, "tasks", {"title": "Decide mail 1", "body": "Keep or close", "owner": "human:ana"},
         token=inbox["token"])
    post(api, "tasks", {"title": "Sign the lease", "body": "Ready", "owner": "human:ana"})
    err, b = call(api, "hub_batch_start")
    assert not err and b["scope"] in ("bot:finance", "bot:inbox") and b["total"] == 1
    assert {g["who"] for g in b["lineup"]} == {"bot:finance", "bot:inbox"}, "never the person's own work"
    first, other = b["scope"], ({"bot:finance", "bot:inbox"} - {b["scope"]}).pop()
    err, _ = call(api, "hub_batch_respond", {"batch": b["id"], "kind": "instruct", "text": "Do it."})
    assert not err
    err, done = call(api, "hub_batch_commit", {"batch": b["id"]})
    assert not err and done["sent"] == {first[4:]: 1} and done["up_next"]["who"] == other
    err, named = call(api, "hub_batch_start", {"bot": other[4:]})
    assert not err and named["scope"] == other
    err, gone = call(api, "hub_batch_abandon", {"batch": named["id"]})
    assert not err and gone["abandoned"]
    err, everything = call(api, "hub_batch_start", {"all": True})
    assert not err and everything["scope"] is None and everything["total"] == 2
    err, refused = call(api, "hub_batch_start", token=finance["token"])
    assert err, "a batch is a person's; a bot is refused"


def test_a_person_on_the_go_is_caught_up_in_one_call(api):
    """Ana, 2026-09-26: Live through Grok Bot. One fast read: who is waiting, what bots said,
    what is broken; it consumes nothing, and `since` narrows what bots said."""
    _, _, finance = setup_attempt(api, "finance")
    post(api, "tasks", {"title": "Approve the Canva renewal", "body": "Yes or no", "owner": "human:ana"},
         token=finance["token"])
    post(api, "messages", {"to": "human:ana", "text": "The Brex warning cleared."}, token=finance["token"])
    err, brief = call(api, "hub_live_brief")
    assert not err
    assert [g["who"] for g in brief["lineup"]] == ["bot:finance"] and brief["lineup"][0]["items"] == 1
    assert brief["said"][0]["text"] == "The Brex warning cleared." and brief["open_batch"] is False
    assert isinstance(brief["alerts"], list) and isinstance(brief["stuck"], int)
    err, later = call(api, "hub_live_brief", {"since": brief["now"]})
    assert not err and later["said"] == [], "since narrows it to what is new"
    err, again = call(api, "hub_batch_start")
    assert not err and again["total"] == 1, "the brief consumed nothing"
    err, refused = call(api, "hub_live_brief", token=finance["token"])
    assert err, "a person's brief; a bot is refused"


def test_every_assistant_tool_call_is_timed_and_summed_up(api):
    """Ana, 2026-09-26: record timing and stats as he uses Grok Bot, so it keeps improving."""
    token = post(api, "me/tokens", {"label": "grok-bot"})["token"]
    for _ in range(3):
        err, _ = call(api, "hub_whoami", token=token)
        assert not err
    err, _ = call(api, "hub_task_show", {"id": "nope"}, token=token)
    with api.app.state.store.read() as c:
        rows = [json.loads(r[0]) for r in c.execute("SELECT detail_json FROM events WHERE action='mcp.call'")]
    assert len(rows) == 4 and all(r["via"] == "grok-bot" and r["ms"] >= 0 and r["bytes"] > 0 for r in rows)
    assert "arguments" not in json.dumps(rows) and sum(r["error"] for r in rows) == 1
    err, stats = call(api, "hub_live_stats", {"via": "grok-bot"})
    assert not err
    who = next(t for t in stats["tools"] if t["tool"] == "hub_whoami")
    assert who["calls"] == 3 and who["errors"] == 0 and who["median_bytes"] > 0
    assert next(t for t in stats["tools"] if t["tool"] == "hub_task_show")["errors"] == 1


def test_voice_tools_answer_short_and_reuse_the_fleet_snapshot(api):
    """Ana, 2026-09-26: cache the fleet status and send smaller answers, so Grok Bot speaks sooner."""
    from backend import views
    _, _, finance = setup_attempt(api, "finance")
    post(api, "tasks", {"title": "Approve the Canva renewal", "body": ("Detail-" + "x" * 20 + " ") * 60, "owner": "human:ana"},
         token=finance["token"])
    err, b = call(api, "hub_batch_start")
    assert not err
    item = b["item"]
    assert len(item.get("body", "")) <= 500 and "hub_task_show" in item["more"]
    assert "rank" not in item and "created" not in item
    views._FLEET_CACHE.clear()
    calls = []
    real = views.fleet_snapshot
    views.fleet_snapshot = lambda *a, **k: calls.append(1) or real(*a, **k)
    try:
        call(api, "hub_live_brief"); call(api, "hub_live_brief")
    finally:
        views.fleet_snapshot = real
    assert len(calls) == 1, "the second brief within 15 s reuses the snapshot"


def test_hub_recent_says_which_bots_i_have_been_working_with_and_where_they_stand(api):
    """Ana, 2026-09-27: "some recent history thing in my mcp ... what bot I have been working on
    recently. What their status is", so an agent of his can carry on."""
    post(api, "chat/ops", {"text": "Where are we on the pricing page?"})
    post(api, "chat/finance", {"text": "Check the Brex balance"})
    post(api, "tasks", {"title": "Draft the pricing page", "body": "Details.", "owner": "ops"})
    with api.app.state.store.transaction() as c:
        cid = c.execute("SELECT conversation_id FROM messages WHERE to_actor='bot:ops' LIMIT 1").fetchone()[0]
        H.say(c, H.bot_actor("ops"), H.human_actor("ana"), "The table is drafted; numbers next.",
              kind="say", conversation_id=cid)
        H.status_set(c, H.bot_actor("ops"), "ops", state="running", focus="Checking the numbers")
    error, out = call(api, "hub_recent", {})
    assert not error, out
    bots = {b["bot"]: b for b in out["bots"]}
    assert out["bots"][0]["bot"] == "ops", "the most recent first"
    assert set(bots) == {"ops", "finance"}
    ops = bots["ops"]
    assert ops["status"]["state"] == "running" and ops["status"]["focus"] == "Checking the numbers"
    assert ops["you_said"]["text"] == "Where are we on the pricing page?"
    assert ops["it_said"]["text"] == "The table is drafted; numbers next."
    assert ops["conversation_id"] == cid
    assert [t["title"] for t in ops["open_tasks"]] == ["Draft the pricing page"]
    # A person's history only: Ben has worked with no bot.
    error, out = call(api, "hub_recent", {}, token="ben-test")
    assert not error and out["bots"] == []
    # And the window is honoured.
    assert get(api, "me/recent?days=1&limit=1")["bots"][0]["bot"] == "ops"
