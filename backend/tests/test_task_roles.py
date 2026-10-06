"""Roles on a task (backend/task_roles.py): the people in each role are kept in task_roles under any
role name, a step says which role it waits on and a type which role its owner holds, every task
answer says who it waits on now with the owner as the fallback, `waiting_on` lists exactly those
tasks, and the rules on who may name people hold."""
from backend import hubdb as H
from backend import task_roles as TRo
from backend.tests.test_api import api, get, post  # noqa: F401  (fixtures)


def board(api):
    typ = post(api, "task-types", {"name": "Dev ticket", "numbered": True, "steps": [
        {"name": "On Deck", "status": "open"}, {"name": "In Progress", "status": "doing"},
        {"name": "QA/PR Rejected", "status": "doing"}, {"name": "PR Review", "status": "review"},
        {"name": "Waiting on QA", "status": "review"}, {"name": "Pending Dev Push to Prod", "status": "ready"},
        {"name": "Dev Owned QA", "status": "ready"}, {"name": "Done", "status": "closed"}]})["type"]
    return typ, {s["name"]: s for s in typ["steps"]}


def test_a_board_copied_before_steps_could_say_gets_its_defaults_by_column_name(api):
    typ, steps = board(api)
    assert typ["owner_role"] == "developer", "a ticket board's owner is its developer"
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE task_steps SET waits_on=NULL WHERE type_id=?", (typ["id"],))
        c.execute("UPDATE task_steps SET waits_on='reviewer' WHERE id=?", (steps["Dev Owned QA"]["id"],))
        c.execute("UPDATE task_types SET owner_role=NULL WHERE id=?", (typ["id"],))
        TRo.migrate(c)
        TRo.migrate(c)
        got = {r[0]: r[1] for r in c.execute("SELECT name, waits_on FROM task_steps WHERE type_id=?", (typ["id"],))}
        assert c.execute("SELECT owner_role FROM task_types WHERE id=?", (typ["id"],)).fetchone()[0] == "developer"
    assert got == {"On Deck": "developer", "In Progress": "developer", "QA/PR Rejected": "developer", "PR Review": "reviewer",
                   "Waiting on QA": "qa", "Pending Dev Push to Prod": "qa", "Dev Owned QA": "reviewer", "Done": None}
    # A type made now says it on each step; a mover sets any role name, and what is set stays set.
    assert get(api, "task-types/" + typ["id"])["type"]["steps"][3]["waits_on"] == "reviewer"
    clean = lambda s, **more: {**{k: s[k] for k in ("id", "name", "position", "status", "waits_on")}, **more}
    kept = post(api, "task-types/" + typ["id"], {"owner_role": "builder", "steps": [
        clean(s, waits_on="product-owner" if s["name"] == "Dev Owned QA" else s["waits_on"]) for s in typ["steps"]]})["type"]
    assert {s["name"]: s["waits_on"] for s in kept["steps"]}["Dev Owned QA"] == "product-owner" and kept["owner_role"] == "builder"
    post(api, "task-types/" + typ["id"], {"steps": [clean(typ["steps"][0], waits_on="Code Reviewer!")]}, expected=422)
    post(api, "task-types/" + typ["id"], {"owner_role": "Dev Lead"}, expected=422)
    assert post(api, "task-types/" + typ["id"], {"owner_role": ""})["type"]["owner_role"] is None


def test_moving_a_task_hands_it_to_the_role_its_step_waits_on_and_the_owner_holds_it_otherwise(api):
    typ, steps = board(api)
    t = post(api, "tasks", {"owner": "ben", "title": "(B) Fix the refund page", "body": "x", "type": typ["id"],
                            "step": "In Progress", "roles": {"reviewer": ["cara"]}}, token="ben-test")
    assert t["roles"] == {"reviewer": ["human:cara"]}
    assert t["waits_on"] == {"role": "developer", "actors": ["human:ben"], "assigned": True}, "the owner is the developer"
    # To review: the reviewer's. Rejected: the developer's again. To QA with nobody on QA: the owner keeps it.
    t = post(api, "tasks/" + t["id"], {"version": t["version"], "step": "PR Review"}, token="ben-test")
    assert t["waits_on"] == {"role": "reviewer", "actors": ["human:cara"], "assigned": True}
    t = post(api, "tasks/" + t["id"], {"version": t["version"], "step": "QA/PR Rejected"}, token="cara-test")
    assert t["waits_on"]["actors"] == ["human:ben"], "a reviewer may send it back without owning it"
    t = post(api, "tasks/" + t["id"], {"version": t["version"], "step": "Waiting on QA"}, token="ben-test")
    assert t["waits_on"] == {"role": "qa", "actors": ["human:ben"], "assigned": False}
    # Naming QA, a second developer (the owner is never repeated) and a role of the team's own is one update.
    t = post(api, "tasks/" + t["id"], {"version": t["version"], "roles": {"qa": ["ana", "ana"], "developer": ["ben", "cara"],
                                                                         "designer": ["cara"]}}, token="ben-test")
    assert t["roles"] == {"reviewer": ["human:cara"], "qa": ["human:ana"], "developer": ["human:cara"], "designer": ["human:cara"]}
    assert t["waits_on"] == {"role": "qa", "actors": ["human:ana"], "assigned": True}
    t = post(api, "tasks/" + t["id"], {"version": t["version"], "step": "In Progress"}, token="ben-test")
    assert t["waits_on"]["actors"] == ["human:ben", "human:cara"], "the owner first, then the other developers"
    # The list filter is the same reading: Ana's list has it only while QA holds it; a finished task waits on nobody.
    ids = lambda who, token="ana-test": [x["id"] for x in get(api, "tasks?waiting_on=" + who, token=token)["tasks"]]
    assert t["id"] in ids("ben") and t["id"] not in ids("ana") and t["id"] in ids("cara")
    t = post(api, "tasks/" + t["id"], {"version": t["version"], "step": "Waiting on QA"}, token="ben-test")
    assert t["id"] in ids("ana") and t["id"] not in ids("ben")
    t = post(api, "tasks/" + t["id"], {"version": t["version"], "roles": {"qa": []}}, token="ben-test")
    assert "qa" not in t["roles"] and t["id"] in ids("ben") and t["id"] not in ids("ana"), "with QA cleared the owner holds it again"
    t = post(api, "tasks/" + t["id"], {"version": t["version"], "step": "Done"}, token="ben-test")
    assert t["waits_on"] == {"role": None, "actors": [], "assigned": True}
    get(api, "tasks?waiting_on=nobody-here", expected=422)
    # Each change is in the history, and the list carries the same fields as the task.
    history = {(e["field"], e["old"], e["new"]) for e in get(api, "tasks/" + t["id"])["events"]}
    assert ("role:reviewer", None, "human:cara") in history and ("role:qa", "human:ana", None) in history
    row = next(x for x in get(api, "tasks?status=all&type=" + typ["id"])["tasks"] if x["id"] == t["id"])
    assert row["roles"]["designer"] == ["human:cara"] and row["waits_on"]["actors"] == []
    # A task with no board waits on its owner, whatever roles it carries.
    todo = post(api, "tasks", {"owner": "ben", "title": "Write the launch post", "body": "x", "roles": {"editor": ["cara"]}}, token="ben-test")
    assert todo["waits_on"] == {"role": None, "actors": ["human:ben"], "assigned": True} and todo["roles"] == {"editor": ["human:cara"]}


def test_only_someone_who_may_change_the_task_names_its_people_and_only_people_on_the_roster(api):
    typ, steps = board(api)
    t = post(api, "tasks", {"owner": "ben", "title": "(B) Fix the refund page", "body": "x", "type": typ["id"], "step": "On Deck"},
             token="ben-test")
    post(api, "tasks/" + t["id"], {"version": t["version"], "roles": {"reviewer": ["cara"]}}, token="cara-test", expected=403)
    post(api, "tasks/" + t["id"], {"version": t["version"], "roles": {"reviewer": ["nobody"]}}, token="ben-test", expected=422)
    post(api, "tasks/" + t["id"], {"version": t["version"], "roles": {"Code Reviewer!": ["cara"]}}, token="ben-test", expected=422)
    assert get(api, "tasks/" + t["id"])["task"]["roles"] == {}
    # A private task names only its parties.
    secret = post(api, "tasks", {"owner": "ben", "title": "Review the salary file", "body": "x", "private": True}, token="ana-test")
    post(api, "tasks/" + secret["id"], {"version": secret["version"], "roles": {"reviewer": ["cara"]}}, token="ben-test", expected=422)
    s = post(api, "tasks/" + secret["id"], {"version": secret["version"], "roles": {"reviewer": ["ana"]}}, token="ben-test")
    assert s["roles"]["reviewer"] == ["human:ana"]
    # In SQL the rows follow the task's own visibility; a deleted task takes its people to the trash and back.
    with api.app.state.store.transaction() as c:
        assert H.task(c, t["id"]) and TRo.roles_of(c, s["id"])["reviewer"] == ["human:ana"]
    post(api, "tasks/" + s["id"] + "/delete", {}, token="ana-test")
    post(api, "tasks/" + s["id"] + "/restore", {}, token="ana-test")
    assert get(api, "tasks/" + s["id"], token="ana-test")["task"]["roles"]["reviewer"] == ["human:ana"]
