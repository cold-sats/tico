"""The redesign's migration (backend/redesign_migration.py, PLAN §8): dry run, resolve, convert, restore."""
import json
import pytest

from backend.tests.test_api import api, get, post, put  # noqa: F401
from backend.tests.test_automation_api import turn_on


def seed(api):
    """An Acme install as today's routes make it: a cron routine, two custom wake rules and an hourly limit."""
    routine = post(api, "bots/coo/routines", {"title": "Morning notes", "text": "Post yesterday's work.",
                                              "cron": "0 9 * * *", "timezone": "Europe/London"})["routine"]
    rules = [post(api, "rules", {"scope_kind": "bot", "scope_id": "coo", "event": event, "then": then})["rule"]
             for event, then in (("comment", "wake"), ("step_entered", "note"))]
    put(api, "usage/limits/coo", {"hourly_usd": 0.35})
    return routine, rules


def db(api):
    return api.app.state.store


def rows(api, sql, args=()):
    with db(api).read() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def migrate(api, step, body=None, token="ana-test", expected=200):
    r = api.post("/api/v2/redesign/migration/" + step, json=body or {},
                 headers={"Authorization": "Bearer " + token, "Idempotency-Key": f"{step}-{json.dumps(body)}"})
    assert r.status_code == expected, r.text
    return r.json()


def by(report, kind):
    return [o for o in report["objects"] if o["kind"] == kind]


def test_hidden_while_off_and_the_owner_only(api):
    migrate(api, "dry-run", expected=404)
    migrate(api, "convert", expected=404)
    turn_on(api)
    migrate(api, "dry-run", token="ben-test", expected=403)
    migrate(api, "convert", token="ben-test", expected=403)


def test_dry_run_lists_every_object_and_writes_nothing(api):
    routine, rules = seed(api)
    turn_on(api)
    before = rows(api, "SELECT COUNT(*) n FROM automations")[0]["n"]
    report = migrate(api, "dry-run")
    assert [o["id"] for o in by(report, "routine")] == [routine["id"]]
    wakes = by(report, "wake_rule")
    assert {o["id"] for o in wakes} == {r["id"] for r in rules}
    flow = wakes[0]["becomes"]
    assert flow["name"].startswith("What wakes") and flow["owner"] == "bot:coo"
    assert [s["type"] for s in flow["steps"]] == ["filter", "filter"]          # one Filter step per rule
    builtin = by(report, "builtin")[0]["becomes"]
    assert builtin["name"] == "What wakes bots" and builtin["readonly"] is True
    limit = [o for o in by(report, "spend_limit") if o["id"] == "limit:coo"][0]
    assert limit["becomes"] == {"per_30m_usd": 0.2, "hourly_usd": None}   # 0.35 / 2 rounded up to $0.10
    assert any(f["kind"] == "rounding" for f in limit["flags"])
    assert rows(api, "SELECT COUNT(*) n FROM automations")[0]["n"] == before
    assert rows(api, "SELECT deleted_at FROM schedules WHERE id=?", (routine["id"],))[0]["deleted_at"] is None
    assert len(rows(api, "SELECT id FROM rules WHERE id IN (?,?)", (rules[0]["id"], rules[1]["id"]))) == 2


def test_convert_waits_for_flags_then_converts_and_restore_puts_it_back(api):
    routine, rules = seed(api)
    turn_on(api)
    report = migrate(api, "dry-run")
    open_ = [f["id"] for o in report["objects"] for f in o["flags"] if not f["accepted"]]
    assert open_ and not report["ready"]
    refused = migrate(api, "convert", expected=409)
    assert refused["error"]["code"] == "flags_open" and set(refused["error"]["flags"]) == set(open_)
    migrate(api, "resolve", {"accept": ["nope#flag"]}, expected=422)
    assert migrate(api, "resolve", {"accept": open_})["ready"] is True
    due = rows(api, "SELECT next_due FROM schedules WHERE id=?", (routine["id"],))[0]["next_due"]

    done = migrate(api, "convert")
    assert not done["failed"] and done["snapshot"]["expires"]
    # The routine: soft-deleted with no next run, its automation due at the very same time (no double fire).
    old = rows(api, "SELECT deleted_at, next_due FROM schedules WHERE id=?", (routine["id"],))[0]
    assert old["deleted_at"] and old["next_due"] is None
    made = rows(api, "SELECT a.id, a.next_due FROM automations a JOIN redesign_migrated m ON m.automation=a.id "
                     "WHERE m.kind='routine' AND m.id=?", (routine["id"],))
    assert made and made[0]["next_due"] == due
    from backend import redesign_migration
    # Wake rules: the rows are gone, the decision still reads them from "What wakes".
    assert not rows(api, "SELECT id FROM rules WHERE id IN (?,?)", (rules[0]["id"], rules[1]["id"]))
    with db(api).read() as c:
        woken = redesign_migration.wake_rows(c, "comment")
    assert [r["id"] for r in woken] == [rules[0]["id"]] and woken[0]["scope_id"] == "coo"
    # The limit: a 30-minute limit of half, rounded up; the hourly one cleared.
    limit = rows(api, "SELECT hourly_usd, per_30m_usd FROM usage_limits WHERE bot='coo'")[0]
    assert limit == {"hourly_usd": None, "per_30m_usd": 0.2}
    # The built-in wake rules: one read-only automation nobody edits.
    listed = get(api, "automations")["automations"]
    builtin = [a for a in listed if a["name"] == "What wakes bots"][0]
    assert builtin["can_edit"] is False
    r = api.patch(f"/api/v2/automations/{builtin['id']}", json={"name": "Mine now"},
                  headers={"Authorization": "Bearer ana-test", "Idempotency-Key": "patch-builtin"})
    assert r.status_code == 403, r.text
    # Converted: no second convert, and the redesign stays on until restored.
    migrate(api, "convert", expected=409)
    put(api, "settings/redesign", {"enabled": False}, expected=409)

    back = migrate(api, "restore")
    assert rows(api, "SELECT state FROM redesign_migrations") == [{"state": "restored"}], back
    old = rows(api, "SELECT deleted_at, next_due FROM schedules WHERE id=?", (routine["id"],))[0]
    assert old["deleted_at"] is None and old["next_due"] == due
    assert len(rows(api, "SELECT id FROM rules WHERE id IN (?,?)", (rules[0]["id"], rules[1]["id"]))) == 2
    assert rows(api, "SELECT hourly_usd, per_30m_usd FROM usage_limits WHERE bot='coo'")[0]["hourly_usd"] == 0.35
    assert not rows(api, "SELECT id FROM automations WHERE id=? AND deleted_at IS NULL", (made[0]["id"],))
    assert not rows(api, "SELECT * FROM redesign_migrated")
    put(api, "settings/redesign", {"enabled": False})


def test_the_hubs_what_wakes_bots_is_adopted_not_doubled_and_outlives_a_restore(api):
    from backend import automations
    seed(api)
    turn_on(api)
    automations.tick(db(api))                                   # the hub makes What wakes bots
    open_ = [f["id"] for o in migrate(api, "dry-run")["objects"] for f in o["flags"] if not f["accepted"]]
    migrate(api, "convert", {"accept": open_})
    named = "SELECT id FROM automations WHERE name='What wakes bots' AND deleted_at IS NULL"
    assert rows(api, named) == [{"id": "auto_builtin_wakes"}]
    migrate(api, "restore")
    assert rows(api, named) == [{"id": "auto_builtin_wakes"}]
    put(api, "settings/redesign", {"enabled": False})


def test_the_librarians_briefing_routine_becomes_the_market_briefing_builtin_never_beside_it(api):
    """While the routine runs, the hub's Market briefing starts paused; convert gives the built-in the routine's time
    and words and turns it on; restore brings the routine back and pauses the built-in again."""
    from backend import automations
    from backend.tests.test_market import _librarian
    _librarian(api)
    routine = post(api, "bots/librarian/routines", {"title": "Market briefing", "text": "Brief the team.",
                                                    "cron": "0 7 * * 1-5", "timezone": "America/New_York"})["routine"]
    turn_on(api)
    automations.tick(db(api))
    built = "SELECT enabled, flow_json FROM automations WHERE id='auto_builtin_market_briefing' AND deleted_at IS NULL"
    assert rows(api, built)[0]["enabled"] == 0
    row = [o for o in by(migrate(api, "dry-run"), "routine") if o["id"] == routine["id"]][0]
    assert row["becomes"]["builtin"] is True and row["becomes"]["name"] == "Market briefing"
    migrate(api, "convert", {"accept": accept_all(api)})
    flow = json.loads(rows(api, built)[0]["flow_json"])
    assert rows(api, built)[0]["enabled"] == 1
    assert flow["trigger"] == {"type": "schedule", "cron": "0 7 * * 1-5", "tz": "America/New_York"}
    assert flow["steps"][0]["prompt"] == "Brief the team." and flow["steps"][1]["do"] == "post_update"
    assert rows(api, "SELECT count(*) AS n FROM automations WHERE name='Market briefing' AND deleted_at IS NULL") == [
        {"n": 1}]
    migrate(api, "restore")
    assert rows(api, built)[0]["enabled"] == 0
    assert rows(api, "SELECT deleted_at FROM schedules WHERE id=?", (routine["id"],)) == [{"deleted_at": None}]
    put(api, "settings/redesign", {"enabled": False})


def test_convert_with_accept_in_one_call_and_restore_after_a_day_is_gone(api):
    seed(api)
    turn_on(api)
    open_ = [f["id"] for o in migrate(api, "dry-run")["objects"] for f in o["flags"] if not f["accepted"]]
    done = migrate(api, "convert", {"accept": open_})
    assert done["converted"] and not done["failed"]
    from backend import redesign_migration
    with db(api).transaction() as c:
        c.execute("UPDATE redesign_migrations SET expires=?", ("2000-01-01T00:00:00.000000Z",))
    migrate(api, "restore", expected=410)
    with db(api).transaction() as c:
        redesign_migration.prune(c, "2100-01-01T00:00:00.000000Z")
    assert rows(api, "SELECT state, snapshot_json FROM redesign_migrations") == [
        {"state": "expired", "snapshot_json": None}]


def test_routine_create_while_converted_returns_the_held_row(api):
    routine, _ = seed(api)
    turn_on(api)
    open_ = [f["id"] for o in migrate(api, "dry-run")["objects"] for f in o["flags"] if not f["accepted"]]
    migrate(api, "convert", {"accept": open_})
    from backend import redesign_migration
    with db(api).read() as c:
        assert redesign_migration.holds(c, "routine", routine["id"])
        assert redesign_migration.converted(c)


def test_half_rounds_up_to_ten_cents():
    from backend.redesign_migration import half
    assert [half(v) for v in (3.0, 5.0, 0.25, 0.35, 0.2)] == [1.5, 2.5, 0.2, 0.2, 0.1]


def test_hub_tool_runs_the_dry_run_for_the_owner_only(api):
    from backend.tests.test_mcp import call
    seed(api)
    turn_on(api)
    err, report = call(api, "hub_redesign_migrate", {})
    assert not err and report["counts"]["total"] >= 3, report
    err, refused = call(api, "hub_redesign_migrate", {"action": "convert"}, token="ben-test")
    assert err and "owner" in str(refused), refused


@pytest.mark.parametrize("argv,action", [(["redesign", "migrate"], None),
                                         (["redesign", "migrate", "--restore"], "restore")])
def test_cli_flags(argv, action):
    from clients import hubcli
    ns = hubcli.parser().parse_args(argv)
    assert ns.fn == "redesign" and ns.migrate == "migrate" and ns.action == action



LONG = "Sort Acme mail by sender and urgency. " * 300                   # about 11,000 characters


def accept_all(api):
    return [f["id"] for o in migrate(api, "dry-run")["objects"] for f in o["flags"]]


def test_rehearsal_cases_team_rules_paused_bots_and_long_inbox_instructions(api):
    """What the real-data rehearsal found that the scenario fixture lacks: wake rules scoped to a department, not a
    bot; a routine on a paused bot; an Inbox Manager whose instructions run past 8,000 characters (they convert)."""
    dept = post(api, "rules", {"scope_kind": "department", "scope_id": "operations", "event": "comment",
                               "then": "wake"})["rule"]
    post(api, "bots/ops/routines", {"title": "Weekly ops check", "text": "Check the queue.", "cron": "0 8 * * 1",
                                    "timezone": "UTC"})
    with db(api).transaction() as c:
        c.execute("UPDATE bots SET state='paused' WHERE slug='ops'")
    post(api, "access/people/cara", {"inbox_bot": "inbox", "mailbox": "cara@acme.example"})
    with db(api).transaction() as c:
        c.execute("INSERT OR REPLACE INTO mail_agent_instructions(bot, content, runner_id, updated) VALUES(?,?,?,?)",
                  ("inbox", LONG, "", "2026-10-28T00:00:00Z"))
    turn_on(api)
    report = migrate(api, "dry-run")
    kinds = {f["kind"] for o in report["objects"] for f in o["flags"]}
    assert {"scope", "bot_not_active"} <= kinds and "too_long" not in kinds, kinds
    rule = [o for o in by(report, "wake_rule") if o["id"] == dept["id"]][0]
    assert rule["becomes"]["owner"] == "person:ana" and rule["becomes"]["wakes"]["scope_kind"] == "department"
    inbox = [o for o in by(report, "inbox") if o["id"] == "inbox:cara@acme.example"][0]
    assert not inbox["flags"] and inbox["becomes"]["steps"][0]["prompt"] == LONG

    done = migrate(api, "convert", {"accept": accept_all(api)})
    assert not done["failed"] and not done["kept"]
    assert {"kind": "inbox", "id": "inbox:cara@acme.example"} in [{k: c[k] for k in ("kind", "id")}
                                                                   for c in done["converted"]]
    with db(api).read() as c:
        from backend import redesign_migration
        assert [r["id"] for r in redesign_migration.wake_rows(c, "comment")] == [dept["id"]]
        assert c.execute("SELECT state FROM bots WHERE slug='inbox'").fetchone()[0] == "paused"   # retired by the convert
        made = c.execute("SELECT a.flow_json FROM automations a JOIN redesign_migrated m ON m.automation=a.id "
                         "WHERE m.kind='inbox'").fetchone()
    step = json.loads(made[0])["steps"][0]
    assert step["type"] == "llm" and step["prompt"] == LONG                # the full instructions, not cut at 8,000
    paused = [a for a in get(api, "automations")["automations"] if a["name"] == "Weekly ops check"]
    assert paused and paused[0]["enabled"] is False
