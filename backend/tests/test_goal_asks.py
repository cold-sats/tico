"""What the Goals page needs from a person is a Goal Manager task (backend/goal_asks.py): one per KPI or proposal,
kind and person, in Tasks and Decide, closed by itself once resolved."""

from datetime import datetime, timedelta, timezone

from backend import goal_asks as GA
from backend.store import H
from backend.tests.test_api import api, get, post  # noqa: F401
from backend.tests.test_kpis import goal_with_kpi, log

MANAGER = "bot:goal-manager"


def goal_manager(api):
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO bots(slug,display_name,runtime,model,effort,cwd,host,state,created) "
                  "VALUES('goal-manager','Goal Manager','fake','','','','keeper','active',?)", (H.now(),))
        c.execute("INSERT INTO bot_config(bot,config_json,team,operator) VALUES('goal-manager','{}',NULL,'ana')")


def asks(api, owner=None):
    with api.app.state.store.read() as c:
        return [dict(r) for r in c.execute(
            "SELECT t.id, t.title, t.body, t.owner, t.status, a.kind, a.ref FROM goal_asks a JOIN tasks t ON t.id=a.task_id "
            "WHERE t.requester=?" + (" AND t.owner=?" if owner else "") + " ORDER BY t.created",
            (MANAGER, owner) if owner else (MANAGER,))]


def manager_tasks(api, status):
    with api.app.state.store.read() as c:
        return [dict(r) for r in c.execute("SELECT * FROM tasks WHERE requester=? AND status=?", (MANAGER, status))]


def sync(api, at=None):
    with api.app.state.store.transaction() as c:
        return GA.sync(c, api.app.state.auth.owner_id(c), at)


def needs_tasks(api, token):
    page = get(api, "needs-you", token)
    return {str(i["id"]) for i in page["items"] + page["older"]}


def test_a_stale_kpi_is_one_task_for_its_owner_closed_by_a_fresh_reading(api):
    goal_manager(api)
    kpi = post(api, "kpis", {"name": "Unreported measure", "owner": "me", "cadence": "weekly"})["kpi"]
    [task] = asks(api, "human:ana")
    assert (task["kind"], task["ref"], task["status"]) == ("kpi_stale", kpi["id"], "open")
    assert task["title"] == "Log the first Unreported measure reading"
    assert task["body"].startswith(task["title"])
    # In Tasks and Decide (the person's Needs you), and on the Goals page with the task named.
    assert task["id"] in needs_tasks(api, "ana-test")
    [item] = [i for i in get(api, "goals/needs-you")["items"] if i.get("kpi_id") == kpi["id"]]
    assert item["kind"] == "kpi_stale" and item["task"]["id"] == task["id"]
    # Another write and the hourly pass ask nothing twice.
    post(api, "kpis", {"name": "Second measure", "owner": "me", "cadence": "weekly"})
    sync(api)
    assert [a["ref"] for a in asks(api, "human:ana")].count(kpi["id"]) == 1
    # A fresh reading closes it at once, as the Goal Manager.
    log(api, kpi["id"], 12, period_end=H.now())
    with api.app.state.store.read() as c:
        row = H.task(c, task["id"])
    assert (row["status"], row["closed_by"]) == ("closed", MANAGER)
    assert all(i.get("kpi_id") != kpi["id"] for i in get(api, "goals/needs-you")["items"])
    # Time passing makes it stale again: the hourly pass asks again, in a new task.
    later = datetime.now(timezone.utc) + timedelta(days=20)
    made = sync(api, later)["created"]
    [again] = [a for a in asks(api, "human:ana") if a["ref"] == kpi["id"]]
    assert again["status"] == "open" and again["id"] != task["id"] and again["id"] in made


def test_a_red_kpi_asks_the_goal_owner_and_closes_once_back_on_track(api):
    goal_manager(api)
    goal, kpi = goal_with_kpi(api, token="ben-test", owner="ben")
    log(api, kpi["id"], 10, token="ben-test", period_end=H.now())
    red = [a for a in asks(api, "human:ben") if a["kind"] == "kpi_red"]
    assert [(a["ref"], a["title"]) for a in red] == [(kpi["id"], "Check why Activation is off track on Raise activation")]
    assert red[0]["id"] in needs_tasks(api, "ben-test")
    assert red[0]["id"] not in needs_tasks(api, "ana-test")
    log(api, kpi["id"], 75, token="ben-test", period_end=H.now())
    assert not [a for a in asks(api) if a["kind"] == "kpi_red"]
    assert red[0]["id"] in {t["id"] for t in manager_tasks(api, "closed")}


def test_a_proposal_asks_whoever_decides_it_and_closes_when_decided(api):
    goal_manager(api)
    goal, kpi = goal_with_kpi(api, token="ben-test", owner="ben")
    log(api, kpi["id"], 45, token="ben-test", period_end=H.now())
    proposal = post(api, "goal-proposals", {"kind": "kpi_target", "goal_id": goal["id"], "kpi_id": kpi["id"],
                    "reason": "The deadline cannot be met at this pace",
                    "payload": {"kind": "improve", "baseline": 40, "target": 60, "deadline": "2099-12-31"}},
                    token="ben-test")["proposal"]
    [task] = [a for a in asks(api) if a["kind"] == "proposal"]
    assert (task["ref"], task["owner"]) == (proposal["id"], "human:ben")
    assert task["title"] == "Confirm or reject a new Activation target on Raise activation"
    [item] = [i for i in get(api, "goals/needs-you", "ben-test")["items"] if i["kind"] == "proposal"]
    assert item["task"]["id"] == task["id"] and item["proposal"]["id"] == proposal["id"]
    post(api, f"goal-proposals/{proposal['id']}/decide", {"decision": "reject", "note": "Keep it"}, token="ben-test")
    with api.app.state.store.read() as c:
        row = H.task(c, task["id"])
    assert row["status"] == "closed" and "rejected" in row["note"]


def test_a_task_the_person_closed_is_not_asked_again_while_the_cause_stands(api):
    goal_manager(api)
    kpi = post(api, "kpis", {"name": "Unreported measure", "owner": "me", "cadence": "weekly"})["kpi"]
    [task] = asks(api, "human:ana")
    with api.app.state.store.transaction() as c:
        H.task_update(c, "human:ana", task["id"], status="declined", note="Not tracking this one")
    sync(api)
    assert [a["id"] for a in asks(api) if a["ref"] == kpi["id"]] == [task["id"]]
    assert all(i.get("kpi_id") != kpi["id"] for i in get(api, "goals/needs-you")["items"])


def test_an_owner_change_moves_the_ask_and_without_a_goal_manager_nothing_is_filed(api):
    goal, kpi = goal_with_kpi(api, token="ben-test", owner="ben")
    log(api, kpi["id"], 10, token="ben-test", period_end=H.now())
    # No Goal Manager: no task, and the Goals page still says what waits.
    assert not asks(api)
    assert any(i["kind"] == "kpi_red" and "task" not in i for i in get(api, "goals/needs-you", "ben-test")["items"])
    goal_manager(api)
    sync(api)
    [old] = [a for a in asks(api) if a["kind"] == "kpi_red"]
    assert old["owner"] == "human:ben"
    post(api, f"goals/{goal['id']}", {"owner": "cara"})
    [new] = [a for a in asks(api) if a["kind"] == "kpi_red"]
    assert new["owner"] == "human:cara" and new["id"] != old["id"]
    assert old["id"] in {t["id"] for t in manager_tasks(api, "closed")}
