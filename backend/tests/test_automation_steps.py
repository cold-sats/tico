"""Each step type in the executor (backend/automation_engine.py) with fake services: filter, decide, llm, find,
bot_turn and action; on/off per step, the spend cap, batch times, and how a run's status comes out."""
from backend import automation_engine as E
from backend.tests.automation_fakes import Services

MESSAGE = {"message": {"from": "news@acme.example", "subject": "Weekly digest"}}


def flow(*steps, **extra):
    return {"name": "Test", "owner": "person:ana", "trigger": {"type": "message", "inbox": "ana@acme.example"},
            "steps": list(steps), **extra}


def note(sid, text="hi", **extra):
    return {"id": sid, "type": "action", "do": "note", "args": {"text": text}, **extra}


def statuses(run):
    return [(r["id"], r["status"]) for r in run["steps"]]


# ---------------------------------------------------------------------------------------------- filter
FROM_NEWS = [{"field": "message.from", "op": "contains", "value": "news@"}]


def test_filter_runs_the_first_matching_rule_and_its_actions():
    services = Services()
    gate = {"id": "gate", "type": "filter", "rules": [
        {"when": [{"field": "message.from", "op": "is", "value": "ceo@acme.example"}], "then": [{"do": "label"}]},
        {"when": FROM_NEWS, "then": [{"do": "archive", "args": {"why": "{{message.subject}}"}}, {"do": "label"}]},
        {"when": [], "then": [{"do": "forward"}]}]}
    run = E.execute(flow(gate, note("after")), MESSAGE, services)
    assert run["steps"][0]["outputs"]["rule"] == 1
    assert services.acted == [("archive", {"why": "Weekly digest"}), ("label", {}), ("note", {"text": "hi"})]
    assert run["status"] == "ok"


def test_filter_stop_ends_the_run_there():
    services = Services()
    gate = {"id": "gate", "type": "filter", "rules": [{"when": FROM_NEWS, "then": [{"do": "archive"}], "stop": True}]}
    run = E.execute(flow(gate, note("after")), MESSAGE, services)
    assert statuses(run) == [("gate", "ok")] and services.acted == [("archive", {})]


def test_filter_with_no_match_goes_on():
    gate = {"id": "gate", "type": "filter", "rules": [
        {"when": [{"field": "message.from", "op": "is", "value": "x"}], "then": [{"do": "archive"}]}]}
    run = E.execute(flow(gate, note("after")), MESSAGE, Services())
    assert run["steps"][0]["outputs"] == {"rule": None, "actions": []} and statuses(run)[-1] == ("after", "ok")


def test_filter_any_matches_on_one_condition():
    gate = {"id": "gate", "type": "filter", "rules": [
        {"when": [{"field": "message.from", "op": "is", "value": "x"}] + FROM_NEWS, "match": "any", "stop": True}]}
    assert statuses(E.execute(flow(gate, note("after")), MESSAGE, Services())) == [("gate", "ok")]


def test_a_filter_action_that_fails_fails_the_run():
    gate = {"id": "gate", "type": "filter", "rules": [{"when": [], "then": [{"do": "archive"}]}]}
    run = E.execute(flow(gate, note("after")), MESSAGE, Services(fail={"archive"}))
    assert statuses(run) == [("gate", "failed")] and run["status"] == "failed"


# ---------------------------------------------------------------------------------------------- decide
def test_decide_asks_once_and_keeps_answers_under_out():
    services = Services()
    questions = {"bucket": {"type": "choice", "instructions": "x", "criteria": {"reply": "", "archive": ""}}}
    decide = {"id": "triage", "type": "decide", "questions": questions, "level": "high", "out": "d1"}
    gate = {"id": "after", "type": "filter",
            "rules": [{"when": [{"field": "d1.bucket", "op": "is", "value": "reply", "min": 0.7}], "then": [{"do": "label"}]}]}
    run = E.execute(flow(decide, gate), MESSAGE, services)
    assert len(services.judged) == 1
    asked = services.judged[0]
    assert asked["questions"] == questions and asked["level"] == "high" and asked["label"] == "automation.triage"
    assert asked["values"]["message"]["subject"] == "Weekly digest"
    assert run["steps"][0]["outputs"]["bucket"]["choice"] == "reply"
    assert run["steps"][0]["cost"] == 0.01 and run["cost"] == 0.01
    assert services.acted == [("label", {})]


def test_decide_reads_a_question_set():
    services = Services()
    E.execute(flow({"id": "d", "type": "decide", "set": "mail-triage@1", "out": "d1"}), MESSAGE, services)
    assert services.judged[0]["questions"] == {"set": {"type": "noul", "instructions": "mail-triage@1"}}


def test_a_judge_failure_fails_the_step_and_the_run():
    run = E.execute(flow({"id": "d", "type": "decide", "set": "x", "out": "d1"}, note("after")), MESSAGE,
                    Services(fail={"judge"}))
    assert statuses(run) == [("d", "failed")] and run["status"] == "failed"
    assert "the judge is down" in run["steps"][0]["outputs"]["error"]


# ---------------------------------------------------------------------------------------------- llm and bot_turn
def test_llm_with_steps_after_it_waits_for_the_turn_then_goes_on():
    services = Services()
    llm = {"id": "draft", "type": "llm", "as": "assistant:ana", "prompt": "Draft: {{message.subject}}", "out": "reply"}
    send = {"id": "send", "type": "action", "do": "send_reply", "args": {"body": "{{reply.text}}"}}
    f = flow(llm, send)
    run = E.execute(f, MESSAGE, services)
    assert run["status"] == "waiting" and statuses(run) == [("draft", "waiting")]
    assert services.turns == [{"who": "assistant:ana", "prompt": "Draft: Weekly digest", "wait": True}]
    assert E.answer(run, "msg_1", "Thanks, noted.", cost=0.05)
    assert not E.answer(run, "msg_1", "again")         # one answer per turn
    run = E.advance(f, run, services)
    assert run["status"] == "ok" and statuses(run) == [("draft", "ok"), ("send", "ok")]
    assert services.acted == [("send_reply", {"body": "Thanks, noted."})]
    assert run["cost"] == 0.05


def test_llm_as_the_last_step_does_not_wait():
    run = E.execute(flow({"id": "x", "type": "llm", "as": "bot:coo", "prompt": "p", "out": "o"}), MESSAGE, Services())
    assert run["status"] == "ok" and run["steps"][0]["outputs"] == {"ref": "msg_1"}


def test_bot_turn_starts_a_turn_on_the_bot_and_goes_on():
    services = Services()
    run = E.execute(flow({"id": "t", "type": "bot_turn", "bot": "coo", "prompt": "Look at {{message.from}}"},
                         note("after")), MESSAGE, services)
    assert services.turns == [{"who": "bot:coo", "prompt": "Look at news@acme.example", "wait": False}]
    assert statuses(run) == [("t", "ok"), ("after", "ok")]


def test_a_turn_that_cannot_start_fails_the_run():
    run = E.execute(flow({"id": "t", "type": "bot_turn", "bot": "gone", "prompt": "p"}), MESSAGE, Services(fail={"turn"}))
    assert run["status"] == "failed"


def test_the_spend_cap_stops_turns_but_not_filter_or_decide():
    services = Services(spent=1.99)
    f = flow({"id": "d", "type": "decide", "set": "x", "out": "d1"},
             {"id": "t", "type": "bot_turn", "bot": "coo", "prompt": "p"}, note("after"), spend_cap={"per_30m": 2})
    run = E.execute(f, MESSAGE, services)
    assert statuses(run) == [("d", "ok"), ("t", "spend_cap")]
    assert services.turns == [] and len(services.judged) == 1 and run["status"] == "ok"


def test_under_the_spend_cap_turns_run():
    services = Services(spent=0.5)
    run = E.execute(flow({"id": "t", "type": "bot_turn", "bot": "coo", "prompt": "p"}, spend_cap={"per_30m": 2}),
                    MESSAGE, services)
    assert statuses(run) == [("t", "ok")]


# ---------------------------------------------------------------------------------------------- find
def test_find_runs_the_rest_once_per_item():
    services = Services(items=[{"subject": "a"}, {"subject": "b"}, {"subject": "c"}])
    f = flow({"id": "f", "type": "find", "source": "mail", "query": "from:{{message.from}}", "limit": 2},
             note("each", "{{item.subject}}"))
    run = E.execute(f, MESSAGE, services)
    assert services.found == [("mail", "from:news@acme.example", 2)]
    assert services.acted == [("note", {"text": "a"}), ("note", {"text": "b"})]
    assert [r.get("item") for r in run["steps"]] == [None, 0, 1] and run["status"] == "ok"


def test_find_with_nothing_is_an_empty_run():
    run = E.execute(flow({"id": "f", "type": "find", "source": "tasks"}, note("each")), {}, Services())
    assert run["status"] == "empty" and statuses(run) == [("f", "ok")]


def test_one_item_failing_fails_the_run_but_the_others_run():
    services = Services(items=[{"do": "note"}, {"do": "label"}])
    f = flow({"id": "f", "type": "find", "source": "tasks"},
             {"id": "a", "type": "action", "do": "label", "args": {}, "enabled": True})
    services.fail = {"label"}
    run = E.execute(f, {}, services)
    assert run["status"] == "failed" and len(services.acted) == 2


# ---------------------------------------------------------------------------------------------- on/off and status
def test_a_step_turned_off_is_skipped():
    services = Services()
    run = E.execute(flow(note("off", enabled=False), note("on")), MESSAGE, services)
    assert statuses(run) == [("off", "skipped"), ("on", "ok")] and services.acted == [("note", {"text": "hi"})]


def test_every_step_off_is_a_skipped_run():
    run = E.execute(flow(note("a", enabled=False)), MESSAGE, Services())
    assert run["status"] == "skipped"


def test_an_action_that_fails_stops_its_thread():
    services = Services(fail={"note"})
    run = E.execute(flow(note("a"), {"id": "b", "type": "action", "do": "label"}), MESSAGE, services)
    assert statuses(run) == [("a", "failed")] and run["status"] == "failed"


def test_action_output_is_readable_by_later_steps():
    services = Services()
    run = E.execute(flow(note("a"), note("b", "{{a.detail}}")), MESSAGE, services)
    assert services.acted[-1] == ("note", {"text": "note done"}) and run["status"] == "ok"


# ---------------------------------------------------------------------------------------------- batch times
def test_batch_runs_filters_on_receipt_and_the_rest_at_the_batch_time():
    services = Services()
    gate = {"id": "gate", "type": "filter", "rules": [{"when": [], "then": [{"do": "label"}]}]}
    f = flow(gate, note("later"), batch={"times": ["13:00"]})
    run = E.execute(f, MESSAGE, services)
    assert run["status"] == "waiting" and statuses(run) == [("gate", "ok")]
    assert run["threads"][0]["wait"] == {"kind": "batch", "until": "2026-10-28T13:00:00Z"}
    E.advance(f, run, services)                         # not yet
    assert run["status"] == "waiting"
    services.clock = "2026-10-28T13:00:01Z"
    E.advance(f, run, services)
    assert run["status"] == "ok" and statuses(run) == [("gate", "ok"), ("later", "ok")]


def test_a_manual_run_ignores_batch_times():
    run = E.execute(flow(note("now"), batch={"times": ["13:00"]}), {}, Services(), manual=True)
    assert run["status"] == "ok"


def test_a_filter_stop_before_the_batch_never_waits():
    gate = {"id": "gate", "type": "filter", "rules": [{"when": [], "stop": True}]}
    run = E.execute(flow(gate, note("later"), batch={"times": ["13:00"]}), MESSAGE, Services())
    assert run["status"] == "ok"


def test_a_turn_that_fails_fails_the_run():
    services = Services()
    f = flow({"id": "x", "type": "llm", "as": "bot:coo", "prompt": "p", "out": "o"}, note("after"))
    run = E.execute(f, MESSAGE, services)
    assert E.answer(run, "msg_1", "interrupted", ok=False)
    E.advance(f, run, services)
    assert run["status"] == "failed" and statuses(run) == [("x", "failed")] and services.acted == []
