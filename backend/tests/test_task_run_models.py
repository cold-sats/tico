"""A task's own model (backend/task_run_models.py): one task runs on the model set on it while the bot's other
tasks keep theirs, a check subtask keeps its check model over it, a model that cannot run falls back and says so,
whoever may change the bot's model may set a task's and a bot never does, change and clear are in the task's
history, and a routine's Bot turn step stamps its model on the task its run opens."""
from backend.tests.test_api import api, claim, get, headers, post  # noqa: F401  (api is a fixture)
from backend.tests.test_check_models import finish, heartbeat
from backend.tests.test_task_models import ops_on_sonnet, task_turn

HAIKU = {"model": "claude-haiku-5-5", "effort": "low", "harness": "claude"}
HAIKU_RAN = {"model": "claude-haiku-5-5", "runtime": "claude", "harness": "claude", "effort": "low", "billing": "api"}
SONNET_RAN = {"model": "claude-sonnet-5-5", "runtime": "claude", "harness": "claude", "effort": "high",
              "billing": "api"}
GROK = {"model": "grok-4.6", "effort": "low", "harness": "grok"}


def filed(api, title, owner="ops"):
    return post(api, "tasks", {"owner": owner, "title": title, "body": "Do the work."})


def own_model(api, task_id, body, token="ana-test", expected=200):
    return post(api, f"tasks/{task_id}/model", body, token=token, expected=expected)


def test_a_task_runs_on_its_own_model_and_the_bots_other_tasks_keep_theirs(api):
    machine = ops_on_sonnet(api)
    mine = filed(api, "Tidy the changelog")
    own_model(api, mine["id"], HAIKU)
    turn = claim(api, machine)
    assert turn["task"]["id"] == mine["id"]
    assert (turn["config"]["model"], turn["config"]["reasoning_effort"]) == ("claude-haiku-5-5", "low")
    finish(api, machine, turn, HAIKU_RAN)
    ran = get(api, "tasks/" + mine["id"])["runs"][0]["ran_on"]
    assert ran["segments"][0]["model"] == "claude-haiku-5-5"
    assert ran["task_model"]["source"] == "task"
    # Only this task changed: the bot's task model is still unset, and its next task runs on its own model.
    assert get(api, "bots/ops")["task_model"] is None
    _, other = task_turn(api, machine, "Tidy the README")
    assert other["config"]["model"] == "claude-sonnet-5-5"


def test_a_tasks_own_model_that_cannot_run_falls_back_to_the_bots_model_and_says_so(api):
    machine = ops_on_sonnet(api)
    mine = filed(api, "Index the docs")
    own_model(api, mine["id"], GROK)
    heartbeat(api, machine, grok="missing")
    turn = claim(api, machine)
    assert turn is not None, "never held for the task's own model"
    assert turn["config"]["model"] == "claude-sonnet-5-5"
    finish(api, machine, turn, SONNET_RAN)
    ran = get(api, "tasks/" + mine["id"])["runs"][0]["ran_on"]
    assert ran["segments"][0]["model"] == "claude-sonnet-5-5"
    assert ran["task_model"]["source"] == "fallback"
    assert "grok-4.6" in ran["task_model"]["note"] and "could not run" in ran["task_model"]["note"]


def test_a_check_subtask_keeps_its_check_model_over_the_tasks_own_model(api):
    machine = ops_on_sonnet(api)
    parent = filed(api, "Ship the import fix")
    own_model(api, parent["id"], HAIKU)
    turn = claim(api, machine)
    assert turn["config"]["model"] == "claude-haiku-5-5"
    sub = post(api, "tasks", {"owner": "ops", "title": "Review PR 700 with another model", "body": "Read it.",
                              "check_model": "grok", "check_role": "review",
                              "relations": [{"task": parent["id"], "kind": "parent"}]}, turn["token"])
    own_model(api, sub["id"], HAIKU)
    finish(api, machine, turn, HAIKU_RAN)
    check = claim(api, machine)
    assert check["task"]["id"] == sub["id"]
    assert (check["config"]["runtime"], check["config"]["model"]) == ("grok", "grok-4.6")
    finish(api, machine, check, {"model": "grok-4.6", "runtime": "grok", "harness": "grok", "effort": "high"})
    ran = get(api, "tasks/" + sub["id"])["runs"][0]["ran_on"]
    assert ran["segments"][0]["model"] == "grok-4.6" and ran["task_model"]["source"] == "check"


def test_only_whoever_may_change_the_bots_model_may_set_a_tasks_and_a_bot_never_does(api):
    machine = ops_on_sonnet(api)
    mine = filed(api, "Tidy the changelog")
    own_model(api, mine["id"], HAIKU, token="cara-test", expected=403)
    turn = claim(api, machine)
    own_model(api, mine["id"], HAIKU, token=turn["token"], expected=403)
    assert get(api, "tasks/" + mine["id"])["run_model"] is None
    own_model(api, mine["id"], HAIKU, token="ben-test")
    assert get(api, "tasks/" + mine["id"])["run_model"]["model"] == "claude-haiku-5-5"


def test_a_tasks_model_changes_and_clears_and_its_history_says_so(api):
    ops_on_sonnet(api)
    mine = filed(api, "Tidy the changelog")
    assert get(api, "tasks/" + mine["id"])["run_model"] is None
    first = own_model(api, mine["id"], HAIKU)
    assert first["run_model"]["model"] == "claude-haiku-5-5" and first["run_model"]["reasoning_effort"] == "low"
    assert get(api, "tasks/" + mine["id"])["run_model"]["harness"] == "claude"
    own_model(api, mine["id"], HAIKU, expected=409)
    cleared = own_model(api, mine["id"], {"model": None})
    assert cleared["run_model"] is None and get(api, "tasks/" + mine["id"])["run_model"] is None
    assert get(api, "bots/ops")["task_model"] is None
    with api.app.state.store.read() as c:
        events = c.execute("SELECT old,new FROM task_events WHERE task_id=? AND field='run_model' ORDER BY rowid",
                           (mine["id"],)).fetchall()
    assert [tuple(e) for e in events] == [("", "claude-haiku-5-5 (low)"), ("claude-haiku-5-5 (low)", "")]


def test_a_model_must_be_a_supported_one_taking_the_effort_and_only_a_bots_task_has_one(api):
    ops_on_sonnet(api)
    mine = filed(api, "Tidy the changelog")
    own_model(api, mine["id"], {"model": "no-such-model"}, expected=422)
    own_model(api, mine["id"], {"model": "claude-haiku-5-5", "effort": "extreme"}, expected=422)
    person = post(api, "tasks", {"owner": "ana", "title": "Call the vendor", "body": "Ring them back."})
    own_model(api, person["id"], HAIKU, expected=422)


def test_a_routine_step_stamps_its_model_on_the_task_its_run_opens(api):
    machine = ops_on_sonnet(api)
    trigger = {"type": "event", "name": "x.y"}
    step = {"id": "audit", "type": "bot_turn", "bot": "ops", "prompt": "Run the audit.", **HAIKU}
    post(api, "automations", {"name": "Haiku audit", "owner": "bot:ops", "trigger": trigger,
                              "steps": [{**step, "effort": "extreme"}]}, expected=422)
    aid = post(api, "automations", {"name": "Haiku audit", "owner": "bot:ops", "trigger": trigger,
                                    "steps": [step]})["id"]
    post(api, f"automations/{aid}/run", {})
    turn = claim(api, machine)
    task_id = turn["task"]["id"]
    assert (turn["config"]["model"], turn["config"]["reasoning_effort"]) == ("claude-haiku-5-5", "low")
    finish(api, machine, turn, HAIKU_RAN)
    assert get(api, "tasks/" + task_id)["run_model"]["model"] == "claude-haiku-5-5"
    with api.app.state.store.read() as c:
        notes = c.execute("SELECT note FROM task_events WHERE task_id=? AND field='run_model'", (task_id,)).fetchall()
    assert [n[0] for n in notes] == ["Set by routine step audit"]
    assert get(api, "bots/ops")["task_model"] is None


def test_a_routine_step_model_from_someone_who_may_not_set_it_waits_for_a_person_who_may(api):
    ops_on_sonnet(api)
    step = {"id": "audit", "type": "bot_turn", "bot": "ops", "prompt": "Run the audit.", **HAIKU}
    flow = {"name": "Haiku audit", "owner": "human:cara", "trigger": {"type": "event", "name": "x.y"}, "steps": [step]}
    # Cara may make her own routine but not choose ops' model: it is saved off, its first version pending.
    draft = post(api, "automations", flow, token="cara-test")
    assert draft["pending"] == 1
    # Turning on her own draft would set the model all the same, so she may not; Ana, who manages ops, may.
    post(api, f"automations/{draft['id']}/versions/1/restore", {}, token="cara-test", expected=403)
    assert get(api, f"automations/{draft['id']}")["enabled"] is False
    on = post(api, f"automations/{draft['id']}/versions/1/restore", {})
    assert on["enabled"] is True
    # A later edit of hers that changes the step's model is proposed, never saved over the live one.
    changed = {"steps": [{**step, "effort": "high"}]}
    proposed = api.patch(f"/api/v2/automations/{draft['id']}", json=changed, headers=headers("cara-test"))
    assert proposed.status_code == 200 and proposed.json()["pending"], proposed.text
    assert get(api, f"automations/{draft['id']}")["steps"][0]["effort"] == "low"
