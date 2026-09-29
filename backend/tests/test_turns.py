"""What a turn did, under its reply (#524): the run summary on the reply and its steps on demand."""

from backend.store import H
from backend.tests.test_api import api, get, post, setup_attempt  # noqa: F401


def run_turn(api):
    """Ana asks Ops; the turn thinks, calls a tool, hands Finance a task, is refused once, answers."""
    r, msg, attempt = setup_attempt(api)
    aid, token = attempt["id"], attempt["token"]
    post(api, f"attempts/{aid}/started", {"thread_id": "t1"}, token=r["token"])
    task = post(api, "tasks", {"owner": "finance", "title": "Check the September invoices",
                               "body": "Compare them with the ledger."}, token=token)
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO refusals(id,ts,actor,rule,detail_json,severity) VALUES(?,?,?,?,?,?)",
                  (H.new_id(), H.now(), "bot:ops", "identity", '{"detail": "Bots cannot message a person directly"}', "normal"))
    events = [("delta", {"text": "Look at the ", "delta_kind": "thought"}), ("delta", {"text": "ledger first.", "delta_kind": "thought"}),
              ("tool", {"tool": "Bash", "status": "started", "item_id": "call-1", "input": {"env": "SECRET=x" * 500}}),
              ("tool", {"tool": "Bash", "status": "completed", "item_id": "call-1"}),
              ("message", {"text": "Handing the invoices to Finance.", "final": False}),
              ("delta", {"text": "Done", "delta_kind": "text"}), ("tokens", {"input": 10, "output": 5}),
              ("message", {"text": "Done: Finance has it.", "final": False}),
              ("message", {"text": "Done: Finance has it.", "final": True})]
    post(api, f"attempts/{aid}/events", {"events": [{"seq": i + 1, "kind": k, "payload": p} for i, (k, p) in enumerate(events)]},
         token=r["token"])
    post(api, f"attempts/{aid}/complete", {"outcome": "completed", "text": "Done: Finance has it.", "last_seq": len(events)},
         token=r["token"])
    return msg, aid, task


def test_a_reply_says_what_its_turn_did_in_titles_and_names(api):
    msg, aid, task = run_turn(api)
    snap = get(api, f"conversations/{msg['conversation_id']}/snapshot")
    reply = next(m for m in snap["messages"] if m["from_actor"] == "bot:ops")
    assert reply["refs"]["turn_id"] == aid
    run = reply["run"]
    assert [(d["kind"], d.get("title") or d.get("text"), d.get("owner")) for d in run["did"]] == [
        ("task", "Check the September invoices", "bot:finance"),
        ("refused", "Bots cannot message a person directly", None)]
    assert run["did"][0]["task_id"] == task["id"]
    assert (run["steps"], run["tool_calls"]) == (3, 1) and run["took_s"] is not None
    # The older-messages page carries the same summary.
    assert next(m for m in get(api, f"conversations/{msg['conversation_id']}/messages") if m["id"] == reply["id"])["run"] == run
    # A message that refers to a task carries its title, so no id is ever shown.
    about = post(api, "chat/ops", {"text": "How is this going?", "refs": {"task": task["id"]}})
    shown = next(m for m in get(api, f"conversations/{msg['conversation_id']}/snapshot")["messages"] if m["id"] == about["id"])
    assert {k: {f: v for f, v in row.items() if f != "owner_name"} for k, row in shown["ref_tasks"].items()} == {
            task["id"]: {"title": "Check the September invoices", "owner": "bot:finance", "status": "open"}}


def test_steps_are_one_short_line_each_and_only_for_readers_of_the_room(api):
    msg, aid, _ = run_turn(api)
    steps = get(api, f"turns/{aid}/steps")
    assert steps["turn_id"] == aid and steps["tool_calls"] == 1
    assert [(s["kind"], s["tool"], s["text"]) for s in steps["steps"]] == [
        ("thinking", "", "Look at the ledger first."), ("tool", "Bash", ""), ("said", "", "Handing the invoices to Finance.")]
    assert set(steps["steps"][1]) == {"kind", "tool", "text", "at"}, "no raw tool input travels"
    # Ana's room is personal: Ben cannot read it, so he cannot read its turns either.
    get(api, f"conversations/{msg['conversation_id']}/snapshot", "ben-test", expected=403)
    get(api, f"turns/{aid}/steps", "ben-test", expected=403)
    get(api, "turns/nope/steps", expected=404)
