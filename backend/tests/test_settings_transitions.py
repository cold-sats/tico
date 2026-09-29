import json

from backend.store import encode

from backend.tests.test_api import api, assign, claim, get, post, ready, runner, settled, setup_attempt


def test_structured_runner_readiness_is_stored_and_drives_claims(api):
    machine = runner(api)
    assign(api, machine, "ops")
    document = {
        "schema_version": 1,
        "runtimes": {"codex": {"installed": True, "authenticated": "ready",
                                  "version": "codex 1", "models": ["gpt-6-astra"],
                                  "controls": ["interrupt", "new-session"], "detail": "Signed in"}},
        "bots": {"ops": {"ready": True, "runtime": "codex", "model": "gpt-6-astra",
                           "repository_present": True, "repository_revision": "abc123",
                           "configuration_valid": True, "problems": [], "warnings": []}},
    }
    post(api, "runners/heartbeat", {"version": "0.2.0", "platform": "darwin",
                                    "capacity": 4, "readiness": document}, machine["token"])
    operations = get(api, "operations")
    reported = next(row for row in operations["machines"] if row["id"] == machine["runner_id"])
    assert reported["readiness"] == document
    employee = next(row for row in api.get("/api/employees", headers={"Authorization": "Bearer ana-test"}).json()
                    if row["name"] == "ops")
    assert employee["ready"] and employee["readiness"]["repository_revision"] == "abc123"
    post(api, "chat/ops", {"text": "Use the structured heartbeat"})
    assert claim(api, machine)["bot"] == "ops"


def _report(api, machine, bots):
    document = {"schema_version": 1,
                "runtimes": {"codex": {"installed": True, "authenticated": "ready",
                                          "models": [], "controls": ["interrupt", "new-session"]}},
                "bots": bots}
    post(api, "runners/heartbeat", {"version": "0.2.0", "platform": "linux",
                                    "capacity": 4, "readiness": document}, machine["token"])


def _placed(api, bot):
    with api.app.state.store.read() as c:
        return c.execute("SELECT runner_id FROM assignments WHERE bot=?", (bot,)).fetchone()[0]


def _company_default(api, bot):
    """The company runs codex / gpt-6-sol and `bot` names neither."""
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO registry_metadata VALUES('providers',?)", (encode({
            "enabled": ["openai"], "runtime": "codex", "model": "gpt-6-sol", "revision": 1}),))
        c.execute("UPDATE bot_config SET config_json=? WHERE bot=?", (encode({"name": bot}), bot))


def test_move_refuses_a_destination_that_is_not_ready_for_the_bot(api):
    _company_default(api, "cpo")
    first = runner(api, "ana", "Ana Mac")
    assign(api, first, "cpo")
    machine = runner(api, "ben", "Ben setup Mac")
    _report(api, machine, {"cpo": {
        "ready": False, "runtime": "codex", "model": "gpt-6-sol", "repository_present": False,
        "repository_revision": "", "configuration_valid": True,
        "problems": ["Missing bot repository or AGENT.md"]}})
    failure = post(api, "bots/cpo/transitions", {
        "kind": "machine", "runner_id": machine["runner_id"], "expected_revision": 1,
        "expected_generation": 1,
    }, expected=409)
    assert failure["error"]["code"] == "runner_not_ready"
    assert "repository" in failure["error"]["detail"].lower()


def test_move_compares_the_runners_report_with_the_resolved_runtime_and_model(api):
    _company_default(api, "cpo")
    first = runner(api, "ana", "Ana Mac")
    assign(api, first, "cpo")
    machine = runner(api, "ben", "Ben setup Mac")
    _report(api, machine, {"cpo": {
        "ready": True, "runtime": "codex", "model": "gpt-6-sol", "repository_present": True,
        "repository_revision": "abc", "configuration_valid": True, "problems": []}})
    moved = post(api, "bots/cpo/transitions", {
        "kind": "machine", "runner_id": machine["runner_id"], "expected_revision": 1,
        "expected_generation": 1})
    assert moved["state"] != "failed"
    assert _placed(api, "cpo") == machine["runner_id"]


def test_first_placement_needs_no_readiness_because_the_runner_reports_only_assigned_bots(api):
    machine = runner(api, "ben", "Ben setup Mac")
    _report(api, machine, {})
    post(api, "bots/cpo/transitions", {
        "kind": "machine", "runner_id": machine["runner_id"], "expected_revision": 1,
        "expected_generation": 0})
    assert _placed(api, "cpo") == machine["runner_id"]


def test_model_transition_rejects_an_effort_the_model_does_not_support(api):
    failure = post(api, "bots/ops/transitions", {
        "kind": "model", "model": "grok-4.6", "effort": "max",
        "expected_revision": 1, "expected_generation": 0,
    }, expected=422)
    assert failure["error"]["code"] == "effort"
