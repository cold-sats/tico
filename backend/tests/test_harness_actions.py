"""Keeping a computer's model CLIs current from Settings: owner-only, audited, and relayed to the
runner the way the browser sign-in is."""

from backend.store import H
from backend.tests.test_api import api, get, post, put, runner  # noqa: F401
from backend.tests.test_model_login import stored  # noqa: F401  (a row reader shared with the sign-in tests)

HARNESS = {"name": "Codex", "runtime": "codex", "installed": True, "version": "0.158.0", "managed": True,
           "source": "tools", "pinned": False, "pin": "", "authenticated": "ready", "update_available": True,
           "latest": "0.160.0", "wanted": True, "state": "idle", "detail": ""}


def beat(api, r, **harnesses):
    body = {"version": "test", "platform": "test",
            "readiness": {"schema_version": 1, "runtimes": {}, "bots": {}, "harnesses": harnesses}}
    return post(api, "runners/heartbeat", body, token=r["token"])


def online(api, **overrides):
    r = runner(api)
    beat(api, r, codex={**HARNESS, **overrides})
    return r


def ask(api, r, action="update", harness="codex", **kw):
    return post(api, f"runners/{r['runner_id']}/harness-actions", {"harness": harness, "action": action}, **kw)


def events(api, action):
    with api.app.state.store.read() as c:
        return [dict(row) for row in c.execute("SELECT * FROM events WHERE action=?", (action,))]


def rows(api):
    with api.app.state.store.read() as c:
        return [dict(row) for row in c.execute("SELECT * FROM runner_harness_actions")]


def test_the_heartbeat_stores_the_harness_report_and_the_devices_page_serves_it(api):
    r = online(api)
    machine = get(api, "operations")["machines"][0]
    codex = machine["readiness"]["harnesses"]["codex"]
    assert (codex["version"], codex["pinned"], codex["update_available"]) == ("0.158.0", False, True)
    assert machine["harness_actions"] == []


def test_a_report_with_an_unknown_field_is_refused_rather_than_stored(api):
    r = runner(api)
    post(api, "runners/heartbeat", {"version": "t", "platform": "t", "readiness": {
        "schema_version": 1, "runtimes": {}, "bots": {}, "harnesses": {"codex": {**HARNESS, "surprise": 1}}}},
         token=r["token"], expected=422)


def test_only_the_owner_asks_and_a_runner_cannot_ask_for_itself(api):
    r = online(api)
    ask(api, r, token="ben-test", expected=403)
    ask(api, r, token=r["token"], expected=403)
    assert rows(api) == []
    # Nor may another person read the pending requests through the owner's page.
    assert get(api, "operations", token="ben-test")["machines"] == []


def test_an_action_is_relayed_to_the_runner_reported_and_audited(api):
    r = online(api)
    first = ask(api, r)
    assert (first["state"], first["action"], first["harness"]) == ("requested", "update", "codex")
    assert ask(api, r)["id"] == first["id"]                     # one at a time per action
    assert get(api, "runner-harness-actions", token=r["token"])["actions"] == [
        {"id": first["id"], "harness": "codex", "action": "update"}]
    post(api, f"runner-harness-actions/{first['id']}/report", {"state": "running"}, token=r["token"])
    assert get(api, "operations")["machines"][0]["harness_actions"][0]["state"] == "running"
    post(api, f"runner-harness-actions/{first['id']}/report",
         {"state": "done", "message": "Codex is at 0.160.0"}, token=r["token"])
    assert get(api, "runner-harness-actions", token=r["token"])["actions"] == []
    # Final: a late report cannot reopen it.
    assert post(api, f"runner-harness-actions/{first['id']}/report", {"state": "failed"}, token=r["token"])["state"] == "done"
    done = get(api, "operations")["machines"][0]["harness_actions"][0]
    assert (done["state"], done["message"]) == ("done", "Codex is at 0.160.0")
    assert [e["actor"] for e in events(api, "runner.harness.update")] == ["human:ana"]
    assert [e["actor"] for e in events(api, "runner.harness.done")] == ["runner:" + r["runner_id"]]


def test_pin_and_unpin_are_actions_too(api):
    r = online(api, pinned=True, pin="0.158.0")
    assert ask(api, r, "unpin")["action"] == "unpin"
    assert ask(api, r, "pin")["action"] == "pin"
    assert [e["action"] for e in events(api, "runner.harness.pin")] == ["runner.harness.pin"]
    assert len(events(api, "runner.harness.unpin")) == 1


def test_one_runner_cannot_report_on_or_read_anothers_requests(api):
    r, other = online(api), online(api)
    request = ask(api, r)
    post(api, f"runner-harness-actions/{request['id']}/report", {"state": "done"}, token=other["token"], expected=404)
    assert get(api, "runner-harness-actions", token=other["token"])["actions"] == []


def test_the_action_needs_a_known_harness_a_managed_install_and_an_online_computer(api):
    r = online(api)
    ask(api, r, harness="grok", expected=404)                    # never reported
    ask(api, r, harness="Bad Name!", expected=422)
    post(api, f"runners/{r['runner_id']}/harness-actions", {"harness": "codex", "action": "reinstall"}, expected=422)
    post(api, "runners/nope/harness-actions", {"harness": "codex", "action": "update"}, expected=404)
    beat(api, r, codex={**HARNESS, "managed": False, "source": "path"})
    assert ask(api, r, expected=409)                             # the person's own install
    beat(api, r, codex=HARNESS)
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE runners SET last_seen=? WHERE id=?", (H.shift(H.now(), seconds=-600), r["runner_id"]))
    ask(api, r, expected=409)                                    # offline
    assert rows(api) == []


def test_a_request_the_computer_never_answers_expires(api):
    r = online(api)
    request = ask(api, r)
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE runner_harness_actions SET created=? WHERE id=?",
                  (H.shift(H.now(), hours=-7), request["id"]))
    assert get(api, "runner-harness-actions", token=r["token"])["actions"] == []
    assert rows(api)[0]["state"] == "failed"


def test_the_runner_learns_the_enabled_providers_from_the_config(api):
    r = runner(api)
    assert get(api, "config", token=r["token"])["enabled_providers"] == []
    put(api, "providers", {"enabled": ["openai", "moonshot"], "runtime": "", "model": "", "expected_revision": 0})
    assert get(api, "config", token=r["token"])["enabled_providers"] == ["openai", "moonshot"]
