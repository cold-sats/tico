import json

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


def test_a_runner_checkout_off_main_is_an_owner_issue(api):
    """#492: the production runner ran 28 commits behind main for a day because a bot committed in
    its checkout. Local commits are said at once; behind, once it has lasted an hour."""
    from backend.tests.test_api import runner as enroll
    r = enroll(api)
    head, running = "a" * 40, "b" * 40

    def beat(**checkout):
        post(api, "runners/heartbeat", {"version": "test", "platform": "test", "readiness": {},
             "checkout": {"head": head, "running": head, "ahead": 0, "behind": 0,
                          "checked_at": "2026-09-24T18:00:00Z", **checkout}}, token=r["token"])
        return [i for i in get(api, "operations")["issues"] if i.get("kind") == "runner_checkout"]

    assert beat() == []
    ahead = beat(ahead=3, behind=28)
    assert len(ahead) == 1 and "3 local commits and 28 behind main" in ahead[0]["detail"]
    assert beat(behind=5) == [], "behind for less than an hour: a pull is probably on its way"
    with api.app.state.store.transaction() as c:
        row = c.execute("SELECT checkout_json FROM runners WHERE id=?", (r["runner_id"],)).fetchone()
        checkout = json.loads(row["checkout_json"])
        assert checkout["behind_since"], "the server remembers when it fell behind"
        checkout["behind_since"] = H.shift(H.now(), seconds=-2 * 3600)
        c.execute("UPDATE runners SET checkout_json=? WHERE id=?", (json.dumps(checkout), r["runner_id"]))
    # One plain line, whether anything would be interrupted, and a Restart button.
    behind = beat(behind=6)
    assert len(behind) == 1 and behind[0]["title"].endswith("has a Tico update")
    assert behind[0]["detail"] == "Nothing is running, so nothing will be interrupted." and behind[0]["restart"] is True
    stale = beat(running=running)
    assert stale[0]["title"].endswith("has a Tico update") and stale[0]["restart"] is True

    # Restart: the next heartbeat hands the request to the runner once and clears it.
    requested = post(api, f"runners/{r['runner_id']}/restart", {})
    assert requested == {"requested": True, "running": 0}
    shown = [i for i in get(api, "operations")["issues"] if i.get("kind") == "runner_checkout"]
    assert shown[0]["detail"].startswith("Restarting now") and shown[0]["restart"] is False
    first = post(api, "runners/heartbeat", {"version": "test", "platform": "test", "readiness": {}}, token=r["token"])
    again = post(api, "runners/heartbeat", {"version": "test", "platform": "test", "readiness": {}}, token=r["token"])
    assert first.get("restart") is True and "restart" not in again


def test_a_runner_that_cannot_update_itself_says_why(api):
    """BotOps, 2026-09-25: the runner sat 87 commits behind because uncommitted changes blocked its
    self-update, and only its log said so. The reason reaches the owner at once."""
    from backend.tests.test_api import runner as enroll
    r = enroll(api)
    post(api, "runners/heartbeat", {"version": "test", "platform": "test", "readiness": {},
         "checkout": {"head": "a" * 40, "running": "a" * 40, "ahead": 0, "behind": 12,
                      "checked_at": "2026-09-25T18:00:00Z", "blocked": "checkout has uncommitted changes"}},
         token=r["token"])
    issues = [i for i in get(api, "operations")["issues"] if i.get("kind") == "runner_checkout"]
    assert len(issues) == 1 and issues[0]["title"].endswith("can't update itself")
    assert "12 commits behind main: checkout has uncommitted changes" in issues[0]["detail"]
    assert "commit or stash" in issues[0]["action"]
