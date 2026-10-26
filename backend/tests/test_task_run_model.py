"""A task a person gives a bot on a model they name (backend/check_models.py `named`, POST /api/v2/tasks and
/api/v2/tasks/{id}/model): its turns run on that model, effort and harness while the bot's other work keeps its own,
and only a person who manages the bot may name or change one."""
import json

import pytest

from backend import check_models
from backend.store import H
from backend.tests.test_api import api, assign, claim, get, post, runner  # noqa: F401  (api is a fixture)
from backend.tests.test_check_models import all_ready, company, finish, later, out_of_quota


def ops_on_claude(api):
    """ops on Claude, the company on Anthropic, OpenAI and xAI, its computer ready for all three."""
    company(api, "anthropic", "openai", "xai")
    with api.app.state.store.transaction() as c:
        config = json.loads(c.execute("SELECT config_json FROM bot_config WHERE bot='ops'").fetchone()[0])
        config.update(runtime="claude", harness="claude", model="claude-sonnet-5-5",
                      fallback={"harness": "codex", "model": "gpt-6.1-sol"})
        c.execute("UPDATE bot_config SET config_json=? WHERE bot='ops'", (json.dumps(config),))
    machine = runner(api)
    assign(api, machine, "ops")
    all_ready(api, machine)
    return machine


def test_a_task_runs_on_the_model_its_person_named_and_the_bots_other_work_keeps_its_own(api):
    machine = ops_on_claude(api)
    review = post(api, "tasks", {"owner": "ops", "title": "Review PR 812", "body": "https://github.com/acme/app/pull/812",
                                 "model": "grok-4.6", "effort": "xhigh"})
    other = post(api, "tasks", {"owner": "ops", "title": "Answer the customer", "body": "Reply about the import."})

    turn = claim(api, machine)
    assert turn["task"]["id"] == review["id"]
    config = turn["config"]
    assert (config["runtime"], config["model"], config["harness"], config["reasoning_effort"]) == (
        "grok", "grok-4.6", "grok", "xhigh")
    assert config["fallback"] == {"off": True}, "the model asked for, or the task waits"
    assert config["session"] == "task" and turn["lane"] == "task:" + review["id"]
    finish(api, machine, turn, {"model": "grok-4.6", "runtime": "grok", "harness": "grok", "billing": "api"},
           during=lambda: post(api, "tasks/" + review["id"], {"status": "done", "note": "Approved.",
                                                               "version": turn["task"]["version"]}, turn["token"]))
    nxt = claim(api, machine)
    assert nxt["task"]["id"] == other["id"] and nxt["config"]["runtime"] == "claude"
    shown = get(api, "tasks/" + review["id"])
    assert shown["check_model"] == {"runtime": "grok", "model": "grok-4.6", "harness": "grok", "effort": "xhigh",
                                    "role": "task"}
    with api.app.state.store.read() as c:
        named = c.execute("SELECT actor,new FROM task_events WHERE task_id=? AND field='check_model'",
                          (review["id"],)).fetchone()
        assert (named["actor"], named["new"]) == ("human:ana", "grok:grok-4.6"), "history names who chose it"


@pytest.mark.parametrize("token, body, status, words", [
    ("cara-test", {"model": "grok-4.6"}, 403, "manages this bot"),          # a person who does not manage ops
    (None, {"model": "grok-4.6"}, 403, "manages this bot"),                 # the bot itself, in its own turn
    ("ana-test", {"effort": "high"}, 422, "along with its effort"),
    ("ana-test", {"model": "grok-4.6", "check_model": "grok"}, 422, "not both"),
    ("ana-test", {"model": "grok-4.6", "owner": "cara"}, 422, "bot's task"),
    ("ana-test", {"model": "grok-4.6", "effort": "max"}, 422, "takes the effort"),
    ("ana-test", {"model": "cursor"}, 422, "enabled"),                     # a provider the company has not enabled
])
def test_only_a_person_who_manages_the_bot_names_an_offered_model(api, token, body, status, words):
    machine = ops_on_claude(api)
    if token is None:
        post(api, "tasks", {"owner": "ops", "title": "Plan the week", "body": "Draft it."})
        token = claim(api, machine)["token"]
    refused = post(api, "tasks", {"owner": "ops", "title": "Review PR 813", "body": "Read it.", **body}, token,
                   expected=status)
    assert words in json.dumps(refused)
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM task_check_models").fetchone()[0] == 0
        assert not c.execute("SELECT 1 FROM tasks WHERE title='Review PR 813'").fetchone()


def test_an_open_tasks_model_changes_and_goes_back_to_the_bots_own_from_its_next_turn(api):
    machine = ops_on_claude(api)
    task = post(api, "tasks", {"owner": "ops", "title": "Review PR 814", "body": "Read it.", "next_run": True})
    post(api, f"tasks/{task['id']}/model", {"model": "grok-4.6"}, "cara-test", expected=403)
    set_ = post(api, f"tasks/{task['id']}/model", {"model": "codex:gpt-6.1-sol", "effort": "high"})
    assert set_["run_model"]["model"] == "gpt-6.1-sol" and set_["run_model"]["effort"] == "high"
    post(api, f"tasks/{task['id']}/model", {"model": "codex:gpt-6.1-sol", "effort": "high"}, expected=409)
    post(api, f"tasks/{task['id']}/run-now", {})
    assert claim(api, machine)["config"]["model"] == "gpt-6.1-sol"

    post(api, f"tasks/{task['id']}/model", {"model": ""}, "cara-test", expected=403)
    cleared = post(api, f"tasks/{task['id']}/model", {"model": ""})
    assert cleared["run_model"] is None
    post(api, f"tasks/{task['id']}/model", {"model": ""}, expected=409)
    with api.app.state.store.read() as c:
        assert H.check_model(c, task["id"]) is None


def test_a_check_subtasks_model_stays_its_filers(api):
    machine = ops_on_claude(api)
    parent = post(api, "tasks", {"owner": "ops", "title": "Ship the import fix", "body": "Open the PR."})
    turn = claim(api, machine)
    sub = post(api, "tasks", {"owner": "ops", "title": "Review it on Grok", "body": "Read it.", "check_model": "grok",
                              "relations": [{"task": parent["id"], "kind": "parent"}]}, turn["token"])
    for change in ({"model": ""}, {"model": "codex"}):
        refused = post(api, f"tasks/{sub['id']}/model", change, expected=409)
        assert "check subtask" in json.dumps(refused)
    with api.app.state.store.read() as c:
        assert H.check_model(c, sub["id"])["role"] == "check"


def test_a_limit_on_the_named_model_holds_the_task_rather_than_moving_it(api, monkeypatch):
    machine = ops_on_claude(api)
    task = post(api, "tasks", {"owner": "ops", "title": "Review PR 815", "body": "Read it.", "model": "codex"})
    turn = claim(api, machine)
    assert turn["task"]["id"] == task["id"] and turn["config"]["runtime"] == "codex"
    start = H.now()
    out_of_quota(api, machine, turn)
    later(api, monkeypatch, machine, H.shift(start, minutes=31))
    again = claim(api, machine)
    assert again["task"]["id"] == task["id"] and again["config"]["runtime"] == "codex"
    out_of_quota(api, machine, again)
    # A check would move to the next check model now; a model a person named waits for its own reset.
    assert claim(api, machine) is None
    with api.app.state.store.read() as c:
        assert not c.execute("SELECT 1 FROM registry_metadata WHERE key=?", ("check-moved:" + task["id"],)).fetchone()
        assert check_models.held(c, task["id"])
