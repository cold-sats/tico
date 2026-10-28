"""How a run lives in the hub (backend/automations.py): saved after each step that did something and resumed from
there, each effect done once; a turn that ends before its run is saved still answers it; the chain carried through a
bot's turn; the run guard; the redesign off; the spend cap holding turns not priced yet; schedules; the find
watermark."""
import json
from datetime import datetime, timedelta, timezone

import pytest
import time_machine

from backend import automations
from backend.store import H
from backend.tests.test_api import api, assign, claim, get, headers, post, ready, runner  # noqa: F401
from backend.tests.test_automation_api import patch, turn_on
from backend.tests.test_automation_turns import draft_then_tell, finish

EVENT = {"type": "event", "name": "x.y"}


class Stop(BaseException):
    """The server stopping mid-run: nothing in the hub catches it."""


def make(api, steps, trigger=EVENT, owner="person:ana", **extra):
    return post(api, "automations", {"name": "Test", "owner": owner, "trigger": trigger, "steps": steps, **extra})["id"]


def queued(api, aid, payload=None):
    with api.app.state.store.transaction() as c:
        row = dict(c.execute("SELECT * FROM automations WHERE id=?", (aid,)).fetchone())
        return automations.queue(c, row, payload or {}, "test")


def run_row(api, rid):
    with api.app.state.store.read() as c:
        row = dict(c.execute("SELECT * FROM automation_runs WHERE id=?", (rid,)).fetchone())
    return {**row, "state": json.loads(row["state_json"] or "{}")}


def sql(api, query, args=()):
    with api.app.state.store.read() as c:
        return [dict(r) for r in c.execute(query, args)]


def hub(api):
    return api.app.state.store.automations


def turn_off(api):
    r = api.put("/api/v2/settings/redesign", json={"enabled": False}, headers=headers("ana-test"))
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------------------------- saved and resumed
def test_a_run_cut_off_after_an_effect_goes_on_from_its_save_and_does_not_do_it_twice(api, monkeypatch):
    turn_on(api)
    aid = make(api, [{"id": "spawn", "type": "action", "do": "create_task", "args": {"title": "Acme follow up",
                                                                                     "owner": "coo"}},
                     {"id": "tell", "type": "action", "do": "wake_bot", "args": {"bot": "coo", "text": "Done"}}])
    rid = queued(api, aid)
    save = automations.HubServices.checkpoint

    def stop(self, state):
        raise Stop()
    monkeypatch.setattr(automations.HubServices, "checkpoint", stop)
    with pytest.raises(Stop):
        hub(api).drain()
    monkeypatch.setattr(automations.HubServices, "checkpoint", save)
    assert run_row(api, rid)["status"] == "running"
    automations.tick(api.app.state.store, datetime.now(timezone.utc) + timedelta(minutes=20))
    done = run_row(api, rid)
    assert done["status"] == "ok" and done["state"]["resumes"] == 1
    assert [s["id"] for s in done["state"]["steps"]] == ["spawn", "tell"]
    assert len(sql(api, "SELECT id FROM tasks WHERE title='Acme follow up'")) == 1


def test_a_run_saves_after_each_step_with_an_effect(api, monkeypatch):
    turn_on(api)
    aid = make(api, [{"id": "spawn", "type": "action", "do": "create_task", "args": {"title": "Acme check"}},
                     {"id": "tell", "type": "action", "do": "wake_bot", "args": {"bot": "coo", "text": "Done"}}])
    rid = queued(api, aid)
    seen = []
    save = automations.HubServices.checkpoint

    def spy(self, state):
        save(self, state)
        seen.append([s["id"] for s in run_row(api, rid)["state"]["steps"]])
    monkeypatch.setattr(automations.HubServices, "checkpoint", spy)
    hub(api).drain()
    assert seen[:2] == [["spawn"], ["spawn", "tell"]]


def test_a_turn_that_ends_before_its_run_is_saved_still_answers_it(api, monkeypatch):
    turn_on(api)
    r = runner(api)
    assign(api, r, "ops")
    ready(api, r, ["ops"])
    aid = post(api, "automations", draft_then_tell())["id"]
    start = automations.HubServices.start_turn

    def quick(self, *args):
        started = start(self, *args)
        finish(api, r, "A quick draft")   # the bot answers before the run has saved that it waits
        return started
    monkeypatch.setattr(automations.HubServices, "start_turn", quick)
    rid = queued(api, aid)
    hub(api).drain()
    done = run_row(api, rid)
    assert done["status"] == "ok", done["state"]
    assert done["state"]["steps"][0]["outputs"]["text"] == "A quick draft"
    assert sql(api, "SELECT * FROM automation_turn_answers") == [] and sql(api, "SELECT * FROM automation_holds") == []


# ---------------------------------------------------------------------------------------------- loops
def test_a_bots_turn_started_by_an_automation_cannot_start_it_again(api):
    turn_on(api)
    r = runner(api)
    assign(api, r, "ops")
    ready(api, r, ["ops"])
    aid = make(api, [{"id": "work", "type": "bot_turn", "bot": "ops", "prompt": "Handle it"}],
               trigger={"type": "task_received", "to": "bot:coo"})
    post(api, f"automations/{aid}/run", {})
    attempt = claim(api, r)
    post(api, f"attempts/{attempt['id']}/started", {"thread_id": "t"}, token=r["token"])
    # In its turn the bot hands coo a task: a task coo received, the automation's own trigger.
    post(api, "tasks", {"owner": "coo", "title": "Acme hand-off", "body": "Please."}, token=attempt["token"])
    assert len(get(api, f"automations/{aid}/runs")["runs"]) == 1


def test_a_webhook_loop_is_paused_by_the_run_guard(api):
    turn_on(api)
    aid = make(api, [{"id": "tell", "type": "action", "do": "wake_bot", "args": {"bot": "ops", "text": "Hook"}}],
               trigger={"type": "webhook", "id": "trg_1"})
    with api.app.state.store.transaction() as c:
        for n in range(70):   # a webhook whose call calls it back: no chain links one delivery to the next
            automations.on_webhook(c, "trg_1", "Deploys", "custom", f"d{n}", {}, "")
    assert len(sql(api, "SELECT id FROM automation_runs WHERE automation_id=?", (aid,))) == automations.RUN_GUARD
    assert get(api, f"automations/{aid}")["enabled"] is False
    needs = sql(api, "SELECT owner FROM tasks WHERE title LIKE 'Automation Test paused%'")
    assert needs == [{"owner": "human:ana"}]
    assert len(sql(api, "SELECT id FROM events WHERE action='automation.run_guard' AND target=?", (aid,))) == 1


# ---------------------------------------------------------------------------------------------- the redesign off
def test_with_the_redesign_off_queued_runs_wait_and_turns_still_answer(api):
    turn_on(api)
    r = runner(api)
    assign(api, r, "ops")
    ready(api, r, ["ops"])
    aid = post(api, "automations", draft_then_tell())["id"]
    waiting = post(api, f"automations/{aid}/run", {})["run"]["id"]
    later = queued(api, aid)
    turn_off(api)
    assert hub(api).drain() == 0 and hub(api).claim() is None
    finish(api, r, "Drafted while off")
    assert run_row(api, later)["status"] == "queued" and run_row(api, later)["state"]["steps"] == []
    answered = run_row(api, waiting)
    assert answered["status"] == "queued" and answered["state"]["steps"][0]["outputs"]["text"] == "Drafted while off"
    turn_on(api)
    automations.tick(api.app.state.store)
    assert run_row(api, waiting)["status"] == "ok"


# ---------------------------------------------------------------------------------------------- the spend cap
def test_a_turn_not_priced_yet_holds_its_usual_cost_against_the_cap(api):
    turn_on(api)
    turn = {"type": "bot_turn", "bot": "ops", "prompt": "Look"}
    aid = make(api, [{"id": "one", **turn}, {"id": "two", **turn}], spend_cap={"per_30m": 0.2})
    run = post(api, f"automations/{aid}/run", {})["run"]
    assert [(s["id"], s["status"]) for s in run["steps"]] == [("one", "ok"), ("two", "spend_cap")]
    assert [h["amount"] for h in sql(api, "SELECT amount FROM automation_holds")] == [automations.TURN_COST]


# ---------------------------------------------------------------------------------------------- schedules
def test_a_rename_keeps_the_schedules_due_time(api):
    turn_on(api)
    aid = make(api, [{"id": "n", "type": "action", "do": "wake_bot", "args": {"bot": "ops"}}],
               trigger={"type": "schedule", "cron": "0 9 * * *", "tz": "UTC"})
    automations.tick(api.app.state.store, datetime(2030, 1, 1, 10, 0, tzinfo=timezone.utc))
    due = get(api, f"automations/{aid}")["next_run"]
    assert due == "2030-01-02T09:00:00.000000Z"
    assert patch(api, aid, {"name": "Renamed"})["next_run"] == due


def test_a_schedules_filters_hold_its_run(api):
    turn_on(api)
    with time_machine.travel(datetime(2030, 1, 1, 10, 0, tzinfo=timezone.utc), tick=False):
        aid = make(api, [{"id": "n", "type": "action", "do": "wake_bot", "args": {"bot": "ops"}}],
                   trigger={"type": "schedule", "cron": "0 9 * * *", "tz": "UTC",
                            "filters": [{"field": "schedule.cron", "op": "contains", "value": "never"}]})
    store = api.app.state.store
    automations.tick(store, datetime(2030, 1, 1, 10, 0, tzinfo=timezone.utc))
    automations.tick(store, datetime(2030, 1, 2, 9, 0, 30, tzinfo=timezone.utc))
    seen = get(api, f"automations/{aid}/runs")
    assert seen["runs"] == [] and seen["daily"][0]["dropped"] == 1


def test_a_sample_the_filters_drop_is_dropped_not_run(api):
    turn_on(api)
    aid = make(api, [{"id": "n", "type": "action", "do": "wake_bot", "args": {"bot": "ops"}}],
               trigger={**EVENT, "filters": [{"field": "mail.from", "op": "contains", "value": "acme.example"}]})
    assert post(api, f"automations/{aid}/run", {"input": {"mail": {"from": "x@other.example"}}}) == {
        "run": None, "dropped": True}
    seen = get(api, f"automations/{aid}/runs")
    assert seen["runs"] == [] and seen["daily"][0]["dropped"] == 1
    assert post(api, f"automations/{aid}/run", {"input": {"mail": {"from": "ana@acme.example"}}})["run"]["id"]


# ---------------------------------------------------------------------------------------------- the find watermark
FIND = {"id": "look", "type": "find", "source": "tasks", "query": "Acme batch", "limit": 1}


def test_items_with_the_same_time_are_all_found_one_page_at_a_time(api):
    turn_on(api)
    aid = make(api, [FIND])
    ids = [post(api, "tasks", {"owner": "ops", "title": f"Acme batch {n}", "body": "x"})["id"] for n in range(3)]
    with api.app.state.store.transaction() as c:
        c.execute(f"UPDATE tasks SET created=? WHERE id IN ({','.join('?' * len(ids))})", (H.now(), *ids))
    counts = [post(api, f"automations/{aid}/run", {})["run"]["steps"][0]["outputs"]["count"] for _ in range(4)]
    assert counts == [1, 1, 1, 0]


def test_the_watermark_moves_only_once_an_item_is_finished(api, monkeypatch):
    turn_on(api)
    aid = make(api, [FIND, {"id": "tell", "type": "action", "do": "wake_bot", "args": {"bot": "ops", "text": "x"}}])
    post(api, "tasks", {"owner": "ops", "title": "Acme batch one", "body": "x"})
    before = sql(api, "SELECT found_since FROM automations WHERE id=?", (aid,))[0]["found_since"]
    queued(api, aid)

    def stop(self, state):
        raise Stop()
    monkeypatch.setattr(automations.HubServices, "checkpoint", stop)
    with pytest.raises(Stop):   # cut off right after the find
        hub(api).drain()
    assert sql(api, "SELECT found_since FROM automations WHERE id=?", (aid,))[0]["found_since"] == before


# ---------------------------------------------------------------------------------------------- review 2
def test_a_resumed_run_gets_back_the_turn_it_started_and_its_own_hold_never_caps_it(api, monkeypatch):
    turn_on(api)
    aid = make(api, [{"id": "look", "type": "bot_turn", "bot": "ops", "prompt": "Look"},
                     {"id": "tell", "type": "action", "do": "wake_bot", "args": {"bot": "coo", "text": "Done"}}],
               spend_cap={"per_30m": 0.2})
    rid = queued(api, aid)
    save = automations.HubServices.checkpoint

    def stop(self, state):
        raise Stop()
    monkeypatch.setattr(automations.HubServices, "checkpoint", stop)
    with pytest.raises(Stop):   # cut off after the turn started, before the save
        hub(api).drain()
    monkeypatch.setattr(automations.HubServices, "checkpoint", save)
    automations.tick(api.app.state.store, datetime.now(timezone.utc) + timedelta(minutes=20))
    done = run_row(api, rid)
    assert [(s["id"], s["status"]) for s in done["state"]["steps"]] == [("look", "ok"), ("tell", "ok")]
    assert len(sql(api, "SELECT id FROM tasks WHERE title LIKE 'Automation Test: look (%'")) == 1


def test_two_runs_of_one_automation_each_get_their_own_turn(api):
    """A turn's task names its run, so a second run's turn is not refused as a duplicate of the first while it is open."""
    turn_on(api)
    aid = make(api, [{"id": "look", "type": "bot_turn", "bot": "ops", "prompt": "Look"}])
    runs = [queued(api, aid), queued(api, aid)]
    hub(api).drain()
    assert [run_row(api, rid)["state"]["steps"][0]["status"] for rid in runs] == ["ok", "ok"]
    titles = sorted(r["title"] for r in sql(api, "SELECT title FROM tasks WHERE title LIKE 'Automation Test: look (%'"))
    assert titles == sorted(f"Automation Test: look ({rid})" for rid in runs)


def test_a_hold_counts_until_its_turn_is_priced_and_a_lost_one_is_swept_after_a_day(api):
    turn_on(api)
    turn = {"id": "look", "type": "bot_turn", "bot": "ops", "prompt": "Look"}
    aid = make(api, [turn], spend_cap={"per_30m": 0.2})
    with api.app.state.store.transaction() as c:   # a turn started two hours ago and still going
        c.execute("INSERT INTO automation_holds(ref,automation_id,run_id,amount,at) VALUES('t_old',?,'run_old',0.25,?)",
                  (aid, H.shift(H.now(), hours=-2)))
    assert post(api, f"automations/{aid}/run", {})["run"]["steps"][0]["status"] == "spend_cap"
    automations.tick(api.app.state.store, datetime.now(timezone.utc) + timedelta(hours=25))
    assert sql(api, "SELECT ref FROM automation_holds WHERE ref='t_old'") == []
    swept = sql(api, "SELECT detail_json AS detail FROM events WHERE action='automation.hold_swept' AND target=?", (aid,))
    assert len(swept) == 1 and json.loads(swept[0]["detail"])["turn"] == "t_old"


def test_a_failed_item_is_tried_again_once_then_passed_over_and_counted(api):
    turn_on(api)
    bad = {"id": "gate", "type": "filter", "rules": [
        {"when": [{"field": "item.title", "op": "contains", "value": "bad"}], "then": [{"do": "post_update"}]}]}
    aid = make(api, [{**FIND, "limit": 10}, bad])
    ids = [post(api, "tasks", {"owner": "ops", "title": f"Acme batch {word}", "body": "x"})["id"]
           for word in ("bad", "good")]
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE tasks SET created=? WHERE id IN (?,?)", (H.now(), *ids))
    counts = [post(api, f"automations/{aid}/run", {})["run"]["steps"][0]["outputs"]["count"] for _ in range(3)]
    assert counts == [2, 1, 0]   # the good one once; the bad one twice, then passed over
    assert get(api, f"automations/{aid}/runs")["daily"][0]["dropped"] == 1


def test_an_automation_that_finds_runs_one_at_a_time(api):
    turn_on(api)
    aid = make(api, [FIND])
    first = queued(api, aid)
    assert first and queued(api, aid) is None   # the next occurrence while the first is unfinished
    assert get(api, f"automations/{aid}/runs")["daily"][0]["dropped"] == 1
    hub(api).drain()
    assert queued(api, aid)
