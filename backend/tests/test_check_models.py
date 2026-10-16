"""A bot's subtask on a check model (backend/check_models.py): its turns run on the named model in a session of their
own, its provenance names that model, and the verdict comes back to the parent's session."""
import json

import pytest

from backend.store import H, encode
from backend.tests.test_api import api, assign, claim, get, post, runner  # noqa: F401  (api is a fixture)

GROK = {"model": "grok-4.6", "runtime": "grok", "harness": "grok", "billing": "api"}


def company(api, *enabled):
    with api.app.state.store.transaction() as c:
        c.execute("DELETE FROM registry_metadata WHERE key='providers'")
        c.execute("INSERT INTO registry_metadata VALUES('providers',?)",
                  (encode({"revision": 1, "enabled": list(enabled), "runtime": "claude", "model": "claude-sonnet-5-5"}),))


def heartbeat(api, machine, grok="ready"):
    post(api, "runners/heartbeat", {
        "version": "test", "platform": "test", "capabilities": ["task_lanes_v2", "session_roots_v1"],
        "readiness": {"schema_version": 1,
                      "runtimes": {"claude": {"installed": True, "authenticated": "ready"},
                                   "grok": {"installed": True, "authenticated": grok}},
                      "bots": {"ops": {"runtime": "claude", "ready": True}}}}, token=machine["token"])


def parent_turn(api):
    """ops on Claude, working a person's task: its claimed turn."""
    company(api, "anthropic", "xai")
    with api.app.state.store.transaction() as c:
        config = json.loads(c.execute("SELECT config_json FROM bot_config WHERE bot='ops'").fetchone()[0])
        config.update(runtime="claude", harness="claude", model="claude-sonnet-5-5",
                      fallback={"harness": "codex", "model": "gpt-6.1-sol"})
        c.execute("UPDATE bot_config SET config_json=? WHERE bot='ops'", (json.dumps(config),))
    machine = runner(api)
    assign(api, machine, "ops")
    heartbeat(api, machine)
    parent = post(api, "tasks", {"owner": "ops", "title": "Ship the import fix", "body": "Open the PR and get it reviewed."})
    turn = claim(api, machine)
    assert turn["task"]["id"] == parent["id"] and turn["config"]["runtime"] == "claude"
    return machine, parent, turn


def finish(api, machine, turn, segment=None, during=None):
    post(api, f"attempts/{turn['id']}/started", {"thread_id": "t-" + turn["id"][:8]}, machine["token"])
    if during:
        during()
    usage = {**segment, "input_tokens": 30, "output_tokens": 30, "segments": [
        {**segment, "input_tokens": 30, "output_tokens": 30}]} if segment else None
    post(api, f"attempts/{turn['id']}/complete", {"outcome": "completed", "last_seq": 0, "text": "Done.",
                                                  **({"usage": usage} if usage else {})}, machine["token"])


def test_a_review_subtask_runs_on_grok_in_its_own_session_and_its_verdict_wakes_the_parent(api):
    machine, parent, turn = parent_turn(api)
    sub = post(api, "tasks", {"owner": "ops", "title": "Review PR 700 with another model",
                              "body": "https://github.com/ticoteam/tico/pull/700", "check_model": "grok",
                              "check_role": "review", "relations": [{"task": parent["id"], "kind": "parent"}]},
               turn["token"])
    finish(api, machine, turn)

    check = claim(api, machine)
    assert check["task"]["id"] == sub["id"]
    assert check["task"]["check"] == {"runtime": "grok", "model": "grok-4.6", "role": "review"}
    config = check["config"]
    assert (config["runtime"], config["model"], config["harness"]) == ("grok", "grok-4.6", "grok")
    assert config["fallback"] == {"off": True}, "a check never hops to another provider"
    assert config["session"] == "task" and config["subtask_session"] == "own"
    assert check["lane"] == "task:" + sub["id"] and check["task"]["session_task_id"] == sub["id"]
    assert all(m.get("conversation_id") == sub["conversation_id"] for m in check["history"])
    finish(api, machine, check, GROK, during=lambda: post(
        api, "tasks/" + sub["id"], {"status": "done", "note": "Verdict: OK to merge; one nit on naming.",
                                         "version": sub["version"]}, check["token"]))
    shown = get(api, "tasks/" + sub["id"])
    assert shown["runs"][0]["ran_on"]["segments"][0]["model"] == "grok-4.6"
    assert shown["check_model"]["model"] == "grok-4.6" and shown["check_model"]["role"] == "review"
    back = claim(api, machine)
    assert back["task"]["id"] == parent["id"]
    assert back["config"]["runtime"] == "claude" and "check" not in back["task"]
    assert "Review on grok-4.6 done: Review PR 700 with another model" in back["message"]["body"]
    assert "Verdict: OK to merge" in back["message"]["body"]


def test_a_parents_turn_after_the_check_keeps_the_bots_own_session(api):
    machine, parent, turn = parent_turn(api)
    post(api, "tasks", {"owner": "ops", "title": "Check the migration with Grok", "body": "Read the migration plan.",
                        "check_model": "grok:grok-4.6", "relations": [{"task": parent["id"], "kind": "parent"}]},
         turn["token"])
    with api.app.state.store.read() as c:
        assert H.session_root(c, "ops", parent["id"]) == parent["id"]
        sub = c.execute("SELECT task_id,role FROM task_check_models").fetchone()
    assert sub["role"] == "check"
    with api.app.state.store.read() as c:
        assert H.session_root(c, "ops", sub["task_id"]) == sub["task_id"], "a check is never the parent's session"


@pytest.mark.parametrize("body, status, words", [
    ({"check_model": "cursor"}, 422, "enabled"),                       # the company has not enabled that provider
    ({"check_model": "grok", "owner": "coo"}, 422, "subtask it owns"),  # another bot's subtask
    ({"check_model": "grok", "relations": []}, 422, "under a task you own"),
])
def test_a_check_model_names_only_what_the_company_enabled_for_the_bots_own_subtask(api, body, status, words):
    machine, parent, turn = parent_turn(api)
    ask = {"owner": "ops", "title": "Review the change", "body": "Read it.",
           "relations": [{"task": parent["id"], "kind": "parent"}], **body}
    refused = post(api, "tasks", ask, turn["token"], expected=status)
    assert words in json.dumps(refused)
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM task_check_models").fetchone()[0] == 0


def test_a_person_cannot_file_one_and_a_signed_out_runtime_is_refused_and_not_handed_the_turn(api):
    machine, parent, turn = parent_turn(api)
    post(api, "tasks", {"owner": "ops", "title": "Review it", "body": "Read it.", "check_model": "grok",
                        "relations": [{"task": parent["id"], "kind": "parent"}]}, expected=422)
    heartbeat(api, machine, grok="missing")
    refused = post(api, "tasks", {"owner": "ops", "title": "Review it on Grok", "body": "Read it.",
                                  "check_model": "grok", "relations": [{"task": parent["id"], "kind": "parent"}]},
                   turn["token"], expected=409)
    assert refused["code"] == "runner_not_ready" if "code" in refused else "runner_not_ready" in json.dumps(refused)
    heartbeat(api, machine)
    sub = post(api, "tasks", {"owner": "ops", "title": "Review it on Grok", "body": "Read it.", "check_model": "grok",
                              "relations": [{"task": parent["id"], "kind": "parent"}]}, turn["token"])
    finish(api, machine, turn)
    heartbeat(api, machine, grok="missing")
    assert claim(api, machine) is None, "a computer signed out of Grok is not handed the check"
    heartbeat(api, machine)
    assert claim(api, machine)["task"]["id"] == sub["id"]
