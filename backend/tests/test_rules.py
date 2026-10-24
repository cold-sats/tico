"""Wake rules (backend/rules.py): every message to a bot names the rule that decided it, table rows override the
built-ins most-specific-first, the always-wake floor holds, and a run records the rule that woke it."""

import json

from backend import hubdb as H
from backend import rules as R
from backend.tests.test_api import api, get, post  # noqa: F401
from backend.tests.test_wake_rules import as_cause, claim, finish, jobs, news, parked_task, setup, skips


def rule_row(api, token="ben-test", expected=200, **body):
    body = {"scope_kind": "team", "event": "status_or_relation", "then": "note", **body}
    return post(api, "rules", body, token=token, expected=expected)


def plain_task(c, title="Plain work", clear=True):
    task = H.task_create(c, "bot:ops", title, "Do it", "bot:cpo")
    if clear:
        c.execute("DELETE FROM jobs")
    return H.task(c, task["id"])


def test_every_message_to_a_bot_names_its_rule_and_the_filters_are_unchanged(api):
    setup(api)
    post(api, "chat/cpo", {"text": "Run your check"})
    with api.app.state.store.transaction() as c:
        task, _ = parked_task(c)
        with as_cause("bot:ops"):
            held = news(c, task)
        plain = news(c, plain_task(c))
        person = H.message(c, c.execute("SELECT id FROM messages WHERE from_actor='human:ana' LIMIT 1").fetchone()[0])
    assert person["refs"]["rule"] == "person_message"
    assert held["refs"]["rule"] == "parked" and held["refs"]["quiet"] is True
    assert plain["refs"]["rule"] == "status_or_relation" and not plain["refs"].get("quiet")
    with api.app.state.store.read() as c:
        assert [s["detail"]["rule_id"] for s in skips(c)] == ["parked"]


def test_rows_override_by_scope_task_over_bot_over_team_and_the_floor_stays(api):
    setup(api)
    team = rule_row(api)["rule"]
    with api.app.state.store.transaction() as c:
        task = plain_task(c)
        msg = news(c, task)
        assert msg["refs"]["rule"] == team["id"] and msg["refs"]["quiet"] is True and jobs(c, "cpo") == 0
        assert msg["refs"]["held_by"] == "rule"
    bot = rule_row(api, scope_kind="bot", scope_id="cpo", then="wake")["rule"]
    with api.app.state.store.transaction() as c:
        assert news(c, task)["refs"]["rule"] == bot["id"] and jobs(c, "cpo") == 1
    one = rule_row(api, scope_kind="task", scope_id=task["id"], then="ignore")["rule"]
    with api.app.state.store.transaction() as c:
        msg = news(c, task)
        assert msg["refs"]["rule"] == one["id"] and msg["refs"]["held_by"] == "ignored"
        assert c.execute("SELECT count(*) FROM notes WHERE message_id=?", (msg["id"],)).fetchone()[0] == 0
    # A person's message is never made to wait, and a row cannot ask it to.
    rule_row(api, event="person_message", then="ignore", expected=422)
    rule_row(api, event="*", then="ignore")
    post(api, "chat/cpo", {"text": "Still there?"})
    with api.app.state.store.read() as c:
        last = c.execute("SELECT refs_json FROM messages WHERE from_actor='human:ana' ORDER BY rowid DESC").fetchone()
        assert json.loads(last[0])["rule"] == "person_message" and "quiet" not in json.loads(last[0])


def test_a_run_records_the_rule_that_woke_it_and_fail_open_wakes(api, monkeypatch):
    r = setup(api)
    with api.app.state.store.transaction() as c:
        news(c, plain_task(c))
    attempt = claim(api, r, "cpo")
    finish(api, r, attempt)
    with api.app.state.store.read() as c:
        assert c.execute("SELECT rule_id FROM turns WHERE id=?", (attempt["id"],)).fetchone()[0] == "status_or_relation"
    monkeypatch.setattr(R, "_judge", lambda *a, **k: 1 / 0)
    with api.app.state.store.transaction() as c:
        other = plain_task(c, "Other work", clear=False)
        before = jobs(c, "cpo")
        woke = news(c, other)
        assert woke["refs"]["rule"] == R.FAIL_OPEN and jobs(c, "cpo") == before + 1


def test_rule_writes_follow_the_scope_and_the_list_shows_builtins_and_counts(api):
    setup(api)
    rule_row(api, token="cara-test", expected=403)
    made = rule_row(api)["rule"]
    assert made["revision"] == 1 and made["enabled"] is True
    seen = get(api, "rules", token="cara-test")
    ids = {r["id"] for r in seen["rules"]}
    assert {"parked", "own_write", "person_message", made["id"]} <= ids
    row = next(r for r in seen["rules"] if r["id"] == made["id"])
    assert row["runs_7d"] == 0 and row["can_change"] is False
    post(api, f"rules/{made['id']}", {"expected_revision": 1, "then": "wake"}, token="cara-test", expected=403)
    stale = post(api, f"rules/{made['id']}", {"expected_revision": 9, "then": "wake"}, expected=409)
    assert stale["error"]["code"] == "version_conflict"
    changed = post(api, f"rules/{made['id']}", {"expected_revision": 1, "then": "wake", "on": False})["rule"]
    assert changed["revision"] == 2 and changed["then"] == "wake" and changed["enabled"] is False
    post(api, "rules/parked", {"expected_revision": 1, "then": "wake"}, expected=403)
    rule_row(api, then="action", params={"action": "nope"}, expected=422)
    rule_row(api, then="action", params={"action": "close"})
    post(api, f"rules/{made['id']}/delete", {}, token="cara-test", expected=403)
    post(api, f"rules/{made['id']}/delete", {})
    assert made["id"] not in {r["id"] for r in get(api, "rules")["rules"]}


def test_rule_weekly_counts_runs_per_rule(api):
    r = setup(api)
    with api.app.state.store.transaction() as c:
        news(c, plain_task(c))
    finish(api, r, claim(api, r, "cpo"))
    out = api.post("/api/v2/sql", json={"sql": "SELECT rule, runs FROM rule_weekly WHERE bot='cpo'"},
                   headers={"Authorization": "Bearer ana-test"})
    assert out.status_code == 200, out.text
    assert ["status_or_relation", 1] in [list(row) for row in out.json()["rows"]]
