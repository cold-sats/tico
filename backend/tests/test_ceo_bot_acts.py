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
