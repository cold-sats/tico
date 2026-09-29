"""The hub's MCP door: same tools as the `hub` CLI, same rules, no privileged path."""

import io
import json

from backend.tests.test_api import api, assign, claim, get, headers, post, ready, runner, setup_attempt  # noqa: F401
from clients import hubcli, hubtools


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
    # A tool that reaches out to the internet (hub_docs_fetch) runs on the bot's computer, never here.
    assert {t["name"] for t in tools} == {n for n, t in hubtools.BY_NAME.items() if not t["local"]}
    assert all(t["inputSchema"]["type"] == "object" for t in tools)
    assert api.get("/api/v2/mcp", headers=headers()).status_code == 405
    assert api.post("/api/v2/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "resources/list"},
                    headers=headers()).json()["error"]["code"] == -32601


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

