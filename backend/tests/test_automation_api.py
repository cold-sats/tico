"""Automations over the API (backend/automations.py): dormant while the redesign is off, save and edit as versions with
an audit row each, restore, delete, built-ins, run now and its run record, and paged lists."""
import json

from backend.tests.test_api import api, get, headers, post  # noqa: F401

NOTE_STEP = {"id": "tell", "type": "action", "enabled": True, "do": "wake_bot", "args": {"bot": "ops", "text": "Look"}}


def turn_on(api, token="ana-test"):
    r = api.put("/api/v2/settings/redesign", json={"enabled": True}, headers=headers(token))
    assert r.status_code == 200, r.text
    return r.json()


def flow(**extra):
    return {"name": "Morning check", "owner": "person:ana", "trigger": {"type": "schedule", "cron": "0 9 * * *", "tz": "UTC"},
            "steps": [NOTE_STEP], **extra}


def make(api, token="ana-test", expected=200, **extra):
    return post(api, "automations", flow(**extra), token, expected=expected)


def patch(api, aid, body, token="ana-test", expected=200):
    r = api.patch(f"/api/v2/automations/{aid}", json=body, headers=headers(token))
    assert r.status_code == expected, r.text
    return r.json()


def audit_rows(api, target):
    with api.app.state.store.read() as c:
        return [dict(r) for r in c.execute("SELECT * FROM audit_log WHERE target=? ORDER BY id", (target,))]


def test_everything_is_404_while_the_redesign_is_off(api):
    assert get(api, "settings/redesign") == {"enabled": False}
    post(api, "automations", flow(), expected=404)
    get(api, "automations", expected=404)
    get(api, "automations/auto_x/runs", expected=404)


def test_only_the_owner_turns_the_redesign_on(api):
    r = api.put("/api/v2/settings/redesign", json={"enabled": True}, headers=headers("ben-test"))
    assert r.status_code == 403
    assert turn_on(api) == {"enabled": True}
    assert get(api, "settings/redesign", "ben-test") == {"enabled": True}
    assert audit_rows(api, "redesign")[-1]["actor"] == "human:ana"


def test_save_edit_versions_and_restore(api):
    turn_on(api)
    made = make(api)
    aid = made["id"]
    assert aid.startswith("auto_") and made["version"] == 1 and made["owner"] == "person:ana"
    edited = patch(api, aid, {"name": "Morning check · weekdays", "enabled": False})
    assert edited["version"] == 2 and edited["enabled"] is False
    assert patch(api, aid, {"enabled": False})["version"] == 2            # nothing changed: no new version
    versions = get(api, f"automations/{aid}/versions")["versions"]
    assert [v["n"] for v in versions] == [2, 1] and versions[1]["flow"]["name"] == "Morning check"
    restored = post(api, f"automations/{aid}/versions/1/restore", {})
    assert restored["version"] == 3 and restored["name"] == "Morning check" and restored["enabled"] is True
    post(api, f"automations/{aid}/versions/9/restore", {}, expected=404)
    rows = audit_rows(api, aid)
    assert [r["action"] for r in rows] == ["create", "update", "restore 1"]
    assert rows[0]["before"] is None and json.loads(rows[1]["before"])["enabled"] is True
    assert json.loads(rows[1]["after"])["enabled"] is False and all(r["actor"] == "human:ana" for r in rows)


def test_a_bad_flow_is_refused_with_why(api):
    turn_on(api)
    body = make(api, expected=422, steps=[{"id": "x", "type": "paths", "paths": [
        {"name": f"p{i}", "when": [], "steps": []} for i in range(11)]}])
    assert "1 to 10 paths" in json.dumps(body)
    assert "not on the team" in json.dumps(make(api, expected=422, owner="bot:nobody"))


def test_delete_and_builtins(api):
    turn_on(api)
    aid = make(api)["id"]
    post(api, f"automations/{aid}/delete", {})
    get(api, f"automations/{aid}", expected=404)
    assert audit_rows(api, aid)[-1]["action"] == "delete"
    builtin = make(api, builtin=True, owner="bot:ops")["id"]
    r = api.delete(f"/api/v2/automations/{builtin}", headers=headers())
    assert r.status_code == 409
    paused = patch(api, builtin, {"enabled": False})
    assert paused["enabled"] is False and "warning" in paused


def test_only_the_top_pauses_or_makes_a_builtin(api):
    turn_on(api)
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bot_config SET reports_to='human:ben' WHERE bot='ops'")
    make(api, "ben-test", expected=403, builtin=True, owner="bot:ops")
    builtin = make(api, builtin=True, owner="bot:ops")["id"]
    patch(api, builtin, {"name": "Renamed by Ben"}, "ben-test")          # ops reports to Ben: he may edit it
    patch(api, builtin, {"enabled": False}, "ben-test", expected=403)


def test_run_now_runs_the_flow_and_records_each_step(api):
    turn_on(api)
    aid = make(api, steps=[NOTE_STEP, {"id": "off", "type": "action", "enabled": False, "do": "note", "args": {}}])["id"]
    run = post(api, f"automations/{aid}/run", {})["run"]
    assert run["status"] == "ok" and run["version"] == 1 and run["finished"]
    assert [(s["id"], s["status"]) for s in run["steps"]] == [("tell", "ok"), ("off", "skipped")]
    with api.app.state.store.read() as c:
        woke = c.execute("SELECT body, refs_json FROM messages WHERE to_actor='bot:ops' ORDER BY created DESC").fetchone()
    assert woke["body"] == "Look" and json.loads(woke["refs_json"])["automation"] == aid
    runs = get(api, f"automations/{aid}/runs")
    assert runs["runs"][0]["id"] == run["id"] and runs["daily"][0]["runs"] == 1
    assert get(api, "automations")["automations"][0]["last_run"]["id"] == run["id"]


def test_a_run_that_fails_says_which_step(api):
    turn_on(api)
    aid = make(api, steps=[{"id": "tell", "type": "action", "do": "wake_bot", "args": {"bot": "nobody"}}])["id"]
    run = post(api, f"automations/{aid}/run", {})["run"]
    assert run["status"] == "failed" and run["steps"][0]["status"] == "failed"
    assert "nobody" in run["steps"][0]["outputs"]["detail"]


def test_lists_are_paged(api):
    turn_on(api)
    for n in range(3):
        make(api, name=f"Check {n}")
    first = get(api, "automations?limit=2")
    assert len(first["automations"]) == 2 and first["next"] == 2
    rest = get(api, f"automations?limit=2&cursor={first['next']}")
    assert len(rest["automations"]) == 1 and rest["next"] is None
