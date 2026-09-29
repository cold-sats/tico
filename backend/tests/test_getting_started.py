"""Getting started: every tick is computed from live state, and each person keeps their own choices."""

import json

from backend.store import H, encode

from backend.tests.test_onboarding import as_person, environment, machine, signed_in  # noqa: F401


def items(api, headers=None):
    body = api.get("/api/v2/getting-started", headers=headers or signed_in()).json()
    return body, {row["id"]: row for row in body["items"]}


def body_of(api):
    return api.get("/api/v2/getting-started", headers=signed_in()).json()


def heartbeat(api, runner_id, *, seconds_ago=0, runtimes=None):
    """A runner's last word, as the heartbeat stores it."""
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE runners SET last_seen=?, readiness_json=? WHERE id=?",
                  (H.shift(H.now(), seconds=-seconds_ago),
                   json.dumps({"schema_version": 1, "runtimes": runtimes or {}, "bots": {}}), runner_id))


def enrolled(api):
    machine(api)
    with api.app.state.store.read() as c:
        return c.execute("SELECT id FROM runners").fetchone()["id"]


def activate(api, *slugs):
    with api.app.state.store.transaction() as c:
        for slug in slugs:
            c.execute("UPDATE bots SET state='active' WHERE slug=?", (slug,))


def add_bot(api, slug, state="active"):
    with api.app.state.store.transaction() as c:
        H.sync_registry(c, {slug: {"name": slug, "status": state}}, None)


SIGNED_IN = {"codex": {"installed": True, "authenticated": "ready"}}


def test_a_fresh_company_has_only_the_first_step(environment):
    api = environment()
    body, rows = items(api)
    assert rows["signed_in"]["done"] is True
    assert not any(rows[k]["done"] for k in ("computer", "model", "github", "botops", "first_bot",
                                               "bot_task", "first_update"))
    assert (body["done"], body["total"], body["complete"]) == (1, 8, False)
    assert rows["first_bot"]["action"] == "create-bot"
    assert rows["computer"]["why"] and rows["computer"]["tab"] == "devices"


def test_botops_first_bot_task_and_update_follow_the_database(environment):
    api = environment()
    assert items(api)[1]["botops"]["done"] is False
    activate(api, "botops")
    assert items(api)[1]["botops"]["done"] is True

    # The assistant is one of the two bots the company starts with, so it is not a first bot.
    activate(api, "coo")
    assert items(api)[1]["first_bot"]["done"] is False
    add_bot(api, "support")
    assert items(api)[1]["first_bot"]["done"] is True
    assert items(api)[1]["bot_task"]["done"] is False

    with api.app.state.store.transaction() as c:
        task = H.task_create(c, "human:morgan", "Answer the queue", "Reply to today's tickets.",
                             "bot:support", allow_planned=True)
    assert items(api)[1]["bot_task"]["done"] is False
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE tasks SET status='done' WHERE id=?", (task["id"],))
    assert items(api)[1]["bot_task"]["done"] is True

    assert items(api)[1]["first_update"]["done"] is False
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO updates(id,bot,kind,day,headline,body,created,updated) VALUES(?,?,?,?,?,?,?,?)",
                  ("u1", "support", "daily", "2026-01-05", "Cleared the queue", "- Cleared it", H.now(), H.now()))
    assert items(api)[1]["first_update"]["done"] is True


def test_each_person_sees_only_what_they_can_act_on(environment):
    api = environment()
    riley = as_person(api, "riley")                # a bot administrator
    quinn = as_person(api, "quinn")                # neither
    assert [r["id"] for r in items(api)[0]["items"]] == [
        "signed_in", "computer", "model", "github", "botops", "first_bot", "bot_task", "first_update"]
    assert [r["id"] for r in items(api, riley)[0]["items"]] == [
        "signed_in", "botops", "first_bot", "bot_task", "first_update"]
    assert [r["id"] for r in items(api, quinn)[0]["items"]] == ["signed_in", "bot_task", "first_update"]


def test_a_bot_or_runner_cannot_read_it(environment):
    api = environment()
    assert api.get("/api/v2/getting-started").status_code in (401, 403)


def test_a_new_bot_is_a_task_for_botops_and_needs_botops_active(environment):
    api = environment()
    ask = {"what": "Answer the support inbox every morning", "name": "Help Desk"}
    refused = api.post("/api/v2/getting-started/bot", json=ask, headers=signed_in())
    assert refused.status_code == 409
    activate(api, "botops")
    made = api.post("/api/v2/getting-started/bot", json=ask, headers=signed_in())
    assert made.status_code == 200, made.text
    assert made.json()["slug"] == "help-desk"
    task = api.get("/api/v2/tasks", params={"owner": "botops"}, headers=signed_in()).json()["tasks"][0]
    assert task["title"] == "Build a bot: Help Desk"
    assert "Answer the support inbox every morning" in task["body"]
    assert "- slug: help-desk" in task["body"]
    # The server record exists already, planned, so the bot is on the chart and can take routines.
    with api.app.state.store.read() as c:
        row = c.execute("SELECT b.state,b.model,g.repo,g.description,g.reports_to FROM bots b "
                        "JOIN bot_config g ON g.bot=b.slug WHERE b.slug='help-desk'").fetchone()
    assert (row["state"], row["repo"], row["description"]) == \
        ("planned", "emp-help-desk", "Answer the support inbox every morning")
    assert row["reports_to"].startswith("human:") and row["model"]
    assert "already created, state planned" in task["body"]
    chart = api.get("/api/v2/org", headers=signed_in()).json()
    owner = row["reports_to"].split(":", 1)[1]
    assert any(b["id"] == "help-desk" for b in chart["bots"])
    assert any(owner in (b.get("reports_to") or "") for b in chart["bots"] if b["id"] == "help-desk")
    # A planned bot already counts as the first one, so the rail card and the checklist step settle.
    assert items(api)[1]["first_bot"]["done"] is True
    # A second request with the same name gets its own slug and record.
    again = api.post("/api/v2/getting-started/bot", json=ask, headers=signed_in())
    assert again.status_code == 200, again.text
    assert again.json()["slug"] == "help-desk-2"
    with api.app.state.store.read() as c:
        assert H.bot(c, "help-desk-2")["state"] == "planned"
    # While BotOps works, the checklist points at the task instead of asking again.
    row = items(api)[1]["first_bot"]
    assert row["href"].startswith("#/task/") and row["action"] == ""
    # A person who neither owns the company nor administers bots cannot ask.
    assert api.post("/api/v2/getting-started/bot", json=ask,
                    headers=as_person(api, "quinn")).status_code == 403

