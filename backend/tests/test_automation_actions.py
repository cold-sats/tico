"""Each action's executor in the hub (backend/automation_actions.py), reusing what the hub has: tasks, tags, wakes,
updates, outgoing webhooks, the mail action queue and the Slack outbox. A refusal is an answer, never a raise."""
import json

from backend import automation_actions as A
from backend.store import H
from backend.tests.test_api import api, post  # noqa: F401
from backend.tests.test_automation_api import turn_on

MAIL = {"message": {"source": "mail", "mailbox": "ana@acme.example", "id": "m1", "subject": "Invoice"}}
SLACK = {"message": {"source": "slack", "inbox": "slack:#general", "channel": "C1", "ts": "1.1", "text": "Help?"}}


def auto(owner="person:ana"):
    return {"id": "auto_t", "flow": {"name": "Test", "owner": owner, "trigger": {"type": "event", "name": "x.y"}},
            "assistant_bot": "coo"}


def act(api, do, args=None, values=None, owner="person:ana"):
    with api.app.state.store.transaction() as c:
        return A.run(c, auto(owner), "run_1", do, args or {}, values or {})


def task(api, title="Check the deploy"):
    made = post(api, "tasks", {"owner": "ops", "title": title, "body": "Please."})
    return {"task": {"id": made["id"], "title": title}}


def sql(api, query, args=()):
    with api.app.state.store.read() as c:
        return [dict(r) for r in c.execute(query, args)]


def test_create_task_files_it_from_the_owner(api):
    turn_on(api)
    done = act(api, "create_task", {"title": "Follow up", "owner": "coo"})
    row = sql(api, "SELECT owner, requester FROM tasks WHERE id=?", (done["task"],))[0]
    assert done["ok"] and row == {"owner": "bot:coo", "requester": "human:ana"}
    assert act(api, "create_task", {}) == {"ok": False, "detail": "create_task needs a title"}


def test_label_note_and_assign_work_on_the_runs_task(api):
    turn_on(api)
    values = task(api)
    assert act(api, "label", {"tag": "billing"}, values)["detail"] == "labelled"
    assert act(api, "label", {"tag": "billing"}, values)["detail"] == "already labelled"
    assert act(api, "note", {"text": "Seen by the automation"}, values)["ok"]
    assert act(api, "assign", {"owner": "coo"}, values)["ok"]
    assert sql(api, "SELECT owner FROM tasks WHERE id=?", (values["task"]["id"],))[0]["owner"] == "bot:coo"
    assert not act(api, "assign", {}, values)["ok"] and not act(api, "note", {})["ok"]


def test_wake_bot_wakes_it_with_the_run_on_the_notice(api):
    turn_on(api)
    assert act(api, "wake_bot", {"bot": "ops", "text": "Look"})["ok"]
    woke = sql(api, "SELECT body, refs_json FROM messages WHERE to_actor='bot:ops' ORDER BY created DESC")[0]
    assert woke["body"] == "Look" and json.loads(woke["refs_json"])["automation_run"] == "run_1"
    assert not act(api, "wake_bot", {"bot": "nobody"})["ok"]


def test_post_update_posts_as_the_owner(api):
    turn_on(api)
    assert act(api, "post_update", {"text": "Shipped the fix"}, owner="bot:ops")["ok"]
    assert act(api, "post_update", {}) == {"ok": False, "detail": "post_update needs text"}


def test_call_webhook_queues_a_delivery_to_a_saved_hook_only(api):
    turn_on(api)
    hook = post(api, "webhooks", {"name": "crm", "url": "https://hooks.acme.example/crm", "events": ["custom.*"]})
    done = act(api, "call_webhook", {"webhook": hook["webhook"]["id"], "data": {"lead": "Acme"}})
    assert done["ok"], done
    assert not act(api, "call_webhook", {"webhook": "wh_nope"})["ok"]


def test_mail_actions_queue_for_the_mailboxs_computer(api):
    turn_on(api)
    for do in ("archive", "leave_for_you", "draft_reply", "forward", "label"):
        assert act(api, do, {"tag": "x"}, MAIL)["ok"]
    queued = [r["action"] for r in sql(api, "SELECT action FROM automation_mail_actions ORDER BY created")]
    assert queued == ["archive", "leave", "draft", "forward", "label"]
    assert act(api, "archive") == {"ok": False, "detail": "archive needs a message"}


def test_slack_send_reply_posts_in_the_thread_and_off_leaves_a_draft_task(api):
    turn_on(api)
    assert act(api, "send_reply", {"body": "On it", "bot": "ops"}, SLACK)["detail"] == "posted"
    post_row = sql(api, "SELECT channel, thread_ts, bot, text FROM slack_posts")[0]
    assert post_row == {"channel": "C1", "thread_ts": "1.1", "bot": "ops", "text": "On it"}
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO automation_inboxes VALUES('slack:#general',0,?,'human:ana')", (H.now(),))
    drafted = act(api, "send_reply", {"body": "On it", "bot": "ops"}, SLACK)
    assert drafted["ok"] and drafted["task"] and len(sql(api, "SELECT 1 FROM slack_posts")) == 1


def test_an_unknown_action_is_refused(api):
    turn_on(api)
    assert not act(api, "explode")["ok"]
