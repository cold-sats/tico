"""What the CEO Bot does alone at level 3 and what it never does (backend/ceo_acts.py; spec: Head of Product, CEO Bot,
tests 9, 12 and 15). A decision changes bot tasks under one action id, logged with its reason; the owner undoes it
without overwriting a later edit; anything on the owner's list, at any level, is refused on the server and becomes a
proposal in their Needs you, and so does a change a bot offline can't take."""

from backend import ceo_bot
from backend.store import H
from backend.tests.test_api import api, get, headers, post  # noqa: F401
from backend.tests.test_ceo_bot_level import level
from backend.tests.test_ceo_bot_suggests import bot_task
from backend.tests.test_company import bot, with_ceo_bot
from backend.tests.test_kpis import goal_with_kpi

OWNER, CEO = "human:ana", "bot:goal-manager"


def decide(api, token, changes, reason="Activation is red; setup work goes first", expected=200):
    return post(api, "ceo-bot/decisions", {"reason": reason, "changes": changes}, token=token, expected=expected)


def task(api, task_id):
    with api.app.state.store.read() as c:
        return H.task(c, task_id)


def proposals(api):
    with api.app.state.store.read() as c:
        return [dict(r) for r in c.execute("SELECT * FROM tasks WHERE requester=? AND owner=? AND title LIKE 'Decide %' "
                                           "ORDER BY created", (CEO, OWNER))]


def test_at_level_3_one_decision_changes_bot_tasks_under_one_action_id_and_the_owner_undoes_it(api):
    """Spec test 12: a decision made alone is one entry in the log with its reason, every task event it wrote carries
    its action id, and Undo puts the tasks back and tells their bots; a field a person changed since keeps their
    change, and the owner is told what wasn't restored. Below level 3, or for any other bot, nothing is decided."""
    ceo = with_ceo_bot(api)
    bot(api, "ops")
    bot(api, "finance")
    first = bot_task(api, "ops", "Write the onboarding email")
    second = bot_task(api, "ops", "Clean up old reports")
    stale = bot_task(api, "ops", "Draft the old pricing page")
    changes = [{"do": "create", "owner": "ops", "title": "Fix the setup step that drops new accounts"},
               {"do": "reorder", "task_id": second},
               {"do": "reassign", "task_id": first, "owner": "finance"},
               {"do": "close", "task_id": stale, "note": "Pricing moved to next quarter"}]
    level(api, 2)
    decide(api, ceo, changes, expected=422)                     # level 2 suggests; it decides nothing alone
    level(api, 3)
    decide(api, bot(api, "ops"), changes, expected=403)        # only the CEO Bot decides alone
    made = decide(api, ceo, changes)
    assert made["state"] == "done" and not made["left"] and len(made["done"]) == 4
    assert task(api, first)["owner"] == "bot:finance" and task(api, stale)["status"] == "closed"
    new = made["done"][0]["task_id"]
    with api.app.state.store.read() as c:
        stamped = {r[0] for r in c.execute("SELECT DISTINCT task_id FROM task_events WHERE action_id=?", (made["id"],))}
    assert {first, second, stale} <= stamped

    log = get(api, "ceo-bot/log")
    assert log["items"][0]["id"] == made["id"] and log["items"][0]["reason"].startswith("Activation is red")
    assert log["can_undo"] is True
    post(api, f"ceo-bot/log/{made['id']}/undo", {}, token=ceo, expected=403)     # never the bot itself

    # A person moves the reassigned task on after the decision: Undo keeps their change and says so.
    with api.app.state.store.transaction() as c:
        H.task_update(c, OWNER, first, owner="bot:ops", mover=True)
        H.task_update(c, OWNER, first, owner="bot:finance", mover=True)
    undone = post(api, f"ceo-bot/log/{made['id']}/undo", {})
    assert undone["state"] == "undone"
    assert task(api, stale)["status"] == "open" and task(api, new)["status"] == "closed"
    assert task(api, first)["owner"] == "bot:finance"                  # the person's later edit stays
    assert "owner was changed since" in undone["undo"]["text"]
    with api.app.state.store.read() as c:
        told = c.execute("SELECT COUNT(*) FROM messages m WHERE m.from_actor=? AND m.body LIKE '%undid a decision%'",
                         (H.KEEPER,)).fetchone()[0]
    assert told >= 2
    post(api, f"ceo-bot/log/{made['id']}/undo", {}, expected=422)       # once


def test_a_change_a_bot_offline_or_a_person_would_take_becomes_one_proposal_never_dropped(api):
    """Spec test 15 and the person's task of test 9: what the decision can't make alone is one proposal in the owner's
    Needs you with the reason in plain words, and the rest still happens."""
    ceo = with_ceo_bot(api)
    bot(api, "ops")
    level(api, 3)
    paused = bot_task(api, "ops", "Rewrite the welcome page")
    with api.app.state.store.transaction() as c:
        H.task_create(c, "bot:finance", "Close the books", "Work it.", "bot:finance", lint=False)
        c.execute("UPDATE bots SET state='paused' WHERE slug='finance'")
    made = decide(api, ceo, [{"do": "reorder", "task_id": paused},
                             {"do": "create", "owner": "finance", "title": "Pause the signup campaign"},
                             {"do": "create", "owner": OWNER, "title": "Call the three biggest customers"}])
    assert made["state"] == "done" and len(made["done"]) == 1 and len(made["left"]) == 2
    asked = proposals(api)
    assert len(asked) == 1 and asked[0]["id"] == made["proposal_task"]
    assert "is paused right now" in asked[0]["body"] and "a task for a person stays the person's" in asked[0]["body"]


def test_everything_on_the_owners_list_is_refused_on_the_server_and_proposed_instead(api):
    """Spec test 9, one case per kind, at level 3 where the CEO Bot does most: a cost, a publish, an outside send's
    invitation, a bot added or removed, a goal or target change, the vision, a bot's instructions and a person's
    task. Each is refused (409 `proposed`), changes nothing, is logged and offered to the owner, and is not counted as
    one of the bot's mistakes."""
    ceo = with_ceo_bot(api)
    bot(api, "ops")
    level(api, 3)
    goal, kpi = goal_with_kpi(api)
    with api.app.state.store.transaction() as c:          # a task it asked for, so it may otherwise change it
        mine = H.task_create(c, CEO, "Write the onboarding email", "Work it.", "bot:ops", lint=False)["id"]
    tries = [
        ("cost", "bots/goal-manager/routines", {"title": "Check KPIs every hour", "cron": "0 * * * *"}),
        ("cost", "bots/ops/model", {"model": "opus", "expected_revision": 1}),
        ("publish", "tasks", {"title": "Share the roadmap", "body": "Publish it.", "owner": "bot:ops",
                              "visibility": "public", "public_title": "Our roadmap"}),
        ("send", "calendar/appointments", {"calendar": "ana@acme.example", "title": "Intro call",
                                           "start": "2099-01-01T09:00:00+00:00", "end": "2099-01-01T09:30:00+00:00",
                                           "attendees": ["buyer@other.example"]}),
        ("bots", "bots/ops/archive", {"expected_revision": 1}),
        ("target", f"goals/{goal['id']}/kpis/{kpi['id']}", {"kind": "improve", "baseline": 40, "target": 50,
                                                           "deadline": "2099-12-31"}),
        ("vision", "company", {"vision": "Rule the world"}),
        ("instructions", "bots/ops/definition", {"description": "Only ever work on growth",
                                                   "expected_revision": 1}),
        ("person_task", f"tasks/{mine}", {"owner": OWNER, "version": task(api, mine)["version"]}),
    ]
    for kind, path, body in tries:
        r = api.post("/api/v2/" + path, json=body, headers=headers(ceo))
        assert r.status_code == 409 and "proposal" in r.text, (kind, r.text)
    with api.app.state.store.read() as c:
        assert not c.execute("SELECT 1 FROM schedules WHERE bot='goal-manager' AND title='Check KPIs every hour'"
                             ).fetchone()
        assert c.execute("SELECT state FROM bots WHERE slug='ops'").fetchone()[0] == "active"
        assert H.task(c, mine)["owner"] == "bot:ops"
        assert not c.execute("SELECT 1 FROM calendar_actions").fetchone()
        assert not c.execute("SELECT 1 FROM refusals WHERE actor=?", (CEO,)).fetchone()
    log = get(api, "ceo-bot/log")["items"]
    assert [x["kind"] for x in log][::-1] == [k for k, _, _ in tries] and all(x["state"] == "proposed" for x in log)
    # Each is in the owner's Needs you until its 5 a day are used (its other asks count too); the rest wait in the log,
    # saying so.
    with api.app.state.store.read() as c:
        assert ceo_bot.room_today(c, OWNER) == 0
    assert proposals(api) and all(x["proposal_task"] or "5 items there today" in x["note"] for x in log)
    assert not any(x["undoable"] for x in log)


def test_undo_never_overwrites_a_later_edit_and_puts_back_everything_else(api):
    """Spec test 12, Undo's edges: a later move in the queue (even one back to where the decision put it), a task it
    made that a person took on, two changes to one task, a close on a steps-only ticket from its second open step with
    a note, and a task whose restore is refused. Each later edit stays and is named; the rest goes back; a form holding
    the task from before the decision or the Undo gets a version conflict."""
    ceo = with_ceo_bot(api)
    for slug in ("ops", "finance", "coo"):
        bot(api, slug)
    level(api, 3)
    typ = post(api, "task-types", {"name": "Dev ticket", "steps_only": True, "bots": "work", "steps": [
        {"name": "Backlog", "status": "open"}, {"name": "On Deck", "status": "open"},
        {"name": "Done", "status": "closed"}]})["type"]
    ticket = post(api, "tasks", {"owner": "ops", "title": "Fix the guest message times", "body": "Please.",
                                 "type": typ["id"], "step": "On Deck"})["id"]
    with api.app.state.store.transaction() as c:
        H.task_update(c, OWNER, ticket, note="Waiting on the copy")
    moved, back, twice, refused = (bot_task(api, "ops", t) for t in (
        "Write the onboarding email", "Clean up old reports", "Draft the pricing page", "Plan the launch"))
    bot_task(api, "ops", "Answer the support inbox")
    bot_task(api, "coo", "Review the budget")
    with api.app.state.store.transaction() as c:
        H.task_update(c, OWNER, refused, owner="bot:coo", mover=True)
    start = {t: task(api, t) for t in (moved, back, twice, refused, ticket)}
    made = decide(api, ceo, [{"do": "reassign", "task_id": moved, "owner": "finance"},
                             {"do": "reassign", "task_id": back, "owner": "finance"},
                             {"do": "reorder", "task_id": twice}, {"do": "reorder", "task_id": twice},
                             {"do": "reassign", "task_id": refused, "owner": "finance"},
                             {"do": "close", "task_id": ticket},
                             {"do": "create", "owner": "ops", "title": "Fix the setup step that drops new accounts"}])
    assert made["state"] == "done" and len(made["done"]) == 7, made["left"]
    post(api, f"tasks/{moved}", {"version": start[moved]["version"], "due": "2099-01-01T00:00:00+00:00"},
         expected=409)
    new = made["done"][-1]["task_id"]
    with api.app.state.store.transaction() as c:
        H.task_update(c, OWNER, moved, rank=-50, mover=True)                       # a person reorders it
        decided = H.task(c, back)["rank"]
        H.task_update(c, OWNER, back, rank=-60, mover=True)                        # ...and away and back
        H.task_update(c, OWNER, back, rank=decided, mover=True)
        H.task_update(c, OWNER, new, owner=OWNER, status="doing", mover=True)      # a person takes on what it made
        c.execute("UPDATE bot_config SET config_json=? WHERE bot='coo'", ('{"harness": "dots"}',))
    held = task(api, ticket)["version"]
    post(api, f"ceo-bot/log/{made['id']}/undo", {}, token="ben-test", expected=403)        # an admin doesn't undo
    undone = post(api, f"ceo-bot/log/{made['id']}/undo", {})
    post(api, f"tasks/{ticket}", {"version": held, "due": "2099-01-01T00:00:00+00:00"}, expected=409)
    text = undone["undo"]["text"]
    now = {t: task(api, t) for t in (moved, back, twice, refused, ticket, new)}
    # The person's place in the queue stays, and the owner still goes back.
    assert now[moved]["owner"] == "bot:ops" and now[moved]["rank"] == -50
    assert now[back]["owner"] == "bot:ops" and now[back]["rank"] == decided
    assert '"Write the onboarding email": its place in the queue was changed since by' in text
    assert '"Clean up old reports": its place in the queue was changed since by' in text
    # Two moves of one task go back to where it started, with no later edit claimed.
    assert now[twice]["rank"] == start[twice]["rank"] and '"Draft the pricing page": its' not in text.split("Not")[-1]
    # The ticket is back in its own step, place and note.
    assert (now[ticket]["status"], now[ticket]["step_id"], now[ticket]["note"]) == (
        "open", start[ticket]["step_id"], "Waiting on the copy")
    assert now[ticket]["step_rank"] == start[ticket]["step_rank"] and not now[ticket]["closed_at"]
    # What a person took on stays theirs and open; a refused restore is said and the rest still went back.
    assert (now[new]["owner"], now[new]["status"]) == (OWNER, "doing") and "which it made, was changed since" in text
    assert now[refused]["owner"] == "bot:finance" and '"Plan the launch" could not be put back' in text
    with api.app.state.store.read() as c:
        told = {r[0] for r in c.execute("SELECT to_actor FROM messages WHERE from_actor=? AND body LIKE "
                                        "'%undid a decision%'", (H.KEEPER,))}
    assert {"bot:ops", "bot:finance"} <= told
