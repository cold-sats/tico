import json

import pytest

from backend.store import H
from backend.tests.test_api import api, as_member, headers, get, post, restrict, setup_attempt, runner, ready, assign, claim


def test_quarantine_remains_a_human_action_after_a_runner_expiry(api):
    with api.app.state.store.transaction() as c:
        H.quarantine(c, 'coo', 'escape: review the refused task')
        H.status_set(c, H.KEEPER, 'coo', state='crashed', focus='Runner disconnected')
    issues = api.get('/api/status', headers=headers()).json()['health_issues']
    issue = next(i for i in issues if i['kind'] == 'bot' and i['bot'] == 'coo')
    assert issue['needs_person'] is True
    assert 'refused task' in issue['detail']
    assert 'resume the bot' in issue['action']


def test_revocation_invalidates_running_bot_credential(api):
    r, _, attempt = setup_attempt(api)
    post(api, f"runners/{r['runner_id']}/revoke", {})
    get(api, "me", r["token"], expected=401)
    get(api, "me", attempt["token"], expected=401)


def test_bot_execution_cannot_read_another_humans_personal_chat(api):
    secret = post(api, "chat/ops", {"text": "Ana private context"})
    r = runner(api)
    assign(api, r, "ops")
    ready(api, r, ["ops"])
    # Complete the older job so the next claim belongs to Ben's conversation.
    first = claim(api, r)
    post(api, f"attempts/{first['id']}/started", {"thread_id": "ana-context"}, r["token"])
    post(api, f"attempts/{first['id']}/complete", {"outcome": "completed", "last_seq": 0}, r["token"])
    own = post(api, "chat/ops", {"text": "Ben work"}, "ben-test")
    attempt = claim(api, r)
    assert attempt["message"]["id"] == own["id"]
    get(api, f"conversations/{secret['conversation_id']}/messages", attempt["token"], expected=403)
    assert secret["id"] not in {row["id"] for row in get(api, "inbox", attempt["token"])["messages"]}
    post(api, "messages", {"to": "human:ana", "text": "Use an old private chat"}, attempt["token"], expected=403)
    question = post(api, "messages", {"to": "finance", "text": "What is the budget?", "kind": "ask"}, attempt["token"])
    assert get(api, f"conversations/{question['conversation_id']}/messages", attempt["token"])


def test_tico_fleet_snapshot_is_bound_to_the_initiating_human(api):
    as_member(api, "ben@acme.example")
    with api.app.state.store.transaction() as c:      # finance takes requests from Ana alone
        restrict(c, "finance", people=["ana"])
    post(api, "tasks", {"title": "Review product direction", "body": "Choose the next slice", "owner": "cpo"},
         "ben-test")
    post(api, "tasks", {"title": "What is blocked?", "body": "List it", "owner": "coo"}, "ben-test")
    machine = runner(api)
    assign(api, machine, "coo")
    ready(api, machine, ["coo"])
    attempt = claim(api, machine)
    fleet = get(api, "tico/fleet", attempt["token"])
    assert fleet["actor"] == "human:ben"
    # The assistant is in the fleet (it still takes work) though nobody chats with it.
    assert {bot["slug"] for bot in fleet["bots"]} == {"coo", "ops", "cpo", "product-design", "doc-updater"}
    assert any(task["title"] == "Review product direction" for task in fleet["tasks"])
    assert "finance" not in {bot["slug"] for bot in fleet["bots"]}


def test_tico_task_execution_cannot_assume_a_private_fleet_identity(api):
    with api.app.state.store.transaction() as c:
        H.task_create(c, "human:ana", "Legacy isolated task", "Review the queue", "bot:coo")
    machine = runner(api)
    assign(api, machine, "coo")
    ready(api, machine, ["coo"])
    attempt = claim(api, machine)
    assert attempt["conversation"]["scope"] == "task"
    get(api, "tico/fleet", attempt["token"], expected=403)


def test_message_pagination_preserves_all_history_with_timestamp_ties(api):
    msg = post(api, "chat/ops", {"text": "First message"})
    with api.app.state.store.transaction() as c:
        for n in range(240):
            H.say(c, "human:ana", "bot:ops", f"Message {n}", conversation_id=msg["conversation_id"])
        c.execute("UPDATE messages SET created='2026-09-10T10:00:00Z'")
    path = f"/api/v2/conversations/{msg['conversation_id']}/messages"
    newest = api.get(path, headers=headers()).json()
    assert newest["messages"][-1]["body"] == "Message 239"
    assert len(newest["messages"]) == 200 and newest["has_more"]
    older = api.get(path, params={"before": newest["next_before"]}, headers=headers()).json()
    assert len(older["messages"]) == 41 and not older["has_more"]
    assert older["messages"][0]["id"] == msg["id"]
    assert len({m["id"] for m in older["messages"] + newest["messages"]}) == 241


def test_task_chat_never_falls_back_to_the_assistant(api):
    # The assistant's own task names it, but nobody chats with it.
    review = post(api, "tasks", {"title": "Review refused writes", "body": "Look.", "owner": "coo"})
    read = get(api, f"tasks/{review['id']}/chat")
    assert read["bot"] == "coo" and read["recipient"]["can_chat"] is False and read["conversation"] is None
    post(api, f"tasks/{review['id']}/chat", {"text": "Hello"}, expected=403)
    # A person's own task with no bot on it has nobody to chat to, and says so.
    own = post(api, "tasks", {"title": "Call the landlord", "body": "Today.", "owner": "human:ana"})
    read = get(api, f"tasks/{own['id']}/chat")
    assert read["bot"] is None and read["recipient"] is None and read["messages"] == []
    refused = post(api, f"tasks/{own['id']}/chat", {"text": "Hello"}, expected=409)
    assert refused["error"]["code"] == "no_bot"
    post(api, "page-chat", {"page": "tasks", "task_id": own["id"], "text": "Hello"}, expected=409)
    # The tasks page's assistant chat is gone with it.
    post(api, "page-chat", {"page": "tasks", "text": "What is late?"}, expected=422)



def test_bot_instructions_show_the_published_file_and_do_not_substitute_description(api):
    path = "/api/employees/ops/files"
    before = api.get(path, headers=headers()).json()
    assert before["AGENT.md"] == ""
    snapshot = get(api, "bots/ops/instructions")
    assert snapshot["content"] == "" and snapshot["published"] is False and snapshot["updated"] is None
    text = "# Instructions\n\nUse the support policy.\n"
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO bot_agent_instructions VALUES(?,?,?,?)", ("ops", text, "computer-1", H.now()))
    assert api.get(path, headers=headers()).json()["AGENT.md"] == text
    snapshot = get(api, "bots/ops/instructions")
    assert snapshot["content"] == text and snapshot["published"] is True and snapshot["updated"]
    from backend.tests.test_api import restrict
    with api.app.state.store.transaction() as c:
        restrict(c, "ops", people=["ana"])
    assert api.get("/api/v2/bots/ops/instructions", headers=headers("cara-test")).status_code == 404


def test_computers_omit_archived_bots_and_show_team_services_once(api):
    r = runner(api)
    assign(api, r, "ops")
    ready(api, r, ["ops"])
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bots SET state='archived' WHERE slug='ops'")
        c.execute("INSERT INTO service_health VALUES('sample-service',?,NULL,'{}')", (H.now(),))
    result = get(api, "computers")
    computer = next(row for row in result["computers"] if row["id"] == r["runner_id"])
    assert "ops" not in computer["readiness"]["bots"]
    assert computer["services"] == []
    assert any(row["service"] == "sample-service" and row["scope"] == "team" for row in result["services"])


@pytest.mark.parametrize("problems, expected, reason", [
    (["No AI provider is chosen: the owner picks providers and a default model in Settings > AI providers"],
     "Saved — no AI provider is chosen", "missing_provider"),
    (["Missing bot repository or AGENT.md"], "Saved — Missing bot repository or AGENT.md", None),
    ([], "Saved — waiting for computer setup", None),
])
def test_queued_chat_names_readiness_problem(api, problems, expected, reason):
    r = runner(api)
    assign(api, r, "ops")
    ready(api, r, ["ops"])
    msg = post(api, "chat/ops", {"text": "Set up this bot"})
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE runners SET readiness_json=? WHERE id=?", (json.dumps({
            "schema_version": 1, "bots": {"ops": {"ready": False, "problems": problems}}
        }), r["runner_id"]))
    snap = get(api, f"conversations/{msg['conversation_id']}/snapshot")["execution"]
    assert snap["state"] == "queued" and snap["label"] == expected
    assert snap.get("readiness_reason") == reason
    # Older computers report just a boolean, without any readiness details.
    post(api, "runners/heartbeat", {"version": "test", "platform": "test", "readiness": {"ops": False}}, r["token"])
    snap = get(api, f"conversations/{msg['conversation_id']}/snapshot")["execution"]
    assert snap["label"] == "Saved — waiting for computer setup"
    assert "readiness_reason" not in snap


def test_old_computer_reports_ignore_unassigned_and_archived_bots(api):
    from backend import health
    machine = runner(api)
    assign(api, machine, "ops")
    ready(api, machine, ["ops"])
    report = {"ready": False, "repository_present": False,
              "problems": ["Missing bot repository"],
              "warnings": ["GitHub history not published: unavailable"]}
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bots SET state='archived' WHERE slug='coo'")
        c.execute("UPDATE runners SET readiness_json=? WHERE id=?",
                  (json.dumps({"schema_version": 1, "bots": {"ops": {"ready": True}, "finance": report,
                                        "coo": report, "unknown": report}}), machine["runner_id"]))
    computers = get(api, "computers")["computers"]
    computer = next(row for row in computers if row["id"] == machine["runner_id"])
    assert set(computer["readiness"]["bots"]) == {"ops"}
    operations = get(api, "operations")
    row = next(row for row in operations["machines"] if row["id"] == machine["runner_id"])
    assert set(row["readiness"]["bots"]) == {"ops"}
    with api.app.state.store.read() as c:
        assert health.missing_repositories(c, {machine["runner_id"]}) == []
        assert health._unpublished(c) == []
