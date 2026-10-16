"""The company's check model as the default (backend/check_models.py `auto`, `review_default`): a check named with no
model, and a review handed to a bot set to `review_model: check`, run on another provider than the work's author."""
import json

from backend.store import encode
from backend.tests.test_api import assign, claim, get, post  # noqa: F401
from backend.tests.test_api import api  # noqa: F401  (the fixture)
from backend.tests.test_check_models import GROK, finish, heartbeat, parent_turn

CLAUDE = {"model": "claude-sonnet-5-5", "runtime": "claude", "harness": "claude", "billing": "api"}


def check_row(api, task_id):
    with api.app.state.store.read() as c:
        return c.execute("SELECT runtime,model,role FROM task_check_models WHERE task_id=?", (task_id,)).fetchone()


def test_a_check_with_no_model_takes_the_company_check_model_and_never_the_authors_provider(api):
    machine, parent, turn = parent_turn(api)
    with api.app.state.store.transaction() as c:
        # The owner's order puts Claude first; the work was written on Claude, so Claude is skipped.
        c.execute("UPDATE registry_metadata SET value_json=? WHERE key='providers'",
                  (encode({"revision": 1, "enabled": ["anthropic", "xai"], "runtime": "claude",
                           "model": "claude-sonnet-5-5", "check_models": ["claude", "grok"]}),))
    sub = post(api, "tasks", {"owner": "ops", "title": "Check the import fix", "body": "Read the PR.",
                              "check_model": "auto", "relations": [{"task": parent["id"], "kind": "parent"}]},
               turn["token"])
    assert tuple(check_row(api, sub["id"])) == ("grok", "grok-4.6", "check")
    # With only the author's provider on, it is refused rather than run there.
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE registry_metadata SET value_json=? WHERE key='providers'",
                  (encode({"revision": 2, "enabled": ["anthropic"], "runtime": "claude", "model": "claude-sonnet-5-5"}),))
    refused = post(api, "tasks", {"owner": "ops", "title": "Check it again", "body": "Read the PR.", "check_model": "auto",
                                  "relations": [{"task": parent["id"], "kind": "parent"}]}, turn["token"], expected=422)
    assert "other than Anthropic" in json.dumps(refused)


def test_a_review_for_a_bot_set_to_review_on_the_check_model_runs_there_and_says_which(api):
    machine, parent, turn = parent_turn(api)
    finish(api, machine, turn, CLAUDE)          # the parent's work ran on Claude
    plain = post(api, "tasks", {"owner": "cpo", "title": "Review PR 700", "body": "https://github.com/ticoteam/tico/pull/700",
                                "relations": [{"task": parent["id"], "kind": "parent"}]})
    assert check_row(api, plain["id"]) is None, "a bot not set to review on the check model keeps its own"
    def review_model(value):
        return post(api, "bots/cpo/definition", {"review_model": value, "expected_revision":
                    next(b for b in get(api, "bots") if b["slug"] == "cpo")["revision"]})
    review_model("check")
    review = post(api, "tasks", {"owner": "cpo", "title": "Review PR 701", "body": "https://github.com/ticoteam/tico/pull/701",
                                 "relations": [{"task": parent["id"], "kind": "parent"}]})
    assert tuple(check_row(api, review["id"])) == ("grok", "grok-4.6", "review")
    # Its own top-level work is no review of someone else's: its own model.
    own = post(api, "tasks", {"owner": "cpo", "title": "Write the weekly notes", "body": "As every week."})
    assert check_row(api, own["id"]) is None

    assign(api, machine, "cpo")
    post(api, "runners/heartbeat", {
        "version": "test", "platform": "test", "capabilities": ["task_lanes_v2", "session_roots_v1"],
        "readiness": {"schema_version": 1, "runtimes": {"claude": {"installed": True, "authenticated": "ready"},
                                                         "grok": {"installed": True, "authenticated": "ready"}},
                      "bots": {"cpo": {"runtime": "grok", "ready": True}}}}, token=machine["token"])
    run = claim(api, machine)
    while run["task"]["id"] != review["id"]:     # the bot's other two tasks, on its own model
        assert run["config"]["runtime"] != "grok"
        finish(api, machine, run)
        run = claim(api, machine)
    assert run["task"]["id"] == review["id"] and (run["config"]["runtime"], run["config"]["model"]) == ("grok", "grok-4.6")
    finish(api, machine, run, GROK, during=lambda: post(
        api, "tasks/" + review["id"], {"status": "done", "note": "Verdict: ok to merge.", "version": review["version"]},
        run["token"]))
    shown = get(api, "tasks/" + review["id"])
    assert shown["check_model"]["model"] == "grok-4.6" and shown["runs"][0]["ran_on"]["family"] == "xai"
    with api.app.state.store.read() as c:
        notices = [r[0] for r in c.execute("SELECT body FROM messages WHERE to_actor='bot:ops' AND kind='notice' "
                                           "AND body LIKE '%Review PR 701%'")]
    assert len(notices) == 1 and "Review on grok-4.6 done" in notices[0], notices
    review_model("own")
    after = post(api, "tasks", {"owner": "cpo", "title": "Review PR 702", "body": "https://github.com/ticoteam/tico/pull/702",
                                "relations": [{"task": parent["id"], "kind": "parent"}]})
    assert check_row(api, after["id"]) is None, "turned off, its reviews run on its own model again"
