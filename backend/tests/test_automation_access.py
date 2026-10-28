"""What an automation may read and as whom it acts (backend/automations.py `may_read_inbox`, backend/automation_actions.py
`acts_as`): only its owner's own mail and Slack, checked on save and again when a message arrives; `find: mail` in
the owner's mailboxes only; a manual run's input only what the owner may read; its writes as its owner, with
`via: automation:<id>`; an Assistant turn only on the owner's own Assistant."""
import json
from types import SimpleNamespace

from backend import automations
from backend.tests.test_api import api, get, post  # noqa: F401
from backend.tests.test_automation_api import turn_on

WAKE = {"id": "tell", "type": "action", "do": "wake_bot", "args": {"bot": "ops", "text": "{{message.subject}}"}}


def flow(owner="person:ana", trigger=None, steps=(WAKE,)):
    return {"name": "Test", "owner": owner, "trigger": trigger or {"type": "event", "name": "x.y"}, "steps": list(steps)}


def mail(msg_id="m1"):
    return SimpleNamespace(msg_id=msg_id, thread_id="t1", from_addr="billing@acme.example", to=["ana@acme.example"],
                           subject="Invoice", snippet="Please pay", body="Please pay.", labels=["INBOX"], list_id=None,
                           is_internal=False, date="2026-10-28T09:00:00Z")


def runs(api, aid):
    return get(api, f"automations/{aid}/runs")


def test_a_mail_trigger_is_its_owners_own_mailbox_on_save(api):
    turn_on(api)
    on_ben = {"type": "message", "inbox": "ben@acme.example"}
    refused = post(api, "automations", flow(trigger=on_ben), expected=403)
    assert "may not read ben@acme.example" in refused["error"]["detail"]
    post(api, "automations", flow(owner="person:ben", trigger=on_ben), token="ben-test")
    # A bot hears its operator's mail: ops is Ana's.
    post(api, "automations", flow(owner="bot:ops", trigger={"type": "message", "inbox": "ana@acme.example"}))
    post(api, "automations", flow(owner="bot:cpo", trigger={"type": "message", "inbox": "ana@acme.example"}),
         expected=403)


def test_a_mail_trigger_is_checked_again_when_mail_arrives(api):
    turn_on(api)
    aid = post(api, "automations", flow(trigger={"type": "message", "inbox": "ana@acme.example"}))["id"]
    with api.app.state.store.transaction() as c:   # the owner changed since the save (a hand edit, an import)
        c.execute("UPDATE automations SET owner='person:ben', flow_json=json_set(flow_json,'$.owner','person:ben') "
                  "WHERE id=?", (aid,))
        assert automations.on_mail(c, "ana@acme.example", mail()) == []
    assert runs(api, aid)["runs"] == [] and runs(api, aid)["daily"][0]["dropped"] == 1


def test_slack_dm_is_the_owners_own_and_a_channel_must_be_one_the_owner_reads(api):
    turn_on(api)
    dm = post(api, "automations", flow(trigger={"type": "message", "inbox": "slack:dm"}))["id"]
    post(api, "automations", flow(trigger={"type": "message", "inbox": "slack:#secret"}), expected=403)
    with api.app.state.store.transaction() as c:
        bens = automations.on_slack(c, {"channel": "D2", "ts": "1.1", "text": "hi"}, {"id": "ben"}, {"kind": "im"})
        anas = automations.on_slack(c, {"channel": "D1", "ts": "1.2", "text": "hi"}, {"id": "ana"}, {"kind": "im"})
    assert bens == [] and len(anas) == 1
    assert runs(api, dm)["daily"][0]["dropped"] == 1


def test_find_mail_reads_only_the_owners_mailboxes(api):
    turn_on(api)
    with api.app.state.store.transaction() as c:
        for box, mid in (("ana@acme.example", "a1"), ("ben@acme.example", "b1")):
            c.execute("INSERT INTO mail_messages(mailbox,msg_id,epoch,date,from_addr,to_json,cc_json,subject,snippet,"
                      "labels_json,body,attachments_json,updated) VALUES(?,?,0,'',?,'[]','[]','Invoice','',"
                      "'[]','','[]',?)", (box, mid, "billing@acme.example", "2026-10-28T09:00:00Z"))
    find = {"id": "look", "type": "find", "source": "mail", "query": "Invoice", "limit": 10}
    aid = post(api, "automations", flow(steps=[find]))["id"]
    run = post(api, f"automations/{aid}/run", {})["run"]
    assert run["steps"][0]["outputs"] == {"count": 1}


def test_a_manual_runs_input_names_only_what_the_owner_may_read(api):
    turn_on(api)
    secret = post(api, "tasks", {"owner": "cpo", "title": "Ben's secret", "body": "x", "private": True},
                  token="ben-test")
    aid = post(api, "automations", flow(owner="bot:ops", steps=[
        {"id": "n", "type": "action", "do": "note", "args": {"text": "Seen"}}]))["id"]
    refused = post(api, f"automations/{aid}/run", {"input": {"task": {"id": secret["id"]}}}, expected=403)
    assert refused["error"]["code"] == "forbidden" and runs(api, aid)["runs"] == []
    post(api, f"automations/{aid}/run", {"input": {"message": {"mailbox": "ben@acme.example", "id": "m1"}}},
         expected=403)


def test_task_actions_act_as_the_owner_with_the_automation_as_via(api):
    turn_on(api)
    made = post(api, "tasks", {"owner": "ops", "title": "Check the deploy", "body": "Please."})
    aid = post(api, "automations", flow(steps=[
        {"id": "n", "type": "action", "do": "note", "args": {"text": "Seen by the automation"}}]))["id"]
    run = post(api, f"automations/{aid}/run", {"input": {"task": {"id": made["id"]}}})["run"]
    assert run["status"] == "ok", run
    with api.app.state.store.read() as c:
        row = c.execute("SELECT actor, via FROM task_events WHERE task_id=? AND note='Seen by the automation'",
                        (made["id"],)).fetchone()
    assert dict(row) == {"actor": "human:ana", "via": f"automation:{aid}"}


def test_an_assistant_turn_is_only_on_the_owners_own_assistant(api):
    turn_on(api)
    step = {"id": "brief", "type": "llm", "as": "assistant:ben", "prompt": "Brief me", "out": "b"}
    refused = post(api, "automations", flow(steps=[step]), expected=403)
    assert "Only ben's own automation" in refused["error"]["detail"]
    nested = {"id": "p", "type": "paths", "paths": [{"name": "a", "when": [], "steps": [step]}]}
    post(api, "automations", flow(steps=[nested]), expected=403)
    post(api, "automations", flow(owner="person:ben", steps=[step]), token="ben-test")


def test_mail_payload_carries_what_the_connector_has(api):
    turn_on(api)
    aid = post(api, "automations", flow(trigger={"type": "message", "inbox": "ana@acme.example"}))["id"]
    message = mail()
    message.cc, message.from_header, message.has_unsubscribe = ["cara@acme.example"], "Acme Billing", True
    message.attachments = [{"name": "invoice.pdf"}]
    with api.app.state.store.transaction() as c:
        rid = automations.on_mail(c, "ana@acme.example", message)[0]
        state = json.loads(c.execute("SELECT state_json FROM automation_runs WHERE id=?", (rid,)).fetchone()[0])
    got = state["payload"]["message"]
    assert (got["cc"], got["from_name"], got["unsubscribe"], got["attachments"]) == (
        ["cara@acme.example"], "Acme Billing", True, ["invoice.pdf"])
    assert runs(api, aid)
