"""A task's run panel (GET /api/v2/tasks/{id}/run-view): each attempt with what followed it, the subagents it started,
the background shells and monitors still running, and the checkpoint. Nothing from a call's arguments reaches it."""
import json

from backend.store import H
from backend.tests.test_api import api, assign, claim, expire, get, post, ready, runner  # noqa: F401
from backend.tests.test_execution_review import aged, sweep


def task_attempt(api, machine, title="Count the words"):
    task = post(api, "tasks", {"owner": "ops", "title": title, "body": "Count them."})
    attempt = claim(api, machine)
    assert attempt["task"]["id"] == task["id"]
    post(api, f"attempts/{attempt['id']}/started", {"thread_id": title}, machine["token"])
    return task["id"], attempt


def events(api, machine, aid, rows, first=1):
    post(api, f"attempts/{aid}/events", {"events": [{"seq": first + i, "kind": k, "payload": p}
                                                    for i, (k, p) in enumerate(rows)]}, machine["token"])


def test_a_run_shows_its_subagent_and_the_background_command_it_left_running(api):
    machine = runner(api, "ana")
    assign(api, machine, "ops")
    ready(api, machine, ["ops"])
    tid, attempt = task_attempt(api, machine)
    aid, secret = attempt["id"], "hunter2-token"
    agent = {"id": "a1", "parent_id": None, "type": "general-purpose", "model": "claude-haiku-5-5",
             "description": f"count {secret}"}
    events(api, machine, aid, [
        ("status", {"state": "active", "tool_events": True}),
        ("tool", {"tool": "Bash", "status": "started", "item_id": "s1", "summary": "sleep", "parent_id": None,
                  "background": True}),
        ("tool", {"tool": "Monitor", "status": "started", "item_id": "m1", "summary": "tail", "parent_id": None,
                  "background": True}),
        ("tool", {"tool": "Monitor", "status": "completed", "item_id": "m1", "parent_id": None, "background": True}),
        ("tool", {"tool": "Agent", "status": "started", "item_id": "a1", "summary": "", "parent_id": None,
                  "subagent": {**agent, "status": "started"}}),
        ("tool", {"tool": "Agent", "status": "backgrounded", "item_id": "a1", "parent_id": None, "background": True}),
        ("tool", {"tool": "Bash", "status": "started", "item_id": "b2", "summary": "wc", "parent_id": "a1"}),
        ("tool", {"tool": "Bash", "status": "completed", "item_id": "b2", "parent_id": "a1"}),
        ("tool", {"tool": "Agent", "status": "completed", "item_id": "a1", "parent_id": None, "background": True,
                  "subagent": {**agent, "status": "completed", "tool_uses": 1, "duration_ms": 2201}}),
        # A shell Claude moved to the background while it ran: its start did not say so.
        ("tool", {"tool": "Bash", "status": "started", "item_id": "s2", "summary": "npm", "parent_id": None}),
        ("tool", {"tool": "Bash", "status": "backgrounded", "item_id": "s2", "parent_id": None, "background": True})])
    view = get(api, f"tasks/{tid}/run-view")
    assert secret not in json.dumps(view)
    [run] = view["attempts"]
    assert (run["run"], run["state"], run["try"], run["tries"], run["next"]) == (aid, "running", 1, 1, None)
    assert [(s["tool"], s["summary"], s["running"]) for s in run["background"]] == [
        ("Bash", "sleep", True), ("Monitor", "tail", False), ("Bash", "", True)]
    [sub] = run["subagents"]
    assert (sub["type"], sub["model"], sub["status"], sub["tool_uses"], sub["duration_ms"], sub["background"]) == (
        "general-purpose", "claude-haiku-5-5", "completed", 1, 2201, True)
    # The steps view keeps one line for the subagent that moved to the background.
    steps = get(api, f"turns/{aid}/steps")["steps"]
    assert [(s["kind"], s.get("nested", False)) for s in steps] == [
        ("tool", False), ("tool", False), ("subagent", False), ("tool", True), ("tool", False)]

    post(api, f"attempts/{aid}/complete", {"outcome": "completed", "last_seq": 11, "text": "Counted: 1 word."},
         machine["token"])
    view = get(api, f"tasks/{tid}/run-view")
    [shell, _, moved] = view["attempts"][0]["background"]
    assert (shell["running"], shell["status"]) == (False, "no end reported") == (moved["running"], moved["status"])
    assert view["checkpoint"]["text"] == "Counted: 1 word." and view["checkpoint"]["by"] == "bot:ops"

    # A run that also carried a private task is left out for whoever cannot read that task.
    hidden = post(api, "tasks", {"owner": "ops", "title": "Private", "body": "Only Ana.", "private": True})
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE tasks SET carried_by=? WHERE id=?", (aid, hidden["id"]))
    assert get(api, f"tasks/{tid}/run-view", token="cara-test")["attempts"] == []
    assert [r["run"] for r in get(api, f"tasks/{tid}/run-view")["attempts"]] == [aid]


def test_a_retried_run_shows_both_attempts_and_the_decision_between_them(api):
    machine = runner(api, "ana")
    assign(api, machine, "ops")
    ready(api, machine, ["ops"])
    tid, first = task_attempt(api, machine, "Archive the bots")
    events(api, machine, first["id"], [("tool", {"name": "shell"}),
                                       ("message", {"text": "Archived one bot; the second is next."})])
    expire(api, first["id"])
    assert claim(api, machine) is None
    view = get(api, f"tasks/{tid}/run-view")
    assert view["attempts"][0]["next"]["kind"] == "waiting"
    assert view["attempts"][0]["reason"] == "Lease expired before completion"
    aged(api, first["id"])
    assert [d["state"] for d in sweep(api)] == ["queued"]
    ready(api, machine, ["ops"])
    second = claim(api, machine)
    assert second["job_id"] == first["job_id"]
    later, earlier = get(api, f"tasks/{tid}/run-view")["attempts"]
    with api.app.state.store.read() as c:
        from backend.run_view import RECOVERY_SQL
        plan = " ".join(r[-1] for r in c.execute(f"EXPLAIN QUERY PLAN SELECT ts FROM events WHERE {RECOVERY_SQL} "
                                                 "AND target IN (?,?)", ("j", "a")))
    assert "events_action_target" in plan, plan
    assert (earlier["run"], earlier["try"], earlier["tries"], earlier["state"]) == (first["id"], 1, 2, "expired")
    assert earlier["next"]["kind"] == "resumed" and earlier["next"]["by"] == H.KEEPER and earlier["next"]["note"]
    assert "Archived one bot" not in json.dumps(earlier), "the hub's own words, never what the stopped run saved"
    assert (later["run"], later["try"], later["tries"], later["next"]) == (second["id"], 2, 2, None)


def test_a_run_from_a_conversation_the_reader_cannot_open_stays_out(api):
    """A person's direct message to the bot that names the task puts that run on the task; only who can read that
    conversation (and the bot) sees it. A blocked checkpoint is not shown."""
    machine = runner(api, "ana")
    assign(api, machine, "ops")
    ready(api, machine, ["ops"])
    tid, shared = task_attempt(api, machine, "Export the report")
    post(api, f"attempts/{shared['id']}/complete", {"outcome": "completed", "last_seq": 0, "text": "Exported."},
         machine["token"])
    post(api, "chat/ops", {"text": "Run the payroll export for this task."})
    direct = claim(api, machine)
    post(api, f"attempts/{direct['id']}/started", {"thread_id": "dm"}, machine["token"])
    events(api, machine, direct["id"], [("tool", {"tool": "Bash", "status": "started", "item_id": "p1",
                                                  "summary": "payroll-export.sh", "parent_id": None, "background": True})])
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE turns SET task_id=? WHERE id=?", (tid, direct["id"]))
    assert {r["run"] for r in get(api, f"tasks/{tid}/run-view")["attempts"]} == {shared["id"], direct["id"]}
    seen = get(api, f"tasks/{tid}/run-view", token="cara-test")
    assert [r["run"] for r in seen["attempts"]] == [shared["id"]] and "payroll" not in json.dumps(seen)
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE tasks SET checkpoint_blocked=1 WHERE id=?", (tid,))
    assert get(api, f"tasks/{tid}/run-view")["checkpoint"] is None
